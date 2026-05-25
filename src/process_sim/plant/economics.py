"""Plant 経済計算の共通関数。"""

from __future__ import annotations

from dataclasses import dataclass
import math

from process_sim.constants.physical_properties import SPECIES_PHYSICAL_PROPERTIES
from process_sim.plant.const import HOURS_PER_YEAR
from process_sim.plant.feed import FreshFeed, FreshFeedPolicy
from process_sim.plant.models import PlantRunRecord
from process_sim.reactor.core.models import ReactorResult
from process_sim.reactor.core.stream import ReactorFeed


FEED_PRICE_YEN_PER_KG: dict[str, float] = {
    "eb": 198.63,
    "steam": 5.0,
}

PRODUCT_PRICE_YEN_PER_KG: dict[str, float] = {
    "styrene": 232.231,
    "benzene": 149.269,
    "toluene": 184.07,
}

VALUABLE_COMPONENT_PRICE_YEN_PER_KG: dict[str, float] = {
    "eb": FEED_PRICE_YEN_PER_KG["eb"],
    "styrene": PRODUCT_PRICE_YEN_PER_KG["styrene"],
    "benzene": PRODUCT_PRICE_YEN_PER_KG["benzene"],
    "toluene": PRODUCT_PRICE_YEN_PER_KG["toluene"],
}


@dataclass(frozen=True)
class SimpleProfitBreakdown:
    """簡易経済評価の内訳。"""

    revenue_yen_per_year: float
    feed_cost_yen_per_year: float
    reactor_annual_cost_yen_per_year: float
    objective_yen_per_year: float


@dataclass(frozen=True)
class PlantReactorEconomicBreakdown:
    """反応器費だけを装置費に入れる plant 経済収支。"""

    product_revenue_yen_per_year: float
    fresh_feed_cost_yen_per_year: float
    reactor_annual_cost_yen_per_year: float
    objective_yen_per_year: float


def radial_reactor_capital_cost_yen(result: ReactorResult) -> float:
    """radial 反応器本体の装置費を計算する。"""
    total_cost_yen = 0.0
    for stage_log in result.log.stage_logs:
        if stage_log.outer_radius_m is None or stage_log.bed_height_m is None:
            raise ValueError("radial reactor stage log must include outer_radius_m and bed_height_m")
        reactor_diameter_m = 2.0 * stage_log.outer_radius_m
        total_cost_yen += 20_000_000.0 * reactor_diameter_m**1.066 * stage_log.bed_height_m**0.82
    return total_cost_yen


def annualized_reactor_cost_yen_per_year(capital_cost_yen: float) -> float:
    """7年定額償却で反応器本体費を年換算する。"""
    return capital_cost_yen / 7.0


def simple_reactor_profit_breakdown(feed: ReactorFeed, result: ReactorResult) -> SimpleProfitBreakdown:
    """反応器出口基準の簡易利益を計算する。"""
    revenue_yen_per_year = component_value_yen_per_year(
        component_id="styrene",
        flow_kmol_h=max(result.outlet.stream.styrene - feed.styrene, 0.0),
        price_yen_per_kg=PRODUCT_PRICE_YEN_PER_KG["styrene"],
    )
    feed_cost_yen_per_year = component_value_yen_per_year(
        component_id="eb",
        flow_kmol_h=feed.eb,
        price_yen_per_kg=FEED_PRICE_YEN_PER_KG["eb"],
    ) + component_value_yen_per_year(
        component_id="steam",
        flow_kmol_h=feed.steam,
        price_yen_per_kg=FEED_PRICE_YEN_PER_KG["steam"],
    )
    reactor_annual_cost_yen_per_year = annualized_reactor_cost_yen_per_year(
        radial_reactor_capital_cost_yen(result)
    )
    objective_yen_per_year = (
        revenue_yen_per_year
        - feed_cost_yen_per_year
        - reactor_annual_cost_yen_per_year
    )
    return SimpleProfitBreakdown(
        revenue_yen_per_year=revenue_yen_per_year,
        feed_cost_yen_per_year=feed_cost_yen_per_year,
        reactor_annual_cost_yen_per_year=reactor_annual_cost_yen_per_year,
        objective_yen_per_year=objective_yen_per_year,
    )


def plant_reactor_economic_breakdown(
    plant_record: PlantRunRecord,
    steady_fresh_feed: FreshFeed,
    reactor_result: ReactorResult,
    fresh_feed_policy: FreshFeedPolicy = FreshFeedPolicy(),
) -> PlantReactorEconomicBreakdown:
    """Plant product 収入、fresh 原料費、反応器年換算費から目的関数を計算する。"""
    product_revenue_yen_per_year = (
        plant_stream_component_value_yen_per_year(
            plant_record=plant_record,
            stream_name="sm_product",
            component_name="Styrene",
            component_id="styrene",
            price_yen_per_kg=PRODUCT_PRICE_YEN_PER_KG["styrene"],
        )
        + plant_stream_component_value_yen_per_year(
            plant_record=plant_record,
            stream_name="bz_product",
            component_name="Benzene",
            component_id="benzene",
            price_yen_per_kg=PRODUCT_PRICE_YEN_PER_KG["benzene"],
        )
        + plant_stream_component_value_yen_per_year(
            plant_record=plant_record,
            stream_name="tl_product",
            component_name="Toluene",
            component_id="toluene",
            price_yen_per_kg=PRODUCT_PRICE_YEN_PER_KG["toluene"],
        )
    )
    fresh_eb_kmol_h = steady_fresh_feed.hydrocarbon_kmol_h * fresh_feed_policy.eb_mol_fraction
    fresh_feed_cost_yen_per_year = component_value_yen_per_year(
        component_id="eb",
        flow_kmol_h=fresh_eb_kmol_h,
        price_yen_per_kg=FEED_PRICE_YEN_PER_KG["eb"],
    ) + component_value_yen_per_year(
        component_id="steam",
        flow_kmol_h=steady_fresh_feed.steam_kmol_h,
        price_yen_per_kg=FEED_PRICE_YEN_PER_KG["steam"],
    )
    reactor_annual_cost_yen_per_year = annualized_reactor_cost_yen_per_year(
        radial_reactor_capital_cost_yen(reactor_result)
    )
    objective_yen_per_year = (
        product_revenue_yen_per_year
        - fresh_feed_cost_yen_per_year
        - reactor_annual_cost_yen_per_year
    )
    return PlantReactorEconomicBreakdown(
        product_revenue_yen_per_year=product_revenue_yen_per_year,
        fresh_feed_cost_yen_per_year=fresh_feed_cost_yen_per_year,
        reactor_annual_cost_yen_per_year=reactor_annual_cost_yen_per_year,
        objective_yen_per_year=objective_yen_per_year,
    )


def plant_stream_component_value_yen_per_year(
    plant_record: PlantRunRecord,
    stream_name: str,
    component_name: str,
    component_id: str,
    price_yen_per_kg: float,
) -> float:
    """Plant stream の指定成分流量から年間価値を計算する。"""
    stream = plant_record.streams.get(stream_name)
    if stream is None:
        raise ValueError(f"{stream_name} stream is missing")
    flow_kmol_h = stream.component_molar_flow_kmol_h.get(component_name)
    if flow_kmol_h is None:
        raise ValueError(f"{stream_name} {component_name} flow is missing")
    return component_value_yen_per_year(
        component_id=component_id,
        flow_kmol_h=flow_kmol_h,
        price_yen_per_kg=price_yen_per_kg,
    )


def format_plant_reactor_economic_breakdown(breakdown: PlantReactorEconomicBreakdown) -> str:
    """Plant reactor economic breakdown をログ用に整形する。"""
    return "\n".join(
        [
            "[Plant Reactor Economic Breakdown]",
            f"product revenue       : {breakdown.product_revenue_yen_per_year:.6e} yen/year",
            f"fresh feed cost       : {breakdown.fresh_feed_cost_yen_per_year:.6e} yen/year",
            f"reactor annual cost   : {breakdown.reactor_annual_cost_yen_per_year:.6e} yen/year",
            f"objective             : {breakdown.objective_yen_per_year:.6e} yen/year",
        ]
    )


def component_value_yen_per_year(component_id: str, flow_kmol_h: float, price_yen_per_kg: float) -> float:
    """成分流量と単価から年間価値を計算する。"""
    physical_property = SPECIES_PHYSICAL_PROPERTIES[component_id]
    return flow_kmol_h * physical_property.molecular_weight * price_yen_per_kg * HOURS_PER_YEAR


def cooling_utility_cost_yen_per_year(
    duty_kw: float,
    refrigerant_yen_per_mj: float,
    hours_per_year: float,
) -> float:
    """冷却 duty から年間冷却用役費を計算する。"""
    return abs(duty_kw) * 3.6 * hours_per_year * refrigerant_yen_per_mj


def cooling_water_cost_yen_per_year(
    duty_kw: float,
    cp_water_kj_kg_k: float,
    cooling_water_delta_t_k: float,
    cooling_water_yen_per_ton: float,
    hours_per_year: float,
) -> float:
    """冷却 duty から年間冷却水費を計算する。"""
    if cp_water_kj_kg_k <= 0.0:
        raise ValueError("cp_water_kj_kg_k must be positive")
    if cooling_water_delta_t_k <= 0.0:
        raise ValueError("cooling_water_delta_t_k must be positive")
    cooling_water_kg_s = abs(duty_kw) / (cp_water_kj_kg_k * cooling_water_delta_t_k)
    cooling_water_ton_h = cooling_water_kg_s * 3.6
    return cooling_water_ton_h * cooling_water_yen_per_ton * hours_per_year


def steam_heating_cost_yen_per_year(
    duty_kw: float,
    steam_yen_per_mj: float,
    hours_per_year: float,
) -> float:
    """加熱 duty から年間スチーム費を計算する。"""
    return abs(duty_kw) * 3.6 * hours_per_year * steam_yen_per_mj


def component_loss_cost_yen_per_year(
    component_flow_kmol_h: dict[str, float],
    price_yen_per_kg: dict[str, float],
    hours_per_year: float,
) -> float:
    """有価成分の流出損失額を計算する。"""
    loss_yen_per_year = 0.0
    for component_id, flow_kmol_h in component_flow_kmol_h.items():
        price_yen_per_kg_value = price_yen_per_kg.get(component_id)
        physical_property = SPECIES_PHYSICAL_PROPERTIES.get(component_id)
        if price_yen_per_kg_value is None or physical_property is None:
            continue
        loss_yen_per_year += (
            flow_kmol_h
            * physical_property.molecular_weight
            * price_yen_per_kg_value
            * hours_per_year
        )
    return loss_yen_per_year


def cooler_capital_cost_yen(area_m2: float) -> float:
    """冷却器面積から装置費を計算する。"""
    if area_m2 <= 0.0:
        raise ValueError("area_m2 must be positive")
    return 1_500_000.0 * area_m2**0.65


def decanter_capital_cost_yen(volume_m3: float) -> float:
    """デカンター体積から Bare Module Cost を計算する。"""
    if volume_m3 <= 0.0:
        raise ValueError("volume_m3 must be positive")

    k1 = 3.5565
    k2 = 0.3776
    k3 = 0.0905
    b1 = 1.49
    b2 = 1.52
    pressure_factor = 1.0
    material_factor = 1.0

    log_volume = math.log10(volume_m3)
    purchased_cost_usd = 10.0 ** (k1 + k2 * log_volume + k3 * log_volume**2)
    bare_module_factor = b1 + b2 * pressure_factor * material_factor
    return purchased_cost_usd * bare_module_factor * (800.0 / 397.0) * 160.0


def heat_exchanger_area_m2(
    duty_kw: float,
    overall_heat_transfer_kj_m2_k_h: float,
    delta_t_lm_k: float,
) -> float:
    """熱負荷、U、対数平均温度差から伝熱面積を計算する。"""
    if overall_heat_transfer_kj_m2_k_h <= 0.0:
        raise ValueError("overall_heat_transfer_kj_m2_k_h must be positive")
    if delta_t_lm_k <= 0.0:
        raise ValueError("delta_t_lm_k must be positive")
    return abs(duty_kw) * 3600.0 / (overall_heat_transfer_kj_m2_k_h * delta_t_lm_k)


def log_mean_temperature_difference_k(
    hot_inlet_c: float,
    hot_outlet_c: float,
    cold_inlet_c: float,
    cold_outlet_c: float,
) -> float:
    """対数平均温度差を計算する。"""
    delta_t_1 = hot_inlet_c - cold_outlet_c
    delta_t_2 = hot_outlet_c - cold_inlet_c
    if delta_t_1 <= 0.0 or delta_t_2 <= 0.0:
        raise ValueError("temperature differences must be positive")
    if math.isclose(delta_t_1, delta_t_2):
        return delta_t_1
    return (delta_t_1 - delta_t_2) / math.log(delta_t_1 / delta_t_2)
