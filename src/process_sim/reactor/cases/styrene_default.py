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
    eb=605.9,
    steam=3029.5,
    styrene=0.0606,
    hydrogen=0.0,
    benzene=0.0606,
    toluene=0.0606,
    co2=0.0,
    ethylene=0.0,
    methane=0.0,
    co=0.0,
)

DEFAULT_STAGED_ADIABATIC_CONDITIONS = ReactorRunConditions(
    pressure_kpa=200.0,
    stage_inlet_temperatures_c=(550.0, 550.0, 550.0),
    stage_lengths_m=(2.5, 2.5, 2.5),
    total_catalyst_volume_m3=99.31304592692096,
    pellet_diameter_m=0.003,
    bed_void_fraction=0.4312,
    catalyst_bulk_density_kg_m3=1422.0,
    ergun_a=1.75,
    ergun_b=150.0,
    gas_viscosity_pa_s=4.0e-5,
    interstage_reheater_pressure_drop_pa=20_000.0,
    segments_per_stage=12000,
    profile_points_per_stage=12,
)

DEFAULT_STYRENE_REACTOR_CASE = ReactorCase(
    feed=DEFAULT_STYRENE_FEED,
    conditions=DEFAULT_STAGED_ADIABATIC_CONDITIONS,
)
