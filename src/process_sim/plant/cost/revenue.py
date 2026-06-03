"""製品収入と原料費の計算。"""

from __future__ import annotations

from process_sim.constants.physical_properties import SPECIES_PHYSICAL_PROPERTIES
from process_sim.plant.cost.common import annual_component_value_yen
from process_sim.plant.cost.constants import FEED_PRICE_YEN_PER_KG, PRODUCT_PRICE_YEN_PER_KG, SM_SALES_CAP_TON_PER_YEAR
from process_sim.plant.cost.models import CostBreakdownItem, RawMaterialCostResult, RevenueCostResult
from process_sim.plant.feed import FreshFeed, FreshFeedPolicy, HYSYS_COMPONENT_TO_REACTOR_FIELD, normalized_component_name
from process_sim.plant.models import PlantRunRecord, PlantStreamRecord


def evaluate_revenue(plant_record: PlantRunRecord) -> RevenueCostResult:
    """製品 stream から年間収入を計算する。"""
    sm_stream = get_stream(plant_record, "sm_product")
    sm_production_ton_per_year = stream_annual_ton(sm_stream)
    sm_sales_ton_per_year = min(sm_production_ton_per_year, SM_SALES_CAP_TON_PER_YEAR)
    sm = CostBreakdownItem(
        name="SM",
        yen_per_year=sm_sales_ton_per_year * 1000.0 * PRODUCT_PRICE_YEN_PER_KG["styrene"],
        duty_kw=sm_stream.total_molar_flow_kmol_h or 0.0,
        note=f"produced={sm_production_ton_per_year:.3f} ton/year, sales={sm_sales_ton_per_year:.3f} ton/year",
    )
    benzene = product_item(plant_record, "bz_product", "Benzene", "benzene", "BZ")
    toluene = product_item(plant_record, "tl_product", "Toluene", "toluene", "TL")
    return RevenueCostResult(
        sm=sm,
        benzene=benzene,
        toluene=toluene,
        total_yen_per_year=sm.yen_per_year + benzene.yen_per_year + toluene.yen_per_year,
    )


def evaluate_raw_material_cost(
    fresh_feed: FreshFeed,
    policy: FreshFeedPolicy = FreshFeedPolicy(),
) -> RawMaterialCostResult:
    """fresh EB と fresh H2O の年間原料費を計算する。"""
    fresh_eb_kmol_h = fresh_feed.hydrocarbon_kmol_h * policy.eb_mol_fraction
    fresh_eb = CostBreakdownItem(
        name="fresh EB",
        yen_per_year=annual_component_value_yen("eb", fresh_eb_kmol_h, FEED_PRICE_YEN_PER_KG["eb"]),
        duty_kw=fresh_eb_kmol_h,
    )
    fresh_h2o = CostBreakdownItem(
        name="fresh H2O",
        yen_per_year=annual_component_value_yen("steam", fresh_feed.steam_kmol_h, FEED_PRICE_YEN_PER_KG["steam"]),
        duty_kw=fresh_feed.steam_kmol_h,
    )
    return RawMaterialCostResult(
        fresh_eb=fresh_eb,
        fresh_h2o=fresh_h2o,
        total_yen_per_year=fresh_eb.yen_per_year + fresh_h2o.yen_per_year,
    )


def revenue_warnings(plant_record: PlantRunRecord) -> tuple[str, ...]:
    """製品収入に関する警告を返す。"""
    sm_production_ton_per_year = stream_annual_ton(get_stream(plant_record, "sm_product"))
    if sm_production_ton_per_year >= SM_SALES_CAP_TON_PER_YEAR:
        return ()
    return (f"SM production is below 200000 ton/year: {sm_production_ton_per_year:.3f} ton/year",)


def product_item(
    plant_record: PlantRunRecord,
    stream_name: str,
    component_name: str,
    component_id: str,
    label: str,
) -> CostBreakdownItem:
    """製品1成分の収入項目を作る。"""
    flow_kmol_h = stream_component_flow(plant_record, stream_name, component_name)
    return CostBreakdownItem(
        name=label,
        yen_per_year=annual_component_value_yen(
            component_id,
            flow_kmol_h,
            PRODUCT_PRICE_YEN_PER_KG[component_id],
        ),
        duty_kw=flow_kmol_h,
        note=f"produced={annual_ton(component_id, flow_kmol_h):.3f} ton/year",
    )


def stream_component_flow(plant_record: PlantRunRecord, stream_name: str, component_name: str) -> float:
    """PlantRunRecord から指定 stream の成分流量を読む。"""
    return stream_component_flow_from_stream(get_stream(plant_record, stream_name), component_name)


def get_stream(plant_record: PlantRunRecord, stream_name: str) -> PlantStreamRecord:
    """PlantRunRecord から指定 stream を読む。"""
    stream = plant_record.streams.get(stream_name)
    if stream is None:
        raise ValueError(f"{stream_name} stream is missing")
    return stream


def stream_component_flow_from_stream(stream: PlantStreamRecord, component_name: str) -> float:
    """PlantStreamRecord から指定成分流量を読む。"""
    value = stream.component_molar_flow_kmol_h.get(component_name)
    if value is None:
        raise ValueError(f"{stream.name} {component_name} flow is missing")
    return value


def annual_ton(component_id: str, flow_kmol_h: float) -> float:
    """kmol/h を ton/year へ変換する。"""
    return flow_kmol_h * SPECIES_PHYSICAL_PROPERTIES[component_id].molecular_weight * 8000.0 / 1000.0


def stream_annual_ton(stream: PlantStreamRecord) -> float:
    """stream 全成分の質量流量を ton/year に変換する。"""
    total_kg_per_h = 0.0
    for component_name, flow_kmol_h in stream.component_molar_flow_kmol_h.items():
        component_id = component_id_from_hysys_name(component_name)
        if component_id is None:
            continue
        total_kg_per_h += flow_kmol_h * SPECIES_PHYSICAL_PROPERTIES[component_id].molecular_weight
    return total_kg_per_h * 8000.0 / 1000.0


def component_id_from_hysys_name(component_name: str) -> str | None:
    """HYSYS 成分名を物性値 component_id へ対応付ける。"""
    field_name = HYSYS_COMPONENT_TO_REACTOR_FIELD.get(normalized_component_name(component_name))
    if field_name == "steam":
        return "steam"
    return field_name
