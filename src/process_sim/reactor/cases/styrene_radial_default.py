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

# 2026-05-21 18:33:05,030 started study=radial_2stage_fast_plant_profit trial=7 s
# tage_count=2 T=[553.44, 640.93] degC P=96.757 kPa abs S/EB=8.120 thickness=[0.533, 0.896] m
# 2026-05-21 18:37:45,128 finished study=radial_2stage_fast_plant_profit trial=7 
# objective=5.018587e+09 EB_conv=0.5048 SM_sel=0.9674 outlet_P=64.849 kPa stage_count=2 T=[553.44, 640.93] degC P=96.757 kPa abs S/EB=8.120 thickness=[0.533, 0.896] m

# objective=2.082874e+09 params={
# 'stage_1_temperature_c': 573.8693404652156, 
# 'stage_2_temperature_c': 587.0799953741401, 
# 'stage_3_temperature_c': 624.4798242389589, 
# 'stage_1_bed_thickness_m': 0.36554081336023214, 
# 'stage_2_bed_thickness_m': 0.8861172009761208, 
# 'stage_3_bed_thickness_m': 0.9231235341441183, 
# 'inlet_pressure_kpa_abs': 105.28175313472731, 
# 'steam_to_eb_ratio': 6.867833893697469}


DEFAULT_STAGED_ADIABATIC_RADIAL_CONDITIONS = RadialReactorRunConditions(
    inlet_pressure_pa=105_280.0,
    stage_inlet_temperatures_k=(273.15 + 573.86, 273.15 + 587.07, 273.15 + 624.47),
    inlet_superficial_velocity_m_per_s=2.0,
    bed_height_m=7.0,
    bed_thicknesses_m=(0.3655, 0.8861,0.9231),
    pellet_diameter_m=0.003,
    bed_void_fraction=0.4312,
    catalyst_bulk_density_kg_m3=1422.0,
    ergun_a=1.75,
    ergun_b=150.0,
    gas_viscosity_pa_s=2.6e-5,
    interstage_reheater_pressure_drop_pa=20_000.0,
    segments_per_stage=12000,
    profile_points_per_stage=12,
)


DEFAULT_STYRENE_RADIAL_REACTOR_CASE = RadialReactorCase(
    feed=DEFAULT_STYRENE_FEED,
    conditions=DEFAULT_STAGED_ADIABATIC_RADIAL_CONDITIONS,
)
