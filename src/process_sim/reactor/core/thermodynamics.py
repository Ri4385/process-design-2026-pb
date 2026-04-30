"""反応器計算で使う熱力学計算。"""

from __future__ import annotations

from process_sim.constants.physical_properties import SpeciesPhysicalProperty
from process_sim.constants.reaction_networks import ReactionNetworkItem
from process_sim.constants.universal import UniversalConstants


def species_heat_capacity_kj_per_kmol_k(
    component_id: str,
    temperature_k: float,
    properties: dict[str, SpeciesPhysicalProperty],
) -> float:
    """成分の定圧モル比熱を返す。"""
    coefficients = properties[component_id].heat_capacity
    return (
        coefficients.a
        + coefficients.b * temperature_k
        + coefficients.c * temperature_k * temperature_k
        + coefficients.d * temperature_k * temperature_k * temperature_k
    )


def species_enthalpy_kj_per_kmol(
    component_id: str,
    temperature_k: float,
    properties: dict[str, SpeciesPhysicalProperty],
    universal: UniversalConstants,
) -> float:
    """基準温度の標準生成エンタルピーと Cp 積分から成分エンタルピーを返す。"""
    property_ = properties[component_id]
    coefficients = property_.heat_capacity
    reference_temperature_k = universal.reference_temperature_k
    return property_.heat_of_formation_kj_per_kmol + (
        coefficients.a * (temperature_k - reference_temperature_k)
        + coefficients.b * (temperature_k * temperature_k - reference_temperature_k * reference_temperature_k) / 2.0
        + coefficients.c
        * (temperature_k * temperature_k * temperature_k - reference_temperature_k * reference_temperature_k * reference_temperature_k)
        / 3.0
        + coefficients.d
        * (
            temperature_k * temperature_k * temperature_k * temperature_k
            - reference_temperature_k * reference_temperature_k * reference_temperature_k * reference_temperature_k
        )
        / 4.0
    )


def reaction_enthalpy_kj_per_kmol(
    reaction: ReactionNetworkItem,
    temperature_k: float,
    properties: dict[str, SpeciesPhysicalProperty],
    universal: UniversalConstants,
) -> float:
    """反応の温度依存エンタルピーを返す。"""
    return sum(
        coefficient * species_enthalpy_kj_per_kmol(
            component_id=component_id,
            temperature_k=temperature_k,
            properties=properties,
            universal=universal,
        )
        for component_id, coefficient in reaction.stoichiometry.items()
    )


def standard_reaction_enthalpy_kj_per_kmol(
    reaction: ReactionNetworkItem,
    properties: dict[str, SpeciesPhysicalProperty],
    universal: UniversalConstants,
) -> float:
    """基準温度における標準反応エンタルピーを返す。"""
    return reaction_enthalpy_kj_per_kmol(
        reaction=reaction,
        temperature_k=universal.reference_temperature_k,
        properties=properties,
        universal=universal,
    )
