"""反応器モデルで使う既定定数。

値の出典は `data/report_md/repoet_7.md` と `data/chem_contest.md` を優先し、
不足分は「最小実装としての初期値」として明示する。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UniversalConstants:
    """物理定数。"""

    gas_constant_kj_per_kmol_k: float = 8.314  # [kJ/(kmol K)]
    atm_per_kpa: float = 1.0 / 101.325


@dataclass(frozen=True)
class KineticsConstants:
    """EB 脱水素モデルの速度式定数。"""

    g11: float = 1.090e6  # [kmol/(m^3 h atm)]
    e11_kj_per_kmol: float = 74170.0

    g12: float = 0.1929  # [kmol/(m^3 h atm^2)]
    e12_kj_per_kmol: float = -50409.0

    g2: float = 5.690e9  # [kmol/(m^3 h atm)]
    e2_kj_per_kmol: float = 160620.0

    g3: float = 2.490e10  # [kmol/(m^3 h atm)]
    e3_kj_per_kmol: float = 165100.0


@dataclass(frozen=True)
class ReactorOperationDefaults:
    """反応器の既定操作条件。"""

    pressure_kpa: float = 152.0  # [kPa] およそ 1.5 atm
    temperature_c: float = 600.0  # [degC]
    steam_to_hydrocarbon_molar_ratio: float = 5.0

    catalyst_void_fraction: float = 0.5
    reactor_volume_m3: float = 15.0
    integration_steps: int = 200


@dataclass(frozen=True)
class ReactorConfigDefaults:
    universal: UniversalConstants = UniversalConstants()
    kinetics: KineticsConstants = KineticsConstants()
    operation: ReactorOperationDefaults = ReactorOperationDefaults()


DEFAULT_REACTOR_CONFIG = ReactorConfigDefaults()
