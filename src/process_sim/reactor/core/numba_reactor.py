# pyright: reportMissingImports=false, reportMissingTypeStubs=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUntypedFunctionDecorator=false
"""既定スチレン反応器用の Numba 高速積分。"""

from __future__ import annotations

from dataclasses import dataclass
import math

from numba import njit  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]
import numpy as np
from numpy.typing import NDArray

from process_sim.constants.physical_properties import SPECIES_PHYSICAL_PROPERTIES, SpeciesPhysicalProperty
from process_sim.constants.reaction_networks import ReactionNetwork, STYRENE_SIX_REACTION_NETWORK
from process_sim.constants.universal import UNIVERSAL_CONSTANTS, UniversalConstants
from process_sim.reactor.core.pressure_drop import ErgunParameters
from process_sim.reactor.core.stream import COMPONENT_ORDER


@dataclass(frozen=True)
class FastIntegrationResult:
    """高速積分で得た終状態と profile 記録点。"""

    final_state: list[float]
    profile_positions_m: list[float]
    profile_states: list[list[float]]
    min_re_over_one_minus_void: float
    max_re_over_one_minus_void: float
    pressure_positive_ok: bool


MOLECULAR_WEIGHTS = np.asarray(
    [SPECIES_PHYSICAL_PROPERTIES[name].molecular_weight for name in COMPONENT_ORDER],
    dtype=np.float64,
)
HEAT_OF_FORMATION = np.asarray(
    [SPECIES_PHYSICAL_PROPERTIES[name].heat_of_formation_kj_per_kmol for name in COMPONENT_ORDER],
    dtype=np.float64,
)
HEAT_CAPACITY_COEFFICIENTS = np.asarray(
    [
        (
            SPECIES_PHYSICAL_PROPERTIES[name].heat_capacity.a,
            SPECIES_PHYSICAL_PROPERTIES[name].heat_capacity.b,
            SPECIES_PHYSICAL_PROPERTIES[name].heat_capacity.c,
            SPECIES_PHYSICAL_PROPERTIES[name].heat_capacity.d,
        )
        for name in COMPONENT_ORDER
    ],
    dtype=np.float64,
)
STOICHIOMETRY = np.asarray(
    [
        (-1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        (-1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
        (-1.0, 0.0, 0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0),
        (0.0, -2.0, 0.0, 4.0, 0.0, 0.0, 0.0, -1.0, 0.0, 2.0),
        (0.0, -1.0, 0.0, 3.0, 0.0, 0.0, 0.0, 0.0, -1.0, 1.0),
        (0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, -1.0),
    ],
    dtype=np.float64,
)

AXIAL_MODE = 0
RADIAL_MODE = 1


def can_use_numba_reactor_core(
    network: ReactionNetwork,
    properties: dict[str, SpeciesPhysicalProperty],
    universal: UniversalConstants,
) -> bool:
    """高速経路で扱える既定条件か返す。"""
    return (
        network is STYRENE_SIX_REACTION_NETWORK
        and properties is SPECIES_PHYSICAL_PROPERTIES
        and universal is UNIVERSAL_CONSTANTS
    )


def integrate_axial_numba(
    initial_state: list[float],
    stage_length_m: float,
    cross_section_area_m2: float,
    ergun_parameters: ErgunParameters,
    segments: int,
    profile_stride: int,
) -> FastIntegrationResult:
    """axial PFR を高速積分する。"""
    return _as_result(
        _integrate_numba(
            np.asarray(initial_state, dtype=np.float64),
            stage_length_m,
            segments,
            profile_stride,
            AXIAL_MODE,
            cross_section_area_m2,
            0.0,
            0.0,
            ergun_parameters.pellet_diameter_m,
            ergun_parameters.bed_void_fraction,
            ergun_parameters.ergun_a,
            ergun_parameters.ergun_b,
            ergun_parameters.gas_viscosity_pa_s,
        )
    )


def integrate_radial_numba(
    initial_state: list[float],
    bed_thickness_m: float,
    inner_radius_m: float,
    bed_height_m: float,
    ergun_parameters: ErgunParameters,
    segments: int,
    profile_stride: int,
) -> FastIntegrationResult:
    """radial 反応器を高速積分する。"""
    return _as_result(
        _integrate_numba(
            np.asarray(initial_state, dtype=np.float64),
            bed_thickness_m,
            segments,
            profile_stride,
            RADIAL_MODE,
            0.0,
            inner_radius_m,
            bed_height_m,
            ergun_parameters.pellet_diameter_m,
            ergun_parameters.bed_void_fraction,
            ergun_parameters.ergun_a,
            ergun_parameters.ergun_b,
            ergun_parameters.gas_viscosity_pa_s,
        )
    )


def _as_result(
    values: tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], float, float, bool],
) -> FastIntegrationResult:
    return FastIntegrationResult(
        final_state=values[0].tolist(),
        profile_positions_m=values[1].tolist(),
        profile_states=values[2].tolist(),
        min_re_over_one_minus_void=values[3],
        max_re_over_one_minus_void=values[4],
        pressure_positive_ok=values[5],
    )


@njit(cache=True)  # pyright: ignore[reportUntypedFunctionDecorator]
def _integrate_numba(
    initial_state: NDArray[np.float64],
    distance_m: float,
    segments: int,
    profile_stride: int,
    mode: int,
    axial_area_m2: float,
    inner_radius_m: float,
    bed_height_m: float,
    pellet_diameter_m: float,
    bed_void_fraction: float,
    ergun_a: float,
    ergun_b: float,
    gas_viscosity_pa_s: float,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], float, float, bool]:
    step = distance_m / float(segments)
    current = initial_state.copy()
    profile_positions = np.empty(segments // profile_stride + 2, dtype=np.float64)
    profile_states = np.empty((segments // profile_stride + 2, len(initial_state)), dtype=np.float64)
    profile_count = 0
    min_re = math.inf
    max_re = 0.0
    pressure_positive_ok = current[11] > 0.0

    for segment_index in range(segments):
        position_m = segment_index * step
        k1 = _derivatives(
            current,
            position_m,
            mode,
            axial_area_m2,
            inner_radius_m,
            bed_height_m,
            pellet_diameter_m,
            bed_void_fraction,
            ergun_a,
            ergun_b,
            gas_viscosity_pa_s,
        )
        k2 = _derivatives(
            current + step * k1 / 2.0,
            position_m + step / 2.0,
            mode,
            axial_area_m2,
            inner_radius_m,
            bed_height_m,
            pellet_diameter_m,
            bed_void_fraction,
            ergun_a,
            ergun_b,
            gas_viscosity_pa_s,
        )
        k3 = _derivatives(
            current + step * k2 / 2.0,
            position_m + step / 2.0,
            mode,
            axial_area_m2,
            inner_radius_m,
            bed_height_m,
            pellet_diameter_m,
            bed_void_fraction,
            ergun_a,
            ergun_b,
            gas_viscosity_pa_s,
        )
        k4 = _derivatives(
            current + step * k3,
            position_m + step,
            mode,
            axial_area_m2,
            inner_radius_m,
            bed_height_m,
            pellet_diameter_m,
            bed_void_fraction,
            ergun_a,
            ergun_b,
            gas_viscosity_pa_s,
        )
        current = current + step * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0
        for component_index in range(10):
            current[component_index] = max(current[component_index], 0.0)
        current[10] = max(current[10], 273.15)
        pressure_positive_ok = pressure_positive_ok and current[11] > 0.0
        current[11] = max(current[11], 1.0)

        area_m2 = _flow_area_m2(
            mode,
            axial_area_m2,
            inner_radius_m,
            bed_height_m,
            position_m + step,
        )
        re_value = _re_over_one_minus_void(
            current[:10],
            area_m2,
            pellet_diameter_m,
            bed_void_fraction,
            gas_viscosity_pa_s,
        )
        min_re = min(min_re, re_value)
        max_re = max(max_re, re_value)
        if (segment_index + 1) % profile_stride == 0 or segment_index == segments - 1:
            profile_positions[profile_count] = position_m + step
            profile_states[profile_count] = current
            profile_count += 1

    return (
        current,
        profile_positions[:profile_count],
        profile_states[:profile_count],
        min_re,
        max_re,
        pressure_positive_ok,
    )


@njit(cache=True)  # pyright: ignore[reportUntypedFunctionDecorator]
def _derivatives(
    state: NDArray[np.float64],
    position_m: float,
    mode: int,
    axial_area_m2: float,
    inner_radius_m: float,
    bed_height_m: float,
    pellet_diameter_m: float,
    bed_void_fraction: float,
    ergun_a: float,
    ergun_b: float,
    gas_viscosity_pa_s: float,
) -> NDArray[np.float64]:
    flows = np.maximum(state[:10], 0.0)
    temperature_k = max(state[10], 273.15)
    pressure_pa = max(state[11], 1.0)
    total_flow = max(np.sum(flows), 1e-18)
    partial_pressures = pressure_pa * flows / total_flow
    rates = _reaction_rates(temperature_k, partial_pressures)
    area_m2 = _flow_area_m2(mode, axial_area_m2, inner_radius_m, bed_height_m, position_m)
    derivatives = np.empty(12, dtype=np.float64)
    for component_index in range(10):
        component_derivative = 0.0
        for reaction_index in range(6):
            component_derivative += rates[reaction_index] * STOICHIOMETRY[reaction_index, component_index]
        derivatives[component_index] = area_m2 * component_derivative

    enthalpies = _species_enthalpies(temperature_k)
    reaction_heat = 0.0
    for reaction_index in range(6):
        reaction_heat += rates[reaction_index] * _dot(STOICHIOMETRY[reaction_index], enthalpies)
    heat_capacity_flow = max(_dot(flows, _species_heat_capacities(temperature_k)), 1e-18)
    derivatives[10] = -area_m2 * reaction_heat / heat_capacity_flow

    mass_flow_kg_s = _dot(flows, MOLECULAR_WEIGHTS)
    mean_molecular_weight = mass_flow_kg_s / total_flow
    gas_density_kg_m3 = pressure_pa * mean_molecular_weight / (1000.0 * 8.31446 * temperature_k)
    mass_velocity = mass_flow_kg_s / area_m2
    derivatives[11] = _ergun_pressure_gradient(
        mass_velocity,
        gas_density_kg_m3,
        pellet_diameter_m,
        bed_void_fraction,
        ergun_a,
        ergun_b,
        gas_viscosity_pa_s,
    )
    return derivatives


@njit(cache=True)  # pyright: ignore[reportUntypedFunctionDecorator]
def _reaction_rates(temperature_k: float, pressures: NDArray[np.float64]) -> NDArray[np.float64]:
    rates = np.empty(6, dtype=np.float64)
    rates[0] = (
        0.0473 * math.exp(-90_981.0 / (8.31446 * temperature_k)) * max(pressures[0], 0.0)
        - 5.58e-8
        * math.exp(-61_127.0 / (8.31446 * temperature_k))
        * max(pressures[2], 0.0)
        * max(pressures[3], 0.0)
    )
    rates[1] = 8_267.0 * math.exp(-207_989.0 / (8.31446 * temperature_k)) * max(pressures[0], 0.0)
    rates[2] = (
        4.0385e-7
        * math.exp(-91_515.0 / (8.31446 * temperature_k))
        * max(pressures[0], 0.0)
        * max(pressures[3], 0.0)
    )
    rates[3] = (
        1.1535e-5
        * math.exp(-103_997.0 / (8.31446 * temperature_k))
        * max(pressures[1], 0.0)
        * math.sqrt(max(pressures[7], 0.0))
    )
    rates[4] = (
        4.314e-9
        * math.exp(-65_723.0 / (8.31446 * temperature_k))
        * max(pressures[1], 0.0)
        * max(pressures[8], 0.0)
    )
    rates[5] = (
        8.059e-4
        * math.exp(-73_638.0 / (8.31446 * temperature_k))
        * max(pressures[1], 0.0)
        * max(pressures[9], 0.0)
    )
    return rates


@njit(cache=True)  # pyright: ignore[reportUntypedFunctionDecorator]
def _species_heat_capacities(temperature_k: float) -> NDArray[np.float64]:
    return (
        HEAT_CAPACITY_COEFFICIENTS[:, 0]
        + HEAT_CAPACITY_COEFFICIENTS[:, 1] * temperature_k
        + HEAT_CAPACITY_COEFFICIENTS[:, 2] * temperature_k**2
        + HEAT_CAPACITY_COEFFICIENTS[:, 3] * temperature_k**3
    )


@njit(cache=True)  # pyright: ignore[reportUntypedFunctionDecorator]
def _species_enthalpies(temperature_k: float) -> NDArray[np.float64]:
    reference_temperature_k = 298.15
    return HEAT_OF_FORMATION + (
        HEAT_CAPACITY_COEFFICIENTS[:, 0] * (temperature_k - reference_temperature_k)
        + HEAT_CAPACITY_COEFFICIENTS[:, 1] * (temperature_k**2 - reference_temperature_k**2) / 2.0
        + HEAT_CAPACITY_COEFFICIENTS[:, 2] * (temperature_k**3 - reference_temperature_k**3) / 3.0
        + HEAT_CAPACITY_COEFFICIENTS[:, 3] * (temperature_k**4 - reference_temperature_k**4) / 4.0
    )


@njit(cache=True)  # pyright: ignore[reportUntypedFunctionDecorator]
def _flow_area_m2(
    mode: int,
    axial_area_m2: float,
    inner_radius_m: float,
    bed_height_m: float,
    position_m: float,
) -> float:
    if mode == AXIAL_MODE:
        return axial_area_m2
    return 2.0 * math.pi * (inner_radius_m + position_m) * bed_height_m


@njit(cache=True)  # pyright: ignore[reportUntypedFunctionDecorator]
def _ergun_pressure_gradient(
    mass_velocity: float,
    gas_density_kg_m3: float,
    pellet_diameter_m: float,
    bed_void_fraction: float,
    ergun_a: float,
    ergun_b: float,
    gas_viscosity_pa_s: float,
) -> float:
    viscous = (
        ergun_b
        * (1.0 - bed_void_fraction) ** 2
        * gas_viscosity_pa_s
        * mass_velocity
        / (bed_void_fraction**3 * pellet_diameter_m**2 * gas_density_kg_m3)
    )
    inertial = (
        ergun_a
        * (1.0 - bed_void_fraction)
        * mass_velocity**2
        / (bed_void_fraction**3 * pellet_diameter_m * gas_density_kg_m3)
    )
    return -(viscous + inertial)


@njit(cache=True)  # pyright: ignore[reportUntypedFunctionDecorator]
def _re_over_one_minus_void(
    flows: NDArray[np.float64],
    area_m2: float,
    pellet_diameter_m: float,
    bed_void_fraction: float,
    gas_viscosity_pa_s: float,
) -> float:
    mass_velocity = _dot(flows, MOLECULAR_WEIGHTS) / area_m2
    reynolds = mass_velocity * pellet_diameter_m / max(gas_viscosity_pa_s, 1e-18)
    return reynolds / max(1.0 - bed_void_fraction, 1e-18)


@njit(cache=True)  # pyright: ignore[reportUntypedFunctionDecorator]
def _dot(left: NDArray[np.float64], right: NDArray[np.float64]) -> float:
    value = 0.0
    for index in range(len(left)):
        value += left[index] * right[index]
    return value
