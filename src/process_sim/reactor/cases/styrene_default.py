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
    pressure_kpa=101.325,
    stage_inlet_temperatures_c=(550.0, 550.0, 550.0),
    stage_lengths_m=(1.5, 3.0, 3.0),
    inlet_superficial_velocity_m_per_s=1.93,
    segments_per_stage=12000,
    profile_points_per_stage=12,
)

DEFAULT_STYRENE_REACTOR_CASE = ReactorCase(
    feed=DEFAULT_STYRENE_FEED,
    conditions=DEFAULT_STAGED_ADIABATIC_CONDITIONS,
)
