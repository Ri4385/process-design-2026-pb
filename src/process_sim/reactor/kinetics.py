"""反応速度式。"""

from __future__ import annotations

from dataclasses import dataclass
import math

from process_sim.constants import KineticsConstants, UniversalConstants


@dataclass(frozen=True)
class RateConstants:
    k11: float
    k12: float
    k2: float
    k3: float


def arrhenius_rate_constants(
    temperature_k: float,
    kinetics: KineticsConstants,
    universal: UniversalConstants,
) -> RateConstants:
    """アレニウス式で速度定数を返す。"""
    r = universal.gas_constant_j_per_mol_k
    per_hour_to_per_second = 1.0 / 3600.0

    return RateConstants(
        k11=per_hour_to_per_second
        * kinetics.k11_pre_exponential
        * math.exp(-kinetics.k11_activation_energy_j_per_mol / (r * temperature_k)),
        k12=per_hour_to_per_second
        * kinetics.k12_pre_exponential
        * math.exp(-kinetics.k12_activation_energy_j_per_mol / (r * temperature_k)),
        k2=per_hour_to_per_second
        * kinetics.k2_pre_exponential
        * math.exp(-kinetics.k2_activation_energy_j_per_mol / (r * temperature_k)),
        k3=per_hour_to_per_second
        * kinetics.k3_pre_exponential
        * math.exp(-kinetics.k3_activation_energy_j_per_mol / (r * temperature_k)),
    )
