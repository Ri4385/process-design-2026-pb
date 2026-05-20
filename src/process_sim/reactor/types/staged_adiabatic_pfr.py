"""多段断熱 PFR 反応器。"""

from __future__ import annotations

from dataclasses import dataclass, replace

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
        """多段断熱PFRを計算する。"""
        self._validate_conditions(conditions)
        properties = self.properties or SPECIES_PHYSICAL_PROPERTIES
        total_length_m = sum(conditions.stage_lengths_m)
        cross_section_area_m2 = conditions.total_catalyst_volume_m3 / total_length_m
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

        for stage_index, (stage_temperature_c, stage_length_m) in enumerate(
            zip(conditions.stage_inlet_temperatures_c, conditions.stage_lengths_m, strict=True),
            start=1,
        ):
            stage_result = single_reactor.run(
                inlet=current_stream,
                feed=feed,
                stage_index=stage_index,
                inlet_temperature_k=stage_temperature_c + 273.15,
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
                inlet_volumetric_flow_m3_s = (
                    stage_result.stage_log.inlet_superficial_velocity_m_per_s * cross_section_area_m2
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
        max_re = max(
            (log.max_re_over_one_minus_void or 0.0 for log in stage_logs),
            default=0.0,
        )
        result_log = ReactorRunLog(
            cross_section_area_m2=cross_section_area_m2,
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
            outlet_pressure_ok=outlet_state.pressure_kpa >= 30.0,
            pressure_positive_ok=all(log.pressure_positive_ok is not False for log in stage_logs)
            and all(interstage_pressure_positive_values),
            ergun_range_ok=max_re < 500.0,
        )
        return ReactorResult(
            outlet=outlet_state,
            eb_conversion=single_reactor.eb_conversion(feed=feed, stream=outlet_state.stream),
            styrene_selectivity=single_reactor.styrene_selectivity(feed=feed, stream=outlet_state.stream),
            log=result_log,
        )

    def _validate_conditions(self, conditions: ReactorRunConditions) -> None:
        if conditions.segments_per_stage <= 0:
            raise ValueError("segments_per_stage must be positive")
        if conditions.profile_points_per_stage <= 0:
            raise ValueError("profile_points_per_stage must be positive")
        if len(conditions.stage_inlet_temperatures_c) != len(conditions.stage_lengths_m):
            raise ValueError("stage_inlet_temperatures_c and stage_lengths_m must have the same length")
        if not conditions.stage_lengths_m:
            raise ValueError("stage_lengths_m must not be empty")
        if sum(conditions.stage_lengths_m) <= 0.0:
            raise ValueError("total PFR length must be positive")
        if conditions.total_catalyst_volume_m3 <= 0.0:
            raise ValueError("total_catalyst_volume_m3 must be positive")
        if conditions.pressure_kpa <= 0.0:
            raise ValueError("pressure_kpa must be positive")
