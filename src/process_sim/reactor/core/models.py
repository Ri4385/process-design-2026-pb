"""反応器計算の入出力モデル。"""

from __future__ import annotations

from dataclasses import dataclass

from process_sim.reactor.core.stream import ReactorStream


@dataclass(frozen=True)
class ReactorRunConditions:
    """多段断熱PFRのシミュレーション条件。"""

    pressure_kpa: float
    stage_inlet_temperatures_c: tuple[float, ...]
    stage_lengths_m: tuple[float, ...]
    inlet_superficial_velocity_m_per_s: float
    segments_per_stage: int
    profile_points_per_stage: int


@dataclass(frozen=True)
class ReactorState:
    """反応器列中の状態。"""

    stage_index: int
    axial_position_m: float
    cumulative_length_m: float
    temperature_c: float
    pressure_kpa: float
    stream: ReactorStream


@dataclass(frozen=True)
class ReactorProfilePoint:
    """軸方向プロファイルの記録点。"""

    stage_index: int
    axial_position_m: float
    cumulative_length_m: float
    temperature_c: float
    eb_conversion: float
    styrene_selectivity: float
    stream: ReactorStream


@dataclass(frozen=True)
class ReactorStageLog:
    """各段の要約ログ。"""

    stage_index: int
    inlet_temperature_c: float
    outlet_temperature_c: float
    stage_length_m: float
    inlet_superficial_velocity_m_per_s: float
    outlet_superficial_velocity_m_per_s: float
    eb_conversion: float
    styrene_selectivity: float
    reheat_duty_mw: float | None
    inlet: ReactorStream
    outlet: ReactorStream


@dataclass(frozen=True)
class ReactorRunLog:
    """反応器列全体のログ。"""

    cross_section_area_m2: float
    inlet_volumetric_flow_m3_s: float
    stage_logs: tuple[ReactorStageLog, ...]
    profile: tuple[ReactorProfilePoint, ...]


@dataclass(frozen=True)
class ReactorResult:
    """反応器列の計算結果。"""

    outlet: ReactorState
    eb_conversion: float
    styrene_selectivity: float
    log: ReactorRunLog
