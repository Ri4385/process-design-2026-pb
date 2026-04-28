"""3段断熱PFR反応器列モデル。"""

from __future__ import annotations

from dataclasses import dataclass

from process_sim.constants import ReactorConfigDefaults
from process_sim.reactor.kinetics import arrhenius_rate_constants
from process_sim.reactor.models import (
    INTERNAL_COMPONENT_ORDER,
    ReactorFeed,
    ReactorProfilePoint,
    ReactorResult,
    ReactorRunConditions,
    ReactorRunLog,
    ReactorStageLog,
    ReactorState,
    ReactorStream,
)


REACTION_STOICH = (
    (1.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0),   # EB -> SM + H2
    (-1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0),  # SM + H2 -> EB
    (0.0, -1.0, 0.0, -4.0, 1.0, 2.0, 0.0, 0.0, 0.0, 6.0),  # EB + 4H2O -> BZ + 2CO2 + 6H2
    (0.0, -1.0, 1.0, -2.0, 0.0, 1.0, 0.0, 0.0, 0.0, 3.0),  # EB + 2H2O -> TL + CO2 + 3H2
)


@dataclass
class StyreneReactorModel:
    """EB脱水素の3段断熱PFRモデル。"""

    config: ReactorConfigDefaults

    def run(self, feed: ReactorFeed, conditions: ReactorRunConditions) -> ReactorResult:
        """3段断熱反応器列を計算する。"""
        if conditions.segments_per_stage <= 0:
            raise ValueError("segments_per_stage must be positive")
        if conditions.profile_points_per_stage <= 0:
            raise ValueError("profile_points_per_stage must be positive")
        if len(conditions.stage_inlet_temperatures_c) != 3:
            raise ValueError("stage_inlet_temperatures_c must have three entries")
        if len(conditions.stage_lengths_m) != 3:
            raise ValueError("stage_lengths_m must have three entries")

        feed_vector = feed.to_internal_vector_kmol_s()
        cross_section_area_m2, inlet_volumetric_flow_m3_s = self._cross_section_area(
            stream=feed,
            temperature_k=conditions.stage_inlet_temperatures_c[0] + 273.15,
            pressure_kpa=conditions.pressure_kpa,
            superficial_velocity_m_per_s=conditions.inlet_superficial_velocity_m_per_s,
        )

        current_vector = feed_vector[:]
        profile_points: list[ReactorProfilePoint] = []
        stage_logs: list[ReactorStageLog] = []
        cumulative_length_m = 0.0

        for stage_index, (stage_inlet_temperature_c, stage_length_m) in enumerate(
            zip(conditions.stage_inlet_temperatures_c, conditions.stage_lengths_m, strict=True),
            start=1,
        ):
            stage_inlet_stream = ReactorStream.from_internal_vector_kmol_s(current_vector)
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

            for segment_index in range(conditions.segments_per_stage):
                state_vector = current_vector + [current_temperature_k]
                next_state = self._rk4_step(
                    state_vector=state_vector,
                    dz=dz,
                    pressure_kpa=conditions.pressure_kpa,
                    cross_section_area_m2=cross_section_area_m2,
                )
                current_vector = [max(value, 0.0) for value in next_state[:10]]
                current_temperature_k = max(next_state[10], 273.15)

                if (segment_index + 1) % profile_stride == 0 or segment_index == conditions.segments_per_stage - 1:
                    stage_outlet_stream = ReactorStream.from_internal_vector_kmol_s(current_vector)
                    self._append_profile_point(
                        profile_points=profile_points,
                        stage_index=stage_index,
                        axial_position_m=(segment_index + 1) * dz,
                        cumulative_length_m=cumulative_length_m + (segment_index + 1) * dz,
                        temperature_c=current_temperature_k - 273.15,
                        stream=stage_outlet_stream,
                        feed=feed,
                    )
            stage_outlet_stream = ReactorStream.from_internal_vector_kmol_s(current_vector)
            outlet_temperature_c = current_temperature_k - 273.15
            outlet_velocity_m_per_s = self._superficial_velocity(
                stream=stage_outlet_stream,
                temperature_k=current_temperature_k,
                pressure_kpa=conditions.pressure_kpa,
                cross_section_area_m2=cross_section_area_m2,
            )
            eb_conversion = self._eb_conversion(feed=feed, stream=stage_outlet_stream)
            styrene_selectivity = self._styrene_selectivity(feed=feed, stream=stage_outlet_stream)
            reheat_duty_mw = None
            if stage_index < len(conditions.stage_inlet_temperatures_c):
                next_inlet_temperature_k = conditions.stage_inlet_temperatures_c[stage_index] + 273.15
                reheat_duty_mw = self._reheat_duty_mw(
                    stream=stage_outlet_stream,
                    from_temperature_k=current_temperature_k,
                    to_temperature_k=next_inlet_temperature_k,
                )

            stage_logs.append(
                ReactorStageLog(
                    stage_index=stage_index,
                    inlet_temperature_c=stage_inlet_temperature_c,
                    outlet_temperature_c=outlet_temperature_c,
                    stage_length_m=stage_length_m,
                    inlet_superficial_velocity_m_per_s=inlet_velocity_m_per_s,
                    outlet_superficial_velocity_m_per_s=outlet_velocity_m_per_s,
                    eb_conversion=eb_conversion,
                    styrene_selectivity=styrene_selectivity,
                    reheat_duty_mw=reheat_duty_mw,
                    inlet=stage_inlet_stream,
                    outlet=stage_outlet_stream,
                )
            )
            cumulative_length_m += stage_length_m

        outlet_stream = ReactorStream.from_internal_vector_kmol_s(current_vector)
        outlet_state = ReactorState(
            stage_index=3,
            axial_position_m=conditions.stage_lengths_m[-1],
            cumulative_length_m=cumulative_length_m,
            temperature_c=current_temperature_k - 273.15,
            pressure_kpa=conditions.pressure_kpa,
            stream=outlet_stream,
        )
        eb_conversion = self._eb_conversion(feed=feed, stream=outlet_stream)
        styrene_selectivity = self._styrene_selectivity(feed=feed, stream=outlet_stream)

        return ReactorResult(
            outlet=outlet_state,
            eb_conversion=eb_conversion,
            styrene_selectivity=styrene_selectivity,
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
        cross_section_area_m2 = volumetric_flow_m3_s / superficial_velocity_m_per_s
        return cross_section_area_m2, volumetric_flow_m3_s

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
        pressure_pa = pressure_kpa * self.config.universal.pa_per_kpa
        return total_flow_mol_s * self.config.universal.gas_constant_j_per_mol_k * temperature_k / pressure_pa

    def _eb_conversion(self, feed: ReactorFeed, stream: ReactorStream) -> float:
        converted = max(feed.eb - stream.eb, 0.0)
        return converted / max(feed.eb, 1e-12)

    def _styrene_selectivity(self, feed: ReactorFeed, stream: ReactorStream) -> float:
        converted = max(feed.eb - stream.eb, 0.0)
        produced = stream.styrene - feed.styrene
        return max(produced / max(converted, 1e-12), 0.0)

    def _reheat_duty_mw(self, stream: ReactorStream, from_temperature_k: float, to_temperature_k: float) -> float:
        enthalpy_change_kj_per_s = 0.0
        stream_dict = self._stream_dict(stream)
        for name in INTERNAL_COMPONENT_ORDER:
            flow_kmol_s = stream_dict[name] / 3600.0
            if flow_kmol_s <= 0.0:
                continue
            delta_h_kj_per_kmol = self._species_enthalpy_kj_per_kmol(name, to_temperature_k) - self._species_enthalpy_kj_per_kmol(
                name,
                from_temperature_k,
            )
            enthalpy_change_kj_per_s += flow_kmol_s * delta_h_kj_per_kmol
        return enthalpy_change_kj_per_s / 1000.0

    def _rk4_step(
        self,
        state_vector: list[float],
        dz: float,
        pressure_kpa: float,
        cross_section_area_m2: float,
    ) -> list[float]:
        k1 = self._derivatives(state_vector, pressure_kpa, cross_section_area_m2)
        k2 = self._derivatives(self._vector_add(state_vector, self._vector_scale(k1, dz / 2.0)), pressure_kpa, cross_section_area_m2)
        k3 = self._derivatives(self._vector_add(state_vector, self._vector_scale(k2, dz / 2.0)), pressure_kpa, cross_section_area_m2)
        k4 = self._derivatives(self._vector_add(state_vector, self._vector_scale(k3, dz)), pressure_kpa, cross_section_area_m2)

        next_state = state_vector[:]
        for index in range(len(state_vector)):
            next_state[index] = state_vector[index] + dz * (k1[index] + 2.0 * k2[index] + 2.0 * k3[index] + k4[index]) / 6.0
        return next_state

    def _derivatives(self, state_vector: list[float], pressure_kpa: float, cross_section_area_m2: float) -> list[float]:
        flows_kmol_s = [max(value, 0.0) for value in state_vector[:10]]
        temperature_k = max(state_vector[10], 273.15)
        total_flow_kmol_s = max(sum(flows_kmol_s), 1e-18)
        pressure_atm = pressure_kpa / 101.325
        partial_pressures_atm = [pressure_atm * flow / total_flow_kmol_s for flow in flows_kmol_s]
        partial_pressure = dict(zip(INTERNAL_COMPONENT_ORDER, partial_pressures_atm, strict=True))

        rate_constants = arrhenius_rate_constants(
            temperature_k=temperature_k,
            kinetics=self.config.kinetics,
            universal=self.config.universal,
        )
        reaction_rates = (
            rate_constants.k11 * partial_pressure["eb"],
            rate_constants.k12 * partial_pressure["styrene"] * partial_pressure["hydrogen"],
            rate_constants.k2 * partial_pressure["eb"],
            rate_constants.k3 * partial_pressure["eb"],
        )

        component_derivatives = [0.0 for _ in range(10)]
        for component_index, stoich_vector in enumerate(zip(*REACTION_STOICH, strict=True)):
            component_derivatives[component_index] = cross_section_area_m2 * sum(
                stoich * rate for stoich, rate in zip(stoich_vector, reaction_rates, strict=True)
            )

        reaction_enthalpies = (117_600.0, -117_600.0, 232_800.0, 110_100.0)
        sigma_r_delta_h_kj_per_m3_s = sum(
            rate * delta_h for rate, delta_h in zip(reaction_rates, reaction_enthalpies, strict=True)
        )
        sigma_f_cp_kj_per_s_k = sum(
            flow * self._species_heat_capacity_kj_per_kmol_k(name, temperature_k)
            for name, flow in zip(INTERNAL_COMPONENT_ORDER, flows_kmol_s, strict=True)
        )
        temperature_derivative = -cross_section_area_m2 * sigma_r_delta_h_kj_per_m3_s / max(sigma_f_cp_kj_per_s_k, 1e-18)

        return component_derivatives + [temperature_derivative]

    def _species_heat_capacity_kj_per_kmol_k(self, name: str, temperature_k: float) -> float:
        thermo = self.config.thermo.by_name(self._thermo_name(name))
        return (
            thermo.heat_capacity_a
            + thermo.heat_capacity_b * temperature_k
            + thermo.heat_capacity_c * temperature_k * temperature_k
            + thermo.heat_capacity_d * temperature_k * temperature_k * temperature_k
        )

    def _species_enthalpy_kj_per_kmol(self, name: str, temperature_k: float) -> float:
        thermo = self.config.thermo.by_name(self._thermo_name(name))
        reference_temperature_k = self.config.universal.reference_temperature_k
        return thermo.heat_of_formation_kj_per_kmol + (
            thermo.heat_capacity_a * (temperature_k - reference_temperature_k)
            + thermo.heat_capacity_b * (temperature_k * temperature_k - reference_temperature_k * reference_temperature_k) / 2.0
            + thermo.heat_capacity_c
            * (temperature_k * temperature_k * temperature_k - reference_temperature_k * reference_temperature_k * reference_temperature_k)
            / 3.0
            + thermo.heat_capacity_d
            * (
                temperature_k * temperature_k * temperature_k * temperature_k
                - reference_temperature_k * reference_temperature_k * reference_temperature_k * reference_temperature_k
            )
            / 4.0
        )

    def _thermo_name(self, component_name: str) -> str:
        if component_name == "benzene":
            return "benzene"
        if component_name == "steam":
            return "steam"
        if component_name == "styrene":
            return "styrene"
        if component_name == "toluene":
            return "toluene"
        if component_name == "ethylene":
            return "ethylene"
        if component_name == "methane":
            return "methane"
        if component_name == "hydrogen":
            return "hydrogen"
        return component_name

    def _stream_dict(self, stream: ReactorStream) -> dict[str, float]:
        return {
            "eb": stream.eb,
            "steam": stream.steam,
            "styrene": stream.styrene,
            "hydrogen": stream.hydrogen,
            "benzene": stream.benzene,
            "toluene": stream.toluene,
            "co2": stream.co2,
            "ethylene": stream.ethylene,
            "methane": stream.methane,
            "co": stream.co,
        }

    def _vector_add(self, left: list[float], right: list[float]) -> list[float]:
        return [left_value + right_value for left_value, right_value in zip(left, right, strict=True)]

    def _vector_scale(self, values: list[float], scale: float) -> list[float]:
        return [value * scale for value in values]
