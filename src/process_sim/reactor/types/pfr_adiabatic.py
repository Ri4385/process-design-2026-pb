"""1基分の断熱 PFR 反応器。"""

from __future__ import annotations

from dataclasses import dataclass

from process_sim.constants.physical_properties import SPECIES_PHYSICAL_PROPERTIES, SpeciesPhysicalProperty
from process_sim.constants.reaction_networks import ReactionNetwork, STYRENE_SIX_REACTION_NETWORK
from process_sim.constants.universal import UNIVERSAL_CONSTANTS, UniversalConstants
from process_sim.reactor.core.balance import ReactorBalanceContext, pfr_adiabatic_derivatives
from process_sim.reactor.core import config
from process_sim.reactor.core.integrator import rk4_step
from process_sim.reactor.core.models import ReactorProfilePoint, ReactorStageLog, ReactorState
from process_sim.reactor.core.numba_reactor import can_use_numba_reactor_core, integrate_axial_numba
from process_sim.reactor.core.pressure_drop import ErgunParameters, reynolds_over_one_minus_void
from process_sim.reactor.core.stream import COMPONENT_ORDER, ReactorFeed, ReactorStream
from process_sim.reactor.core.thermodynamics import species_enthalpy_kj_per_kmol


@dataclass(frozen=True)
class PfrReactorStageResult:
    """1基分の PFR 計算結果。"""

    outlet: ReactorState
    stage_log: ReactorStageLog
    profile: tuple[ReactorProfilePoint, ...]


@dataclass(frozen=True)
class PfrAdiabaticReactor:
    """1基分の断熱 PFR 固定床反応器。"""

    network: ReactionNetwork = STYRENE_SIX_REACTION_NETWORK
    properties: dict[str, SpeciesPhysicalProperty] | None = None
    universal: UniversalConstants = UNIVERSAL_CONSTANTS

    def run(
        self,
        inlet: ReactorStream,
        feed: ReactorFeed,
        stage_index: int,
        inlet_temperature_k: float,
        inlet_pressure_pa: float,
        cross_section_area_m2: float,
        stage_length_m: float,
        cumulative_length_offset_m: float,
        ergun_parameters: ErgunParameters,
        catalyst_bulk_density_kg_m3: float,
        segments: int,
        profile_points: int,
    ) -> PfrReactorStageResult:
        """1基分の断熱 PFR を計算する。"""
        if cross_section_area_m2 <= 0.0:
            raise ValueError("cross_section_area_m2 must be positive")
        if stage_length_m <= 0.0:
            raise ValueError("stage_length_m must be positive")
        if inlet_pressure_pa <= 0.0:
            raise ValueError("inlet_pressure_pa must be positive")
        if catalyst_bulk_density_kg_m3 <= 0.0:
            raise ValueError("catalyst_bulk_density_kg_m3 must be positive")
        if segments <= 0:
            raise ValueError("segments must be positive")
        if profile_points <= 0:
            raise ValueError("profile_points must be positive")

        properties = self.properties or SPECIES_PHYSICAL_PROPERTIES
        current_vector = inlet.to_vector_kmol_s()
        current_temperature_k = inlet_temperature_k
        current_pressure_pa = inlet_pressure_pa
        dz = stage_length_m / float(segments)
        profile_stride = max(1, segments // profile_points)
        profile: list[ReactorProfilePoint] = []
        re_values: list[float] = []
        pressure_positive_ok = inlet_pressure_pa > 0.0

        inlet_velocity_m_per_s = self._superficial_velocity_m_per_s(
            stream=inlet,
            temperature_k=inlet_temperature_k,
            pressure_pa=inlet_pressure_pa,
            cross_section_area_m2=cross_section_area_m2,
        )
        self._append_profile_point(
            profile_points=profile,
            stage_index=stage_index,
            axial_position_m=0.0,
            cumulative_length_m=cumulative_length_offset_m,
            temperature_k=current_temperature_k,
            pressure_pa=current_pressure_pa,
            stream=inlet,
            feed=feed,
            cross_section_area_m2=cross_section_area_m2,
            ergun_parameters=ergun_parameters,
            properties=properties,
        )

        balance_context = ReactorBalanceContext(
            cross_section_area_m2=cross_section_area_m2,
            network=self.network,
            properties=properties,
            universal=self.universal,
            ergun_parameters=ergun_parameters,
        )
        if config.USE_NUMBA_REACTOR_CORE and can_use_numba_reactor_core(self.network, properties, self.universal):
            integration = integrate_axial_numba(
                initial_state=current_vector + [current_temperature_k, current_pressure_pa],
                stage_length_m=stage_length_m,
                cross_section_area_m2=cross_section_area_m2,
                ergun_parameters=ergun_parameters,
                segments=segments,
                profile_stride=profile_stride,
            )
            current_vector = integration.final_state[: len(COMPONENT_ORDER)]
            current_temperature_k = float(integration.final_state[len(COMPONENT_ORDER)])
            current_pressure_pa = float(integration.final_state[len(COMPONENT_ORDER) + 1])
            pressure_positive_ok = integration.pressure_positive_ok
            re_values.extend(
                (
                    integration.min_re_over_one_minus_void,
                    integration.max_re_over_one_minus_void,
                )
            )
            for axial_position_m, state in zip(
                integration.profile_positions_m,
                integration.profile_states,
                strict=True,
            ):
                current_stream = ReactorStream.from_vector_kmol_s(state[: len(COMPONENT_ORDER)])
                self._append_profile_point(
                    profile_points=profile,
                    stage_index=stage_index,
                    axial_position_m=float(axial_position_m),
                    cumulative_length_m=cumulative_length_offset_m + float(axial_position_m),
                    temperature_k=float(state[len(COMPONENT_ORDER)]),
                    pressure_pa=float(state[len(COMPONENT_ORDER) + 1]),
                    stream=current_stream,
                    feed=feed,
                    cross_section_area_m2=cross_section_area_m2,
                    ergun_parameters=ergun_parameters,
                    properties=properties,
                )
        else:
            for segment_index in range(segments):
                state_vector = current_vector + [current_temperature_k, current_pressure_pa]
                next_state = rk4_step(
                    state_vector=state_vector,
                    dz=dz,
                    derivative=lambda values: pfr_adiabatic_derivatives(values, balance_context),
                )
                current_vector = [max(value, 0.0) for value in next_state[: len(COMPONENT_ORDER)]]
                current_temperature_k = max(next_state[len(COMPONENT_ORDER)], 273.15)
                raw_pressure_pa = next_state[len(COMPONENT_ORDER) + 1]
                pressure_positive_ok = pressure_positive_ok and raw_pressure_pa > 0.0
                current_pressure_pa = max(raw_pressure_pa, 1.0)
                current_stream = ReactorStream.from_vector_kmol_s(current_vector)
                re_values.append(
                    self._re_over_one_minus_void(
                        stream=current_stream,
                        cross_section_area_m2=cross_section_area_m2,
                        ergun_parameters=ergun_parameters,
                        properties=properties,
                    )
                )
                if (segment_index + 1) % profile_stride == 0 or segment_index == segments - 1:
                    axial_position_m = (segment_index + 1) * dz
                    self._append_profile_point(
                        profile_points=profile,
                        stage_index=stage_index,
                        axial_position_m=axial_position_m,
                        cumulative_length_m=cumulative_length_offset_m + axial_position_m,
                        temperature_k=current_temperature_k,
                        pressure_pa=current_pressure_pa,
                        stream=current_stream,
                        feed=feed,
                        cross_section_area_m2=cross_section_area_m2,
                        ergun_parameters=ergun_parameters,
                        properties=properties,
                    )

        outlet_stream = ReactorStream.from_vector_kmol_s(current_vector)
        outlet_velocity_m_per_s = self._superficial_velocity_m_per_s(
            stream=outlet_stream,
            temperature_k=current_temperature_k,
            pressure_pa=current_pressure_pa,
            cross_section_area_m2=cross_section_area_m2,
        )
        carbon_error, hydrogen_error = atom_balance_errors(feed=inlet, outlet=outlet_stream)
        catalyst_volume_m3 = cross_section_area_m2 * stage_length_m
        outlet_state = ReactorState(
            stage_index=stage_index,
            axial_position_m=stage_length_m,
            cumulative_length_m=cumulative_length_offset_m + stage_length_m,
            temperature_c=current_temperature_k - 273.15,
            pressure_kpa=current_pressure_pa / self.universal.pa_per_kpa,
            stream=outlet_stream,
        )
        stage_log = ReactorStageLog(
            stage_index=stage_index,
            inlet_temperature_c=inlet_temperature_k - 273.15,
            outlet_temperature_c=current_temperature_k - 273.15,
            stage_length_m=stage_length_m,
            inlet_superficial_velocity_m_per_s=inlet_velocity_m_per_s,
            outlet_superficial_velocity_m_per_s=outlet_velocity_m_per_s,
            eb_conversion=self.eb_conversion(feed=feed, stream=outlet_stream),
            styrene_selectivity=self.styrene_selectivity(feed=feed, stream=outlet_stream),
            reheat_duty_mw=None,
            inlet=inlet,
            outlet=outlet_stream,
            inlet_pressure_kpa=inlet_pressure_pa / self.universal.pa_per_kpa,
            outlet_pressure_kpa=current_pressure_pa / self.universal.pa_per_kpa,
            reactor_pressure_drop_kpa=(inlet_pressure_pa - current_pressure_pa) / self.universal.pa_per_kpa,
            catalyst_volume_m3=catalyst_volume_m3,
            catalyst_mass_kg=catalyst_volume_m3 * catalyst_bulk_density_kg_m3,
            min_re_over_one_minus_void=min(re_values) if re_values else None,
            max_re_over_one_minus_void=max(re_values) if re_values else None,
            carbon_balance_error_fraction=carbon_error,
            hydrogen_balance_error_fraction=hydrogen_error,
            pressure_positive_ok=pressure_positive_ok,
        )
        return PfrReactorStageResult(
            outlet=outlet_state,
            stage_log=stage_log,
            profile=tuple(profile),
        )

    def _append_profile_point(
        self,
        profile_points: list[ReactorProfilePoint],
        stage_index: int,
        axial_position_m: float,
        cumulative_length_m: float,
        temperature_k: float,
        pressure_pa: float,
        stream: ReactorStream,
        feed: ReactorFeed,
        cross_section_area_m2: float,
        ergun_parameters: ErgunParameters,
        properties: dict[str, SpeciesPhysicalProperty],
    ) -> None:
        profile_points.append(
            ReactorProfilePoint(
                stage_index=stage_index,
                axial_position_m=axial_position_m,
                cumulative_length_m=cumulative_length_m,
                temperature_c=temperature_k - 273.15,
                eb_conversion=self.eb_conversion(feed=feed, stream=stream),
                styrene_selectivity=self.styrene_selectivity(feed=feed, stream=stream),
                stream=stream,
                pressure_kpa=pressure_pa / self.universal.pa_per_kpa,
                superficial_velocity_m_per_s=self._superficial_velocity_m_per_s(
                    stream=stream,
                    temperature_k=temperature_k,
                    pressure_pa=pressure_pa,
                    cross_section_area_m2=cross_section_area_m2,
                ),
                re_over_one_minus_void=self._re_over_one_minus_void(
                    stream=stream,
                    cross_section_area_m2=cross_section_area_m2,
                    ergun_parameters=ergun_parameters,
                    properties=properties,
                ),
            )
        )

    def _superficial_velocity_m_per_s(
        self,
        stream: ReactorStream,
        temperature_k: float,
        pressure_pa: float,
        cross_section_area_m2: float,
    ) -> float:
        total_flow_mol_s = stream.total_flow_kmol_s() * 1000.0
        volumetric_flow_m3_s = (
            total_flow_mol_s * self.universal.gas_constant_j_per_mol_k * temperature_k / max(pressure_pa, 1.0)
        )
        return volumetric_flow_m3_s / cross_section_area_m2

    def _re_over_one_minus_void(
        self,
        stream: ReactorStream,
        cross_section_area_m2: float,
        ergun_parameters: ErgunParameters,
        properties: dict[str, SpeciesPhysicalProperty],
    ) -> float:
        return reynolds_over_one_minus_void(
            superficial_mass_velocity_kg_m2_s=mass_flow_kg_s(stream=stream, properties=properties)
            / cross_section_area_m2,
            parameters=ergun_parameters,
        )

    def reheat_duty_mw(
        self,
        stream: ReactorStream,
        from_temperature_k: float,
        to_temperature_k: float,
        properties: dict[str, SpeciesPhysicalProperty],
    ) -> float:
        """再加熱に必要な熱量を MW で返す。"""
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

    def eb_conversion(self, feed: ReactorFeed, stream: ReactorStream) -> float:
        """feed 基準の EB 転化率を返す。"""
        converted = max(feed.eb - stream.eb, 0.0)
        return converted / max(feed.eb, 1e-12)

    def styrene_selectivity(self, feed: ReactorFeed, stream: ReactorStream) -> float:
        """feed 基準の SM 選択率を返す。"""
        converted = max(feed.eb - stream.eb, 0.0)
        produced = stream.styrene - feed.styrene
        return max(produced / max(converted, 1e-12), 0.0)


def mass_flow_kg_s(stream: ReactorStream, properties: dict[str, SpeciesPhysicalProperty]) -> float:
    """成分流量から質量流量を kg/s で返す。"""
    return sum(
        flow_kmol_h / 3600.0 * properties[name].molecular_weight
        for name, flow_kmol_h in stream.to_component_flows_kmol_h().items()
    )


ATOM_COUNTS: dict[str, tuple[int, int]] = {
    "eb": (8, 10),
    "steam": (0, 2),
    "styrene": (8, 8),
    "hydrogen": (0, 2),
    "benzene": (6, 6),
    "toluene": (7, 8),
    "co2": (1, 0),
    "ethylene": (2, 4),
    "methane": (1, 4),
    "co": (1, 0),
}


def atom_balance_errors(feed: ReactorStream, outlet: ReactorStream) -> tuple[float, float]:
    """C と H の入口出口相対収支誤差を返す。"""
    inlet_c, inlet_h = atom_flows(feed)
    outlet_c, outlet_h = atom_flows(outlet)
    return (
        abs(outlet_c - inlet_c) / max(abs(inlet_c), 1e-12),
        abs(outlet_h - inlet_h) / max(abs(inlet_h), 1e-12),
    )


def atom_flows(stream: ReactorStream) -> tuple[float, float]:
    """C と H の原子流量を kmol-atom/h で返す。"""
    carbon = 0.0
    hydrogen = 0.0
    for name, flow_kmol_h in stream.to_component_flows_kmol_h().items():
        c_count, h_count = ATOM_COUNTS[name]
        carbon += flow_kmol_h * c_count
        hydrogen += flow_kmol_h * h_count
    return carbon, hydrogen
