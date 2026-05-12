"""反応器最適化の実現性制約。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReactorOptimizationConstraints:
    """反応器候補条件に対する物理・設計上の制約値。"""

    min_outlet_pressure_kpa_abs: float      # 反応器列出口圧力の下限
    pressure_drop_kpa_per_reactor: float    # 反応器1基あたりの圧力損失
    min_steam_to_eb_ratio: float            # Steam/EB モル比の下限
    max_stage_inlet_temperature_c: float    # 各段の反応器入口温度の上限


# 初期実装で使う反応器最適化制約値。
INITIAL_REACTOR_OPTIMIZATION_CONSTRAINTS = ReactorOptimizationConstraints(
    min_outlet_pressure_kpa_abs=10.1,
    pressure_drop_kpa_per_reactor=20.0,
    min_steam_to_eb_ratio=5.0,
    max_stage_inlet_temperature_c=650.0,
)
