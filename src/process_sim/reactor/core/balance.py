"""PFR の物質収支と熱収支。"""

from __future__ import annotations

from dataclasses import dataclass

from process_sim.constants.physical_properties import SpeciesPhysicalProperty
from process_sim.constants.reaction_networks import ReactionNetwork
from process_sim.constants.universal import UniversalConstants
from process_sim.reactor.core.pressure_drop import ErgunParameters, ergun_pressure_gradient_pa_per_m
from process_sim.reactor.core.reaction import reaction_rates
from process_sim.reactor.core.stream import COMPONENT_ORDER
from process_sim.reactor.core.thermodynamics import reaction_enthalpy_kj_per_kmol, species_heat_capacity_kj_per_kmol_k


@dataclass(frozen=True)
class ReactorBalanceContext:
    """収支計算に必要な外部条件。"""

    cross_section_area_m2: float
    network: ReactionNetwork
    properties: dict[str, SpeciesPhysicalProperty]
    universal: UniversalConstants
    ergun_parameters: ErgunParameters


@dataclass(frozen=True)
class RadialBalanceContext:
    """ラジアルフロー反応器の収支計算に必要な外部条件。"""

    radius_m: float
    flow_area_m2: float
    network: ReactionNetwork
    properties: dict[str, SpeciesPhysicalProperty]
    universal: UniversalConstants
    ergun_parameters: ErgunParameters


def pfr_adiabatic_derivatives(state_vector: list[float], context: ReactorBalanceContext) -> list[float]:
    """断熱PFRの dF/dz、dT/dz、dP/dz を返す。"""
    flows_kmol_s = [max(value, 0.0) for value in state_vector[: len(COMPONENT_ORDER)]]
    temperature_k = max(state_vector[len(COMPONENT_ORDER)], 273.15)
    pressure_pa = max(state_vector[len(COMPONENT_ORDER) + 1], 1.0)
    total_flow_kmol_s = max(sum(flows_kmol_s), 1e-18)
    partial_pressures_pa = {
        name: pressure_pa * flow / total_flow_kmol_s
        for name, flow in zip(COMPONENT_ORDER, flows_kmol_s, strict=True)
    }

    rates = reaction_rates(
        network=context.network,
        temperature_k=temperature_k,
        partial_pressures_pa=partial_pressures_pa,
        universal=context.universal,
    )
    rate_by_reaction_id = {rate.reaction_id: rate.rate_kmol_per_s_m3 for rate in rates}

    component_derivatives = [0.0 for _ in COMPONENT_ORDER]
    for reaction in context.network.reactions:
        rate = rate_by_reaction_id[reaction.reaction_id]
        for component_id, coefficient in reaction.stoichiometry.items():
            component_index = COMPONENT_ORDER.index(component_id)
            component_derivatives[component_index] += context.cross_section_area_m2 * coefficient * rate

    reaction_heat_kj_per_m3_s = sum(
        rate_by_reaction_id[reaction.reaction_id]
        * reaction_enthalpy_kj_per_kmol(
            reaction=reaction,
            temperature_k=temperature_k,
            properties=context.properties,
            universal=context.universal,
        )
        for reaction in context.network.reactions
    )
    flow_heat_capacity_kj_per_s_k = sum(
        flow * species_heat_capacity_kj_per_kmol_k(
            component_id=name,
            temperature_k=temperature_k,
            properties=context.properties,
        )
        for name, flow in zip(COMPONENT_ORDER, flows_kmol_s, strict=True)
    )
    temperature_derivative = -context.cross_section_area_m2 * reaction_heat_kj_per_m3_s / max(flow_heat_capacity_kj_per_s_k, 1e-18)
    gas_density_kg_m3 = _gas_density_kg_m3(
        flows_kmol_s=flows_kmol_s,
        pressure_pa=pressure_pa,
        temperature_k=temperature_k,
        properties=context.properties,
        universal=context.universal,
    )
    mass_velocity_kg_m2_s = _mass_flow_kg_s(flows_kmol_s=flows_kmol_s, properties=context.properties) / context.cross_section_area_m2
    pressure_derivative = ergun_pressure_gradient_pa_per_m(
        superficial_mass_velocity_kg_m2_s=mass_velocity_kg_m2_s,
        gas_density_kg_m3=gas_density_kg_m3,
        parameters=context.ergun_parameters,
    )
    return component_derivatives + [temperature_derivative, pressure_derivative]


def radial_adiabatic_derivatives(state_vector: list[float], context: RadialBalanceContext) -> list[float]:
    """断熱ラジアルフロー反応器の dF/dr、dT/dr、dP/dr を返す。"""
    flows_kmol_s = [max(value, 0.0) for value in state_vector[: len(COMPONENT_ORDER)]]
    temperature_k = max(state_vector[len(COMPONENT_ORDER)], 273.15)
    pressure_pa = max(state_vector[len(COMPONENT_ORDER) + 1], 1.0)
    total_flow_kmol_s = max(sum(flows_kmol_s), 1e-18)
    partial_pressures_pa = {
        name: pressure_pa * flow / total_flow_kmol_s
        for name, flow in zip(COMPONENT_ORDER, flows_kmol_s, strict=True)
    }

    rates = reaction_rates(
        network=context.network,
        temperature_k=temperature_k,
        partial_pressures_pa=partial_pressures_pa,
        universal=context.universal,
    )
    rate_by_reaction_id = {rate.reaction_id: rate.rate_kmol_per_s_m3 for rate in rates}

    component_derivatives = [0.0 for _ in COMPONENT_ORDER]
    for reaction in context.network.reactions:
        rate = rate_by_reaction_id[reaction.reaction_id]
        for component_id, coefficient in reaction.stoichiometry.items():
            component_index = COMPONENT_ORDER.index(component_id)
            component_derivatives[component_index] += context.flow_area_m2 * coefficient * rate

    reaction_heat_kj_per_m3_s = sum(
        rate_by_reaction_id[reaction.reaction_id]
        * reaction_enthalpy_kj_per_kmol(
            reaction=reaction,
            temperature_k=temperature_k,
            properties=context.properties,
            universal=context.universal,
        )
        for reaction in context.network.reactions
    )
    flow_heat_capacity_kj_per_s_k = sum(
        flow * species_heat_capacity_kj_per_kmol_k(
            component_id=name,
            temperature_k=temperature_k,
            properties=context.properties,
        )
        for name, flow in zip(COMPONENT_ORDER, flows_kmol_s, strict=True)
    )
    temperature_derivative = -context.flow_area_m2 * reaction_heat_kj_per_m3_s / max(flow_heat_capacity_kj_per_s_k, 1e-18)
    gas_density_kg_m3 = _gas_density_kg_m3(
        flows_kmol_s=flows_kmol_s,
        pressure_pa=pressure_pa,
        temperature_k=temperature_k,
        properties=context.properties,
        universal=context.universal,
    )
    mass_velocity_kg_m2_s = _mass_flow_kg_s(flows_kmol_s=flows_kmol_s, properties=context.properties) / context.flow_area_m2
    pressure_derivative = ergun_pressure_gradient_pa_per_m(
        superficial_mass_velocity_kg_m2_s=mass_velocity_kg_m2_s,
        gas_density_kg_m3=gas_density_kg_m3,
        parameters=context.ergun_parameters,
    )
    return component_derivatives + [temperature_derivative, pressure_derivative]


def _mass_flow_kg_s(flows_kmol_s: list[float], properties: dict[str, SpeciesPhysicalProperty]) -> float:
    return sum(
        flow * properties[name].molecular_weight
        for name, flow in zip(COMPONENT_ORDER, flows_kmol_s, strict=True)
    )


def _gas_density_kg_m3(
    flows_kmol_s: list[float],
    pressure_pa: float,
    temperature_k: float,
    properties: dict[str, SpeciesPhysicalProperty],
    universal: UniversalConstants,
) -> float:
    total_flow_kmol_s = max(sum(flows_kmol_s), 1e-18)
    mean_molecular_weight_kg_per_kmol = sum(
        flow / total_flow_kmol_s * properties[name].molecular_weight
        for name, flow in zip(COMPONENT_ORDER, flows_kmol_s, strict=True)
    )
    return pressure_pa * mean_molecular_weight_kg_per_kmol / (
        1000.0 * universal.gas_constant_j_per_mol_k * temperature_k
    )
