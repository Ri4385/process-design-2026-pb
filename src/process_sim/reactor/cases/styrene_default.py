"""スチレン反応器の既定ケース。"""

from __future__ import annotations

from dataclasses import dataclass

from process_sim.reactor.core.models import ReactorRunConditions
from process_sim.reactor.core.stream import ReactorFeed


@dataclass(frozen=True)
class ReactorCase:
    """反応器実行ケース。"""

    feed: ReactorFeed
    conditions: ReactorRunConditions


DEFAULT_STYRENE_FEED = ReactorFeed(
    eb=395.707,
    steam=395.707 * 6.86,
    styrene=0.495,
    hydrogen=0.025,
    benzene=1.393,
    toluene=1.998,
    co2=0.053,
    ethylene=0.0,
    methane=0.004,
    co=0.0,
)

DEFAULT_STAGED_ADIABATIC_CONDITIONS = ReactorRunConditions(
    pressure_kpa=300.0,
    stage_inlet_temperatures_c=(550.0, 570.0, 600.0),
    inlet_superficial_velocity_m_per_s=1.8,
    stage_ld_ratios=(0.7, 0.7, 0.7),
    pellet_diameter_m=0.003,
    bed_void_fraction=0.4312,
    catalyst_bulk_density_kg_m3=1422.0,
    ergun_a=1.75,
    ergun_b=150.0,
    gas_viscosity_pa_s=2.6e-5,
    interstage_reheater_pressure_drop_pa=20_000.0,
    segments_per_stage=16000,
    profile_points_per_stage=12,
    min_outlet_pressure_kpa_abs=60.0,
    max_stage_length_m=10.0,
    min_superficial_velocity_m_per_s=1.0,
    max_superficial_velocity_m_per_s=3.0,
)

DEFAULT_STYRENE_REACTOR_CASE = ReactorCase(
    feed=DEFAULT_STYRENE_FEED,
    conditions=DEFAULT_STAGED_ADIABATIC_CONDITIONS,
)
