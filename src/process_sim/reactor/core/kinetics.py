"""反応速度式の評価。"""

from __future__ import annotations

import math

from process_sim.constants.reaction_networks import ArrheniusTerm
from process_sim.constants.universal import UniversalConstants


def arrhenius_rate_constant(
    temperature_k: float,
    term: ArrheniusTerm,
    universal: UniversalConstants,
) -> float:
    """アレニウス式で速度定数を返す。"""
    return term.pre_exponential * math.exp(-term.activation_energy_j_per_mol / (universal.gas_constant_j_per_mol_k * temperature_k))


def reaction_rate_from_partial_pressures(
    temperature_k: float,
    partial_pressures_pa: dict[str, float],
    term: ArrheniusTerm,
    universal: UniversalConstants,
) -> float:
    """分圧から反応速度を返す。単位は反応ネットワーク定義に従う。"""
    rate = arrhenius_rate_constant(temperature_k=temperature_k, term=term, universal=universal)
    for component_id, order in term.partial_pressure_orders.items():
        pressure = max(partial_pressures_pa.get(component_id, 0.0), 0.0)
        rate *= pressure**order
    return rate
