"""反応器最適化の探索範囲と候補条件。"""

from __future__ import annotations

from dataclasses import dataclass

from process_sim.optimization.models import ParameterRange


# 初期実装で許可する反応器段数。
ALLOWED_REACTOR_STAGE_COUNTS: frozenset[int] = frozenset({2, 3})

# 各段の反応器入口温度範囲。
INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C = ParameterRange(
    lower=590.0,
    upper=650.0,
)

# 反応器列入口圧力範囲。
# 0.1 atm から 1.5 atm 相当として置く。
INITIAL_INLET_PRESSURE_RANGE_KPA_ABS = ParameterRange(
    lower=10.1,
    upper=152.0,
)

# Steam/EB モル比範囲。
INITIAL_STEAM_TO_EB_RATIO_RANGE = ParameterRange(
    lower=5.0,
    upper=8.0,
)

# 各段の反応器長さ範囲。
# 段長範囲は暫定値として置く。
INITIAL_STAGE_LENGTH_RANGE_M = ParameterRange(
    lower=0.5,
    upper=5.0,
)


@dataclass(frozen=True)
class ReactorParameterConfig:
    """反応器最適化変数の探索空間。"""

    # 各段の反応器入口温度範囲。
    stage_inlet_temperatures_c: tuple[ParameterRange, ...]
    # 反応器列入口圧力範囲。
    inlet_pressure_kpa_abs: ParameterRange
    # Steam/EB モル比範囲。
    steam_to_eb_ratio: ParameterRange
    # 各段の反応器長さ範囲。
    stage_lengths_m: tuple[ParameterRange, ...]

    def __post_init__(self) -> None:
        """探索空間の構造整合性を検証する。"""
        stage_count = len(self.stage_inlet_temperatures_c)

        if stage_count not in ALLOWED_REACTOR_STAGE_COUNTS:
            raise ValueError("stage_count must be 2 or 3")

        if len(self.stage_lengths_m) != stage_count:
            raise ValueError(
                "stage_lengths_m must have the same length as "
                "stage_inlet_temperatures_c"
            )

    @property
    def stage_count(self) -> int:
        """この探索空間が表す反応器段数。"""
        return len(self.stage_inlet_temperatures_c)


@dataclass(frozen=True)
class ReactorCandidate:
    """探索空間から生成された 1 ケース分の反応器条件。"""

    # 各段の反応器入口温度。
    stage_inlet_temperatures_c: tuple[float, ...]
    # 反応器列入口圧力。
    inlet_pressure_kpa_abs: float
    # Steam/EB モル比。
    steam_to_eb_ratio: float
    # 各段の反応器長さ。
    stage_lengths_m: tuple[float, ...]

    @property
    def stage_count(self) -> int:
        """この候補条件が表す反応器段数。"""
        return len(self.stage_inlet_temperatures_c)


# 2段反応器用の初期探索空間。
TWO_STAGE_REACTOR_PARAMETER_CONFIG = ReactorParameterConfig(
    stage_inlet_temperatures_c=(
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
    ),
    inlet_pressure_kpa_abs=INITIAL_INLET_PRESSURE_RANGE_KPA_ABS,
    steam_to_eb_ratio=INITIAL_STEAM_TO_EB_RATIO_RANGE,
    stage_lengths_m=(
        INITIAL_STAGE_LENGTH_RANGE_M,
        INITIAL_STAGE_LENGTH_RANGE_M,
    ),
)

# 3段反応器用の初期探索空間。
THREE_STAGE_REACTOR_PARAMETER_CONFIG = ReactorParameterConfig(
    stage_inlet_temperatures_c=(
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
    ),
    inlet_pressure_kpa_abs=INITIAL_INLET_PRESSURE_RANGE_KPA_ABS,
    steam_to_eb_ratio=INITIAL_STEAM_TO_EB_RATIO_RANGE,
    stage_lengths_m=(
        INITIAL_STAGE_LENGTH_RANGE_M,
        INITIAL_STAGE_LENGTH_RANGE_M,
        INITIAL_STAGE_LENGTH_RANGE_M,
    ),
)
