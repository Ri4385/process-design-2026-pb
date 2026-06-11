"""Cost 評価用の default plant case。"""

from __future__ import annotations

from process_sim.plant.cases.models import DefaultCase, SeparatorCondition
from process_sim.reactor.cases.styrene_default import DEFAULT_STYRENE_FEED
from process_sim.reactor.cases.styrene_radial_default import RadialReactorCase
from process_sim.reactor.core.models import RadialReactorRunConditions

# rank	trial_number	annual_profit_yen_per_year	stage_1_temperature_c	stage_2_temperature_c	inlet_pressure_kpa_abs	steam_to_eb_ratio	stage_1_bed_thickness_m	stage_2_bed_thickness_m	decanter_1_temperature_c	sm_column_reflux_ratio	eb_conversion	styrene_selectivity	sm_product_kmol_h	fresh_eb_kmol_h	fresh_h2o_kmol_h	eb_recycle_kmol_h	h2o_recycle_kmol_h	utility_yen_per_year	annualized_equipment_yen_per_year
# 1	251	1.42275e+09	  614.363	630.17	91.6012	5	0.989302	0.988711	55	6.312	0.627386	0.944252	240.054	259.802	13.7155	149.105	2017.86	1.34786e+09	1.44775e+09
DEFAULT_STEAM_TO_EB_RATIO = 5.0
DEFAULT_DECANTER_1_TEMPERATURE_C = 55.0
DEFAULT_SM_COLUMN_REFLUX_RATIO = 6.312


DEFAULT_RADIAL_REACTOR_CONDITIONS = RadialReactorRunConditions(
    inlet_pressure_pa=91_601.2,
    stage_inlet_temperatures_k=(273.15 + 614.363, 273.15 + 630.17),
    inlet_superficial_velocity_m_per_s=2.0,
    center_channel_radius_m=1.0,
    bed_height_m=6.0,
    # bed_thicknesses_m=(0.989302, 0.988711),
    bed_thicknesses_m=(1.0, 1.0),
    pellet_diameter_m=0.003,
    bed_void_fraction=0.4312,
    catalyst_bulk_density_kg_m3=1422.0,
    ergun_a=1.75,
    ergun_b=150.0,
    gas_viscosity_pa_s=2.6e-5,
    interstage_reheater_pressure_drop_pa=20_000.0,
    segments_per_stage=50000,
    profile_points_per_stage=12,
    min_outlet_pressure_kpa_abs=60.0,
    min_bed_outlet_velocity_m_per_s=1.0,
)

DEFAULT_RADIAL_REACTOR_CASE = RadialReactorCase(
    feed=DEFAULT_STYRENE_FEED,
    conditions=DEFAULT_RADIAL_REACTOR_CONDITIONS,
)

DEFAULT_CASE = DefaultCase(
    steam_to_eb_ratio=DEFAULT_STEAM_TO_EB_RATIO,
    reactor=DEFAULT_RADIAL_REACTOR_CASE,
    separator=SeparatorCondition(
        decanter_1_temperature_c=DEFAULT_DECANTER_1_TEMPERATURE_C,
        sm_column_reflux_ratio=DEFAULT_SM_COLUMN_REFLUX_RATIO,
    ),
)
