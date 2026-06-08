"""反応器最適化の探索範囲と候補条件。"""

from __future__ import annotations

from dataclasses import dataclass

from process_sim.optimization.models import ParameterRange


# 初期実装で許可する反応器段数。
ALLOWED_REACTOR_STAGE_COUNTS: frozenset[int] = frozenset({2, 3})

# 各段の反応器入口温度範囲。
INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C = ParameterRange(
    lower=550.0,
    upper=650.0,
)

# ラジアル反応器の各段触媒層厚み範囲。
INITIAL_RADIAL_BED_THICKNESS_RANGE_M = ParameterRange(
    lower=0.3,
    upper=1.2,
)

# 全体最適化 v2 の 2 段ラジアル反応器各段触媒層厚み範囲。
WHOLE_PLANT_V2_TWO_STAGE_RADIAL_BED_THICKNESS_RANGE_M = ParameterRange(
    lower=0.6,
    upper=0.9,
)

# 全体最適化 v2 の 3 段ラジアル反応器各段触媒層厚み範囲。
WHOLE_PLANT_V2_THREE_STAGE_RADIAL_BED_THICKNESS_RANGE_M = ParameterRange(
    lower=0.5,
    upper=0.8,
)

# ラジアル反応器列入口圧力範囲。
# 段間再加熱器圧損を見込み、50 から 200 kPa abs とする。
INITIAL_RADIAL_INLET_PRESSURE_RANGE_KPA_ABS = ParameterRange(
    lower=90.0,
    upper=200.0,
)

# ラジアル反応器の Steam/EB モル比範囲。文献側の条件を含める。
INITIAL_RADIAL_STEAM_TO_EB_RATIO_RANGE = ParameterRange(
    lower=5.0,
    upper=11.0,
)

# Pareto v2 用の axial PFR 各段 L/D 範囲。
PARETO_V2_AXIAL_LD_RATIO_RANGE = ParameterRange(
    lower=0.2,
    upper=1.0,
)

# ラジアル反応器入口空塔速度。
RADIAL_INLET_SUPERFICIAL_VELOCITY_M_PER_S = 2.0

# 全体最適化 v2 のラジアル反応器内半径。
WHOLE_PLANT_V2_RADIAL_CENTER_CHANNEL_RADIUS_M = 1.0

# 全体最適化 v2 のラジアル反応器高さ。
WHOLE_PLANT_V2_RADIAL_BED_HEIGHT_M = 6.0


@dataclass(frozen=True)
class RadialReactorParameterConfig:
    """ラジアル反応器最適化変数の探索空間。"""

    stage_inlet_temperatures_c: tuple[ParameterRange, ...]  # 各段の反応器入口温度範囲
    inlet_pressure_kpa_abs: ParameterRange  # 反応器列入口圧力範囲
    steam_to_eb_ratio: ParameterRange  # Steam/EB モル比範囲
    bed_thicknesses_m: tuple[ParameterRange, ...]  # 各段の触媒層厚み範囲

    def __post_init__(self) -> None:
        """探索空間の構造整合性を検証する。"""
        stage_count = len(self.stage_inlet_temperatures_c)
        if stage_count not in ALLOWED_REACTOR_STAGE_COUNTS:
            raise ValueError("stage_count must be 2 or 3")
        if len(self.bed_thicknesses_m) != stage_count:
            raise ValueError(
                "bed_thicknesses_m must have the same length as "
                "stage_inlet_temperatures_c"
            )

    @property
    def stage_count(self) -> int:
        """この探索空間が表す反応器段数。"""
        return len(self.stage_inlet_temperatures_c)


@dataclass(frozen=True)
class RadialReactorCandidate:
    """探索空間から生成された 1 ケース分のラジアル反応器条件。"""

    stage_inlet_temperatures_c: tuple[float, ...]  # 各段の反応器入口温度
    inlet_pressure_kpa_abs: float  # 反応器列入口圧力
    steam_to_eb_ratio: float  # Steam/EB モル比
    bed_thicknesses_m: tuple[float, ...]  # 各段の触媒層厚み

    @property
    def stage_count(self) -> int:
        """この候補条件が表す反応器段数。"""
        return len(self.stage_inlet_temperatures_c)


@dataclass(frozen=True)
class AxialParetoParameterConfig:
    """axial PFR Pareto v2 の探索空間。"""

    stage_inlet_temperatures_c: tuple[ParameterRange, ...]
    inlet_pressure_kpa_abs: ParameterRange
    steam_to_eb_ratio: ParameterRange
    stage_ld_ratios: tuple[ParameterRange, ...]

    def __post_init__(self) -> None:
        """探索空間の構造整合性を検証する。"""
        stage_count = len(self.stage_inlet_temperatures_c)
        if stage_count not in ALLOWED_REACTOR_STAGE_COUNTS:
            raise ValueError("stage_count must be 2 or 3")
        if len(self.stage_ld_ratios) != stage_count:
            raise ValueError(
                "stage_ld_ratios must have the same length as stage_inlet_temperatures_c"
            )

    @property
    def stage_count(self) -> int:
        """この探索空間が表す反応器段数。"""
        return len(self.stage_inlet_temperatures_c)


@dataclass(frozen=True)
class AxialParetoCandidate:
    """axial PFR Pareto v2 の候補条件。"""

    stage_inlet_temperatures_c: tuple[float, ...]
    inlet_pressure_kpa_abs: float
    steam_to_eb_ratio: float
    stage_ld_ratios: tuple[float, ...]

    @property
    def stage_count(self) -> int:
        """候補条件の段数を返す。"""
        return len(self.stage_inlet_temperatures_c)


# 2段ラジアル反応器用の初期探索空間。
TWO_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG = RadialReactorParameterConfig(
    stage_inlet_temperatures_c=(
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
    ),
    inlet_pressure_kpa_abs=INITIAL_RADIAL_INLET_PRESSURE_RANGE_KPA_ABS,
    steam_to_eb_ratio=INITIAL_RADIAL_STEAM_TO_EB_RATIO_RANGE,
    bed_thicknesses_m=(
        INITIAL_RADIAL_BED_THICKNESS_RANGE_M,
        INITIAL_RADIAL_BED_THICKNESS_RANGE_M,
    ),
)

# 3段ラジアル反応器用の初期探索空間。
THREE_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG = RadialReactorParameterConfig(
    stage_inlet_temperatures_c=(
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
    ),
    inlet_pressure_kpa_abs=INITIAL_RADIAL_INLET_PRESSURE_RANGE_KPA_ABS,
    steam_to_eb_ratio=INITIAL_RADIAL_STEAM_TO_EB_RATIO_RANGE,
    bed_thicknesses_m=(
        INITIAL_RADIAL_BED_THICKNESS_RANGE_M,
        INITIAL_RADIAL_BED_THICKNESS_RANGE_M,
        INITIAL_RADIAL_BED_THICKNESS_RANGE_M,
    ),
)

# 全体最適化 v2 の 2 段ラジアル反応器用探索空間。
TWO_STAGE_WHOLE_PLANT_V2_RADIAL_REACTOR_PARAMETER_CONFIG = RadialReactorParameterConfig(
    stage_inlet_temperatures_c=(
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
    ),
    inlet_pressure_kpa_abs=ParameterRange(lower=80.0, upper=200.0),
    steam_to_eb_ratio=INITIAL_RADIAL_STEAM_TO_EB_RATIO_RANGE,
    bed_thicknesses_m=(
        WHOLE_PLANT_V2_TWO_STAGE_RADIAL_BED_THICKNESS_RANGE_M,
        WHOLE_PLANT_V2_TWO_STAGE_RADIAL_BED_THICKNESS_RANGE_M,
    ),
)

# 全体最適化 v2 の 3 段ラジアル反応器用探索空間。
THREE_STAGE_WHOLE_PLANT_V2_RADIAL_REACTOR_PARAMETER_CONFIG = (
    RadialReactorParameterConfig(
        stage_inlet_temperatures_c=(
            INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
            INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
            INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
        ),
        inlet_pressure_kpa_abs=ParameterRange(lower=100.0, upper=200.0),
        steam_to_eb_ratio=INITIAL_RADIAL_STEAM_TO_EB_RATIO_RANGE,
        bed_thicknesses_m=(
            WHOLE_PLANT_V2_THREE_STAGE_RADIAL_BED_THICKNESS_RANGE_M,
            WHOLE_PLANT_V2_THREE_STAGE_RADIAL_BED_THICKNESS_RANGE_M,
            WHOLE_PLANT_V2_THREE_STAGE_RADIAL_BED_THICKNESS_RANGE_M,
        ),
    )
)

# 2段 axial PFR Pareto v2 用探索空間。
TWO_STAGE_AXIAL_PARETO_PARAMETER_CONFIG = AxialParetoParameterConfig(
    stage_inlet_temperatures_c=(
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
    ),
    inlet_pressure_kpa_abs=ParameterRange(lower=80.0, upper=300.0),
    steam_to_eb_ratio=INITIAL_RADIAL_STEAM_TO_EB_RATIO_RANGE,
    stage_ld_ratios=(
        PARETO_V2_AXIAL_LD_RATIO_RANGE,
        PARETO_V2_AXIAL_LD_RATIO_RANGE,
    ),
)

# 3段 axial PFR Pareto v2 用探索空間。
THREE_STAGE_AXIAL_PARETO_PARAMETER_CONFIG = AxialParetoParameterConfig(
    stage_inlet_temperatures_c=(
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
        INITIAL_STAGE_INLET_TEMPERATURE_RANGE_C,
    ),
    inlet_pressure_kpa_abs=ParameterRange(lower=100.0, upper=300.0),
    steam_to_eb_ratio=INITIAL_RADIAL_STEAM_TO_EB_RATIO_RANGE,
    stage_ld_ratios=(
        PARETO_V2_AXIAL_LD_RATIO_RANGE,
        PARETO_V2_AXIAL_LD_RATIO_RANGE,
        PARETO_V2_AXIAL_LD_RATIO_RANGE,
    ),
)
