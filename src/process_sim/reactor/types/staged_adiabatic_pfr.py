"""多段断熱 PFR 反応器。"""

from __future__ import annotations

from dataclasses import dataclass

from process_sim.constants.physical_properties import SPECIES_PHYSICAL_PROPERTIES, SpeciesPhysicalProperty
from process_sim.constants.reaction_networks import ReactionNetwork, STYRENE_SIX_REACTION_NETWORK
from process_sim.constants.universal import UNIVERSAL_CONSTANTS, UniversalConstants
from process_sim.reactor.core.balance import ReactorBalanceContext, pfr_adiabatic_derivatives
from process_sim.reactor.core.integrator import rk4_step
from process_sim.reactor.core.models import (
    ReactorProfilePoint,
    ReactorResult,
    ReactorRunConditions,
    ReactorRunLog,
    ReactorStageLog,
    ReactorState,
)
from process_sim.reactor.core.stream import COMPONENT_ORDER, ReactorFeed, ReactorStream
from process_sim.reactor.core.thermodynamics import species_enthalpy_kj_per_kmol


@dataclass(frozen=True)
class StagedAdiabaticPfrModel:
    """多段断熱PFRモデル。"""

    network: ReactionNetwork = STYRENE_SIX_REACTION_NETWORK
    properties: dict[str, SpeciesPhysicalProperty] | None = None
    universal: UniversalConstants = UNIVERSAL_CONSTANTS

    def run(self, feed: ReactorFeed, conditions: ReactorRunConditions) -> ReactorResult:
        """多段断熱PFRを計算する。"""
        if conditions.segments_per_stage <= 0:
            raise ValueError("segments_per_stage must be positive")
        if conditions.profile_points_per_stage <= 0:
            raise ValueError("profile_points_per_stage must be positive")
        if len(conditions.stage_inlet_temperatures_c) != len(conditions.stage_lengths_m):
            raise ValueError("stage_inlet_temperatures_c and stage_lengths_m must have the same length")
        if not conditions.stage_lengths_m:
            raise ValueError("stage_lengths_m must not be empty")

        properties = self.properties or SPECIES_PHYSICAL_PROPERTIES
        feed_vector = feed.to_vector_kmol_s()
        cross_section_area_m2, inlet_volumetric_flow_m3_s = self._cross_section_area(
            stream=feed,
            temperature_k=conditions.stage_inlet_temperatures_c[0] + 273.15,
            pressure_kpa=conditions.pressure_kpa,
            superficial_velocity_m_per_s=conditions.inlet_superficial_velocity_m_per_s,
        )

        current_vector = feed_vector[:]
        current_temperature_k = conditions.stage_inlet_temperatures_c[0] + 273.15
        profile_points: list[ReactorProfilePoint] = []
        stage_logs: list[ReactorStageLog] = []
        cumulative_length_m = 0.0

        for stage_index, (stage_inlet_temperature_c, stage_length_m) in enumerate(
            zip(conditions.stage_inlet_temperatures_c, conditions.stage_lengths_m, strict=True),
            start=1,
        ):
            stage_inlet_stream = ReactorStream.from_vector_kmol_s(current_vector)
            inlet_velocity_m_per_s = self._superficial_velocity(
                stream=stage_inlet_stream,
                temperature_k=stage_inlet_temperature_c + 273.15,
                pressure_kpa=conditions.pressure_kpa,
                cross_section_area_m2=cross_section_area_m2,
            )
            self._append_profile_point(
                profile_points=profile_points,
                stage_index=stage_index,
                axial_position_m=0.0,
                cumulative_length_m=cumulative_length_m,
                temperature_c=stage_inlet_temperature_c,
                stream=stage_inlet_stream,
                feed=feed,
            )

            current_temperature_k = stage_inlet_temperature_c + 273.15
            dz = stage_length_m / float(conditions.segments_per_stage)
            profile_stride = max(1, conditions.segments_per_stage // conditions.profile_points_per_stage)
            balance_context = ReactorBalanceContext(
                pressure_kpa=conditions.pressure_kpa,
                cross_section_area_m2=cross_section_area_m2,
                network=self.network,
                properties=properties,
                universal=self.universal,
            )

            for segment_index in range(conditions.segments_per_stage):
                state_vector = current_vector + [current_temperature_k]
                next_state = rk4_step(
                    state_vector=state_vector,
                    dz=dz,
                    derivative=lambda values: pfr_adiabatic_derivatives(values, balance_context),
                )
                current_vector = [max(value, 0.0) for value in next_state[: len(COMPONENT_ORDER)]]
                current_temperature_k = max(next_state[len(COMPONENT_ORDER)], 273.15)

                if (segment_index + 1) % profile_stride == 0 or segment_index == conditions.segments_per_stage - 1:
                    stage_outlet_stream = ReactorStream.from_vector_kmol_s(current_vector)
                    self._append_profile_point(
                        profile_points=profile_points,
                        stage_index=stage_index,
                        axial_position_m=(segment_index + 1) * dz,
                        cumulative_length_m=cumulative_length_m + (segment_index + 1) * dz,
                        temperature_c=current_temperature_k - 273.15,
                        stream=stage_outlet_stream,
                        feed=feed,
                    )

            stage_outlet_stream = ReactorStream.from_vector_kmol_s(current_vector)
            outlet_temperature_c = current_temperature_k - 273.15
            outlet_velocity_m_per_s = self._superficial_velocity(
                stream=stage_outlet_stream,
                temperature_k=current_temperature_k,
                pressure_kpa=conditions.pressure_kpa,
                cross_section_area_m2=cross_section_area_m2,
            )
            reheat_duty_mw = None
            if stage_index < len(conditions.stage_inlet_temperatures_c):
                next_inlet_temperature_k = conditions.stage_inlet_temperatures_c[stage_index] + 273.15
                reheat_duty_mw = self._reheat_duty_mw(
                    stream=stage_outlet_stream,
                    from_temperature_k=current_temperature_k,
                    to_temperature_k=next_inlet_temperature_k,
                    properties=properties,
                )

            stage_logs.append(
                ReactorStageLog(
                    stage_index=stage_index,
                    inlet_temperature_c=stage_inlet_temperature_c,
                    outlet_temperature_c=outlet_temperature_c,
                    stage_length_m=stage_length_m,
                    inlet_superficial_velocity_m_per_s=inlet_velocity_m_per_s,
                    outlet_superficial_velocity_m_per_s=outlet_velocity_m_per_s,
                    eb_conversion=self._eb_conversion(feed=feed, stream=stage_outlet_stream),
                    styrene_selectivity=self._styrene_selectivity(feed=feed, stream=stage_outlet_stream),
                    reheat_duty_mw=reheat_duty_mw,
                    inlet=stage_inlet_stream,
                    outlet=stage_outlet_stream,
                )
            )
            cumulative_length_m += stage_length_m

        outlet_stream = ReactorStream.from_vector_kmol_s(current_vector)
        outlet_state = ReactorState(
            stage_index=len(conditions.stage_lengths_m),
            axial_position_m=conditions.stage_lengths_m[-1],
            cumulative_length_m=cumulative_length_m,
            temperature_c=current_temperature_k - 273.15,
            pressure_kpa=conditions.pressure_kpa,
            stream=outlet_stream,
        )
        return ReactorResult(
            outlet=outlet_state,
            eb_conversion=self._eb_conversion(feed=feed, stream=outlet_stream),
            styrene_selectivity=self._styrene_selectivity(feed=feed, stream=outlet_stream),
            log=ReactorRunLog(
                cross_section_area_m2=cross_section_area_m2,
                inlet_volumetric_flow_m3_s=inlet_volumetric_flow_m3_s,
                stage_logs=tuple(stage_logs),
                profile=tuple(profile_points),
            ),
        )

    def _append_profile_point(
        self,
        profile_points: list[ReactorProfilePoint],
        stage_index: int,
        axial_position_m: float,
        cumulative_length_m: float,
        temperature_c: float,
        stream: ReactorStream,
        feed: ReactorFeed,
    ) -> None:
        profile_points.append(
            ReactorProfilePoint(
                stage_index=stage_index,
                axial_position_m=axial_position_m,
                cumulative_length_m=cumulative_length_m,
                temperature_c=temperature_c,
                eb_conversion=self._eb_conversion(feed=feed, stream=stream),
                styrene_selectivity=self._styrene_selectivity(feed=feed, stream=stream),
                stream=stream,
            )
        )

    def _cross_section_area(
        self,
        stream: ReactorStream,
        temperature_k: float,
        pressure_kpa: float,
        superficial_velocity_m_per_s: float,
    ) -> tuple[float, float]:
        volumetric_flow_m3_s = self._volumetric_flow_m3_s(
            total_flow_kmol_s=stream.total_flow_kmol_s(),
            temperature_k=temperature_k,
            pressure_kpa=pressure_kpa,
        )
        return volumetric_flow_m3_s / superficial_velocity_m_per_s, volumetric_flow_m3_s

    def _superficial_velocity(
        self,
        stream: ReactorStream,
        temperature_k: float,
        pressure_kpa: float,
        cross_section_area_m2: float,
    ) -> float:
        volumetric_flow_m3_s = self._volumetric_flow_m3_s(
            total_flow_kmol_s=stream.total_flow_kmol_s(),
            temperature_k=temperature_k,
            pressure_kpa=pressure_kpa,
        )
        return volumetric_flow_m3_s / cross_section_area_m2

    def _volumetric_flow_m3_s(self, total_flow_kmol_s: float, temperature_k: float, pressure_kpa: float) -> float:
        total_flow_mol_s = total_flow_kmol_s * 1000.0
        pressure_pa = pressure_kpa * self.universal.pa_per_kpa
        return total_flow_mol_s * self.universal.gas_constant_j_per_mol_k * temperature_k / pressure_pa

    def _reheat_duty_mw(
        self,
        stream: ReactorStream,
        from_temperature_k: float,
        to_temperature_k: float,
        properties: dict[str, SpeciesPhysicalProperty],
    ) -> float:
        enthalpy_change_kj_per_s = 0.0
        for name, flow_kmol_h in stream.to_component_flows_kmol_h().items():
            flow_kmol_s = flow_kmol_h / 3600.0
            if flow_kmol_s <= 0.0:
                continue
            delta_h_kj_per_kmol = species_enthalpy_kj_per_kmol(
                component_id=name,
                temperature_k=to_temperature_k,
                properties=properties,
                universal=self.universal,
            ) - species_enthalpy_kj_per_kmol(
                component_id=name,
                temperature_k=from_temperature_k,
                properties=properties,
                universal=self.universal,
            )
            enthalpy_change_kj_per_s += flow_kmol_s * delta_h_kj_per_kmol
        return enthalpy_change_kj_per_s / 1000.0

    def _eb_conversion(self, feed: ReactorFeed, stream: ReactorStream) -> float:
        converted = max(feed.eb - stream.eb, 0.0)
        return converted / max(feed.eb, 1e-12)

    def _styrene_selectivity(self, feed: ReactorFeed, stream: ReactorStream) -> float:
        converted = max(feed.eb - stream.eb, 0.0)
        produced = stream.styrene - feed.styrene
        return max(produced / max(converted, 1e-12), 0.0)
