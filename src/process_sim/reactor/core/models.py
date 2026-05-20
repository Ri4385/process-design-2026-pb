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
    total_catalyst_volume_m3: float
    pellet_diameter_m: float
    bed_void_fraction: float
    catalyst_bulk_density_kg_m3: float
    ergun_a: float
    ergun_b: float
    gas_viscosity_pa_s: float
    interstage_reheater_pressure_drop_pa: float
    segments_per_stage: int
    profile_points_per_stage: int


@dataclass(frozen=True)
class RadialReactorRunConditions:
    """多段断熱ラジアルフロー反応器のシミュレーション条件。"""

    inlet_pressure_pa: float
    stage_inlet_temperatures_k: tuple[float, ...]
    bed_inner_radius_m: float
    bed_height_m: float
    bed_thicknesses_m: tuple[float, ...]
    pellet_diameter_m: float
    bed_void_fraction: float
    catalyst_bulk_density_kg_m3: float
    ergun_a: float
    ergun_b: float
    gas_viscosity_pa_s: float
    interstage_reheater_pressure_drop_pa: float
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
    radial_position_m: float | None = None
    bed_fraction: float | None = None
    pressure_kpa: float | None = None
    superficial_velocity_m_per_s: float | None = None
    re_over_one_minus_void: float | None = None


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
    inlet_pressure_kpa: float | None = None
    outlet_pressure_kpa: float | None = None
    reactor_pressure_drop_kpa: float | None = None
    reheat_pressure_drop_kpa: float | None = None
    inner_radius_m: float | None = None
    outer_radius_m: float | None = None
    bed_height_m: float | None = None
    bed_thickness_m: float | None = None
    catalyst_volume_m3: float | None = None
    catalyst_mass_kg: float | None = None
    min_re_over_one_minus_void: float | None = None
    max_re_over_one_minus_void: float | None = None
    carbon_balance_error_fraction: float | None = None
    hydrogen_balance_error_fraction: float | None = None
    pressure_positive_ok: bool | None = None


@dataclass(frozen=True)
class ReactorRunLog:
    """反応器列全体のログ。"""

    cross_section_area_m2: float
    inlet_volumetric_flow_m3_s: float
    stage_logs: tuple[ReactorStageLog, ...]
    profile: tuple[ReactorProfilePoint, ...]
    reactor_pressure_drop_kpa: float | None = None
    reheat_pressure_drop_kpa: float | None = None
    total_pressure_drop_kpa: float | None = None
    total_catalyst_volume_m3: float | None = None
    total_catalyst_mass_kg: float | None = None
    max_re_over_one_minus_void: float | None = None
    carbon_balance_error_fraction: float | None = None
    hydrogen_balance_error_fraction: float | None = None
    atom_balance_ok: bool | None = None
    outlet_pressure_ok: bool | None = None
    pressure_positive_ok: bool | None = None
    ergun_range_ok: bool | None = None


@dataclass(frozen=True)
class ReactorResult:
    """反応器列の計算結果。"""

    outlet: ReactorState
    eb_conversion: float
    styrene_selectivity: float
    log: ReactorRunLog
