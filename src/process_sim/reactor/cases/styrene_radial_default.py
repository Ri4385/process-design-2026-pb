"""スチレン用ラジアルフロー反応器の既定ケース。"""

from __future__ import annotations

from dataclasses import dataclass

from process_sim.reactor.cases.styrene_default import DEFAULT_STYRENE_FEED
from process_sim.reactor.core.models import RadialReactorRunConditions
from process_sim.reactor.core.stream import ReactorFeed


@dataclass(frozen=True)
class RadialReactorCase:
    """ラジアルフロー反応器の実行ケース。"""

    feed: ReactorFeed
    conditions: RadialReactorRunConditions


DEFAULT_STAGED_ADIABATIC_RADIAL_CONDITIONS = RadialReactorRunConditions(
    inlet_pressure_pa=130_000.0,
    stage_inlet_temperatures_k=(900.0, 900.0, 900.0),
    bed_inner_radius_m=1.0,
    bed_height_m=5.0,
    bed_thicknesses_m=(0.90, 0.90, 0.90),
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


DEFAULT_STYRENE_RADIAL_REACTOR_CASE = RadialReactorCase(
    feed=DEFAULT_STYRENE_FEED,
    conditions=DEFAULT_STAGED_ADIABATIC_RADIAL_CONDITIONS,
)
