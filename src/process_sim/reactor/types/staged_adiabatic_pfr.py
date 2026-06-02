"""多段断熱 PFR 反応器。"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math

from process_sim.constants.physical_properties import SPECIES_PHYSICAL_PROPERTIES, SpeciesPhysicalProperty
from process_sim.constants.reaction_networks import ReactionNetwork, STYRENE_SIX_REACTION_NETWORK
from process_sim.constants.universal import UNIVERSAL_CONSTANTS, UniversalConstants
from process_sim.reactor.core.models import (
    ReactorProfilePoint,
    ReactorResult,
    ReactorRunConditions,
    ReactorRunLog,
    ReactorStageLog,
    ReactorState,
)
from process_sim.reactor.core.pressure_drop import ErgunParameters
from process_sim.reactor.core.stream import ReactorFeed
from process_sim.reactor.types.pfr_adiabatic import PfrAdiabaticReactor, atom_balance_errors


@dataclass(frozen=True)
class StagedAdiabaticPfrModel:
    """多段断熱PFRモデル。"""

    network: ReactionNetwork = STYRENE_SIX_REACTION_NETWORK
    properties: dict[str, SpeciesPhysicalProperty] | None = None
    universal: UniversalConstants = UNIVERSAL_CONSTANTS

    def run(self, feed: ReactorFeed, conditions: ReactorRunConditions) -> ReactorResult:
        """入口空塔速度と段別 L/D から寸法を決めて計算する。"""
        self._validate_conditions(conditions)
        properties = self.properties or SPECIES_PHYSICAL_PROPERTIES
        ergun_parameters = ErgunParameters(
            pellet_diameter_m=conditions.pellet_diameter_m,
            bed_void_fraction=conditions.bed_void_fraction,
            catalyst_bulk_density_kg_m3=conditions.catalyst_bulk_density_kg_m3,
            ergun_a=conditions.ergun_a,
            ergun_b=conditions.ergun_b,
            gas_viscosity_pa_s=conditions.gas_viscosity_pa_s,
        )
        single_reactor = PfrAdiabaticReactor(
            network=self.network,
            properties=properties,
            universal=self.universal,
        )
        current_stream = feed
        current_pressure_pa = conditions.pressure_kpa * self.universal.pa_per_kpa
        stage_logs: list[ReactorStageLog] = []
        profile: list[ReactorProfilePoint] = []
        outlet_state: ReactorState | None = None
        cumulative_length_m = 0.0
        inlet_volumetric_flow_m3_s: float | None = None
        interstage_pressure_positive_values: list[bool] = []

        for stage_index, (stage_temperature_c, ld_ratio) in enumerate(
            zip(conditions.stage_inlet_temperatures_c, conditions.stage_ld_ratios, strict=True),
            start=1,
        ):
            stage_temperature_k = stage_temperature_c + 273.15
            stage_inlet_volumetric_flow_m3_s = self._volumetric_flow_m3_s(
                stream=current_stream,
                temperature_k=stage_temperature_k,
                pressure_pa=current_pressure_pa,
            )
            cross_section_area_m2 = (
                stage_inlet_volumetric_flow_m3_s / conditions.inlet_superficial_velocity_m_per_s
            )
            equivalent_diameter_m = math.sqrt(4.0 * cross_section_area_m2 / math.pi)
            stage_length_m = ld_ratio * equivalent_diameter_m
            stage_result = single_reactor.run(
                inlet=current_stream,
                feed=feed,
                stage_index=stage_index,
                inlet_temperature_k=stage_temperature_k,
                inlet_pressure_pa=current_pressure_pa,
                cross_section_area_m2=cross_section_area_m2,
                stage_length_m=stage_length_m,
                cumulative_length_offset_m=cumulative_length_m,
                ergun_parameters=ergun_parameters,
                catalyst_bulk_density_kg_m3=conditions.catalyst_bulk_density_kg_m3,
                segments=conditions.segments_per_stage,
                profile_points=conditions.profile_points_per_stage,
            )
            if inlet_volumetric_flow_m3_s is None:
                inlet_volumetric_flow_m3_s = stage_inlet_volumetric_flow_m3_s
            stage_velocities = tuple(
                point.superficial_velocity_m_per_s
                for point in stage_result.profile
                if point.superficial_velocity_m_per_s is not None
            )
            reheat_duty_mw = None
            reheat_pressure_drop_kpa = None
            current_stream = stage_result.outlet.stream
            current_pressure_pa = stage_result.outlet.pressure_kpa * self.universal.pa_per_kpa
            if stage_index < len(conditions.stage_inlet_temperatures_c):
                next_temperature_k = conditions.stage_inlet_temperatures_c[stage_index] + 273.15
                reheat_duty_mw = single_reactor.reheat_duty_mw(
                    stream=current_stream,
                    from_temperature_k=stage_result.outlet.temperature_c + 273.15,
                    to_temperature_k=next_temperature_k,
                    properties=properties,
                )
                reheat_pressure_drop_kpa = (
                    conditions.interstage_reheater_pressure_drop_pa / self.universal.pa_per_kpa
                )
                raw_reheat_outlet_pressure_pa = current_pressure_pa - conditions.interstage_reheater_pressure_drop_pa
                interstage_pressure_positive_values.append(raw_reheat_outlet_pressure_pa > 0.0)
                current_pressure_pa = max(raw_reheat_outlet_pressure_pa, 1.0)
            stage_logs.append(
                replace(
                    stage_result.stage_log,
                    reheat_duty_mw=reheat_duty_mw,
                    reheat_pressure_drop_kpa=reheat_pressure_drop_kpa,
                    cross_section_area_m2=cross_section_area_m2,
                    equivalent_diameter_m=equivalent_diameter_m,
                    ld_ratio=ld_ratio,
                    min_superficial_velocity_m_per_s=min(stage_velocities),
                    max_superficial_velocity_m_per_s=max(stage_velocities),
                )
            )
            profile.extend(stage_result.profile)
            outlet_state = stage_result.outlet
            cumulative_length_m += stage_length_m

        if outlet_state is None:
            raise ValueError("PFR staged model requires at least one stage")
        carbon_error, hydrogen_error = atom_balance_errors(feed=feed, outlet=outlet_state.stream)
        reactor_pressure_drop_kpa = sum(log.reactor_pressure_drop_kpa or 0.0 for log in stage_logs)
        reheat_pressure_drop_kpa = sum(log.reheat_pressure_drop_kpa or 0.0 for log in stage_logs)
        max_re = max((log.max_re_over_one_minus_void or 0.0 for log in stage_logs), default=0.0)
        length_ok = all(log.stage_length_m <= conditions.max_stage_length_m for log in stage_logs)
        velocity_range_ok = all(
            (log.min_superficial_velocity_m_per_s or 0.0) >= conditions.min_superficial_velocity_m_per_s
            and (log.max_superficial_velocity_m_per_s or float("inf"))
            <= conditions.max_superficial_velocity_m_per_s
            for log in stage_logs
        )
        result_log = ReactorRunLog(
            cross_section_area_m2=stage_logs[0].cross_section_area_m2 or 0.0,
            inlet_volumetric_flow_m3_s=inlet_volumetric_flow_m3_s or 0.0,
            stage_logs=tuple(stage_logs),
            profile=tuple(profile),
            reactor_pressure_drop_kpa=reactor_pressure_drop_kpa,
            reheat_pressure_drop_kpa=reheat_pressure_drop_kpa,
            total_pressure_drop_kpa=reactor_pressure_drop_kpa + reheat_pressure_drop_kpa,
            total_catalyst_volume_m3=sum(log.catalyst_volume_m3 or 0.0 for log in stage_logs),
            total_catalyst_mass_kg=sum(log.catalyst_mass_kg or 0.0 for log in stage_logs),
            max_re_over_one_minus_void=max_re,
            carbon_balance_error_fraction=carbon_error,
            hydrogen_balance_error_fraction=hydrogen_error,
            atom_balance_ok=carbon_error < 1e-8 and hydrogen_error < 1e-8,
            outlet_pressure_ok=outlet_state.pressure_kpa >= conditions.min_outlet_pressure_kpa_abs,
            pressure_positive_ok=all(log.pressure_positive_ok is not False for log in stage_logs)
            and all(interstage_pressure_positive_values),
            ergun_range_ok=max_re < 500.0,
            length_ok=length_ok,
            velocity_range_ok=velocity_range_ok,
        )
        return ReactorResult(
            outlet=outlet_state,
            eb_conversion=single_reactor.eb_conversion(feed=feed, stream=outlet_state.stream),
            styrene_selectivity=single_reactor.styrene_selectivity(feed=feed, stream=outlet_state.stream),
            log=result_log,
        )

    def _validate_conditions(self, conditions: ReactorRunConditions) -> None:
        """入力条件の構造を検証する。"""
        if len(conditions.stage_inlet_temperatures_c) != len(conditions.stage_ld_ratios):
            raise ValueError("stage_inlet_temperatures_c and stage_ld_ratios must have the same length")
        if len(conditions.stage_inlet_temperatures_c) not in (2, 3):
            raise ValueError("PFR staged model supports only 2 or 3 stages")
        positive_values = (
            conditions.pressure_kpa,
            conditions.inlet_superficial_velocity_m_per_s,
            conditions.min_outlet_pressure_kpa_abs,
            conditions.max_stage_length_m,
            conditions.min_superficial_velocity_m_per_s,
            conditions.max_superficial_velocity_m_per_s,
            float(conditions.segments_per_stage),
            float(conditions.profile_points_per_stage),
        )
        if any(value <= 0.0 for value in positive_values):
            raise ValueError("PFR conditions must be positive")
        if any(ld_ratio <= 0.0 for ld_ratio in conditions.stage_ld_ratios):
            raise ValueError("stage_ld_ratios must be positive")
        if conditions.min_superficial_velocity_m_per_s > conditions.max_superficial_velocity_m_per_s:
            raise ValueError("minimum superficial velocity must not exceed maximum superficial velocity")

    def _volumetric_flow_m3_s(
        self,
        stream: ReactorFeed,
        temperature_k: float,
        pressure_pa: float,
    ) -> float:
        """理想気体の体積流量を返す。"""
        total_flow_mol_s = stream.total_flow_kmol_s() * 1000.0
        return total_flow_mol_s * self.universal.gas_constant_j_per_mol_k * temperature_k / pressure_pa
