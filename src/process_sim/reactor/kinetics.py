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
    r = universal.gas_constant_kj_per_kmol_k

    return RateConstants(
        k11=kinetics.g11 * math.exp(-kinetics.e11_kj_per_kmol / (r * temperature_k)),
        k12=kinetics.g12 * math.exp(-kinetics.e12_kj_per_kmol / (r * temperature_k)),
        k2=kinetics.g2 * math.exp(-kinetics.e2_kj_per_kmol / (r * temperature_k)),
        k3=kinetics.g3 * math.exp(-kinetics.e3_kj_per_kmol / (r * temperature_k)),
    )
