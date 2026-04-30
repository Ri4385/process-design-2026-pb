"""プロセス計算で使う普遍定数と単位換算。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UniversalConstants:
    """普遍定数と共通単位換算。"""

    gas_constant_j_per_mol_k: float = 8.31446
    reference_temperature_k: float = 298.15
    pa_per_kpa: float = 1000.0


UNIVERSAL_CONSTANTS = UniversalConstants()
