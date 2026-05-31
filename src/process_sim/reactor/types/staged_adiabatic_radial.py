"""多段断熱ラジアルフロー反応器。"""

from __future__ import annotations

from dataclasses import replace
import math

from process_sim.constants.physical_properties import SPECIES_PHYSICAL_PROPERTIES, SpeciesPhysicalProperty
from process_sim.constants.reaction_networks import ReactionNetwork, STYRENE_SIX_REACTION_NETWORK
from process_sim.constants.universal import UNIVERSAL_CONSTANTS, UniversalConstants
from process_sim.reactor.core.models import (
    RadialReactorRunConditions,
    ReactorProfilePoint,
    ReactorResult,
    ReactorRunLog,
    ReactorStageLog,
    ReactorState,
)
from process_sim.reactor.core.pressure_drop import ErgunParameters
from process_sim.reactor.core.radial_geometry import RadialBedGeometry
from process_sim.reactor.core.stream import ReactorFeed
from process_sim.reactor.types.radial_adiabatic import RadialAdiabaticReactor, atom_balance_errors


class StagedAdiabaticRadialFlowModel:
    """多段断熱ラジアルフロー反応器モデル。"""

    def __init__(
        self,
        network: ReactionNetwork = STYRENE_SIX_REACTION_NETWORK,
        properties: dict[str, SpeciesPhysicalProperty] | None = None,
        universal: UniversalConstants = UNIVERSAL_CONSTANTS,
    ) -> None:
        self.network = network
        self.properties = properties
        self.universal = universal

    def run(self, feed: ReactorFeed, conditions: RadialReactorRunConditions) -> ReactorResult:
        """中心流路半径と入口空塔速度から各段高さを決めて計算する。"""
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
        single_reactor = RadialAdiabaticReactor(
            network=self.network,
            properties=properties,
            universal=self.universal,
        )
        current_stream = feed
        current_pressure_pa = conditions.inlet_pressure_pa
        stage_logs: list[ReactorStageLog] = []
        profile: list[ReactorProfilePoint] = []
        outlet_state: ReactorState | None = None
        interstage_pressure_positive_values: list[bool] = []

        for stage_index, (stage_temperature_k, bed_thickness_m) in enumerate(
            zip(conditions.stage_inlet_temperatures_k, conditions.bed_thicknesses_m, strict=True),
            start=1,
        ):
            bed_height_m = self._bed_height_m(
                stream=current_stream,
                temperature_k=stage_temperature_k,
                pressure_pa=current_pressure_pa,
                inner_radius_m=conditions.center_channel_radius_m,
                inlet_velocity_m_per_s=conditions.inlet_superficial_velocity_m_per_s,
            )
            geometry = RadialBedGeometry(
                inner_radius_m=conditions.center_channel_radius_m,
                bed_height_m=bed_height_m,
                bed_thickness_m=bed_thickness_m,
                catalyst_bulk_density_kg_m3=conditions.catalyst_bulk_density_kg_m3,
            )
            stage_result = single_reactor.run(
                inlet=current_stream,
                feed=feed,
                stage_index=stage_index,
                inlet_temperature_k=stage_temperature_k,
                inlet_pressure_pa=current_pressure_pa,
                geometry=geometry,
                ergun_parameters=ergun_parameters,
                segments=conditions.segments_per_stage,
                profile_points=conditions.profile_points_per_stage,
            )
            reheat_duty_mw = None
            reheat_pressure_drop_kpa = None
            current_stream = stage_result.outlet.stream
            current_pressure_pa = stage_result.outlet.pressure_kpa * self.universal.pa_per_kpa
            if stage_index < len(conditions.stage_inlet_temperatures_k):
                next_temperature_k = conditions.stage_inlet_temperatures_k[stage_index]
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

        if outlet_state is None:
            raise ValueError("radial staged model requires at least one stage")
        carbon_error, hydrogen_error = atom_balance_errors(feed=feed, outlet=outlet_state.stream)
        reactor_pressure_drop_kpa = sum(log.reactor_pressure_drop_kpa or 0.0 for log in stage_logs)
        reheat_pressure_drop_kpa = sum(log.reheat_pressure_drop_kpa or 0.0 for log in stage_logs)
        max_re = max((log.max_re_over_one_minus_void or 0.0 for log in stage_logs), default=0.0)
        radial_bed_outlet_velocity_ok = all(
            log.outlet_superficial_velocity_m_per_s >= conditions.min_bed_outlet_velocity_m_per_s
            for log in stage_logs
        )
        first_stage = stage_logs[0]
        result_log = ReactorRunLog(
            cross_section_area_m2=2.0
            * math.pi
            * conditions.center_channel_radius_m
            * (first_stage.bed_height_m or 0.0),
            inlet_volumetric_flow_m3_s=self._volumetric_flow_m3_s(
                stream=feed,
                temperature_k=conditions.stage_inlet_temperatures_k[0],
                pressure_pa=conditions.inlet_pressure_pa,
            ),
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
            radial_bed_outlet_velocity_ok=radial_bed_outlet_velocity_ok,
        )
        return ReactorResult(
            outlet=outlet_state,
            eb_conversion=single_reactor.eb_conversion(feed=feed, stream=outlet_state.stream),
            styrene_selectivity=single_reactor.styrene_selectivity(feed=feed, stream=outlet_state.stream),
            log=result_log,
        )

    def _validate_conditions(self, conditions: RadialReactorRunConditions) -> None:
        """入力条件の構造を検証する。"""
        if len(conditions.stage_inlet_temperatures_k) != len(conditions.bed_thicknesses_m):
            raise ValueError("stage_inlet_temperatures_k and bed_thicknesses_m must have the same length")
        if len(conditions.stage_inlet_temperatures_k) not in (2, 3):
            raise ValueError("radial staged model supports only 2 or 3 stages")
        positive_values = (
            conditions.inlet_pressure_pa,
            conditions.inlet_superficial_velocity_m_per_s,
            conditions.center_channel_radius_m,
            conditions.min_outlet_pressure_kpa_abs,
            conditions.min_bed_outlet_velocity_m_per_s,
            float(conditions.segments_per_stage),
            float(conditions.profile_points_per_stage),
        )
        if any(value <= 0.0 for value in positive_values):
            raise ValueError("radial conditions must be positive")
        if any(bed_thickness_m <= 0.0 for bed_thickness_m in conditions.bed_thicknesses_m):
            raise ValueError("bed_thicknesses_m must be positive")

    def _bed_height_m(
        self,
        stream: ReactorFeed,
        temperature_k: float,
        pressure_pa: float,
        inner_radius_m: float,
        inlet_velocity_m_per_s: float,
    ) -> float:
        """中心流路半径と入口空塔速度から触媒床高さを返す。"""
        inlet_area_m2 = (
            self._volumetric_flow_m3_s(
                stream=stream,
                temperature_k=temperature_k,
                pressure_pa=pressure_pa,
            )
            / inlet_velocity_m_per_s
        )
        return inlet_area_m2 / (2.0 * math.pi * inner_radius_m)

    def _volumetric_flow_m3_s(
        self,
        stream: ReactorFeed,
        temperature_k: float,
        pressure_pa: float,
    ) -> float:
        """理想気体の体積流量を返す。"""
        total_flow_mol_s = stream.total_flow_kmol_s() * 1000.0
        return total_flow_mol_s * self.universal.gas_constant_j_per_mol_k * temperature_k / pressure_pa
