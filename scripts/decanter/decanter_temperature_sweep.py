"""デカンター入口温度を振って局所最適条件を確認する。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import japanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt

from process_sim.constants.physical_properties import SPECIES_PHYSICAL_PROPERTIES
from process_sim.plant.const import HOURS_PER_YEAR, HYSYS_INVALID_SENTINEL
from process_sim.plant.economics import (
    VALUABLE_COMPONENT_PRICE_YEN_PER_KG,
    component_loss_cost_yen_per_year,
    cooling_utility_cost_yen_per_year,
    cooling_water_cost_yen_per_year,
    cooler_capital_cost_yen,
    decanter_capital_cost_yen,
    heat_exchanger_area_m2,
    log_mean_temperature_difference_k,
    steam_heating_cost_yen_per_year,
)
from process_sim.separator.hysys_io import (
    component_value_map,
    get_component_molar_flows,
    get_component_names,
    get_flowsheet,
    get_material_stream,
    get_operation,
    get_quantity,
    get_vapor_fraction,
    hysys_case,
    normalized_component_name,
    set_quantity,
    wait_for_hysys_calculation,
)


SCRIPT_DIR = Path(__file__).resolve().parent
CASE_PATH = SCRIPT_DIR / "hysys" / "decanter1_0524v1.hsc"
MEDIA_DIR = SCRIPT_DIR / "media"

# T_DEC_LIST_C = tuple(float(value) for value in range(15, 66, 5))
T_DEC_LIST_C = tuple(float(value) for value in range(15, 50, 5))
DETAIL_T_DEC_LIST_C = (15.0, 75.0)
REACTOR_OUTLET_PRESSURE_KPA: float | None = None
TOWER1_PRESSURE_KPA = 10.0
MAX_TOWER1_FEED_VAPOR_FRAC = 0.05
VERBOSE = True

HOT_SIDE_EVALUATION_START_C = 80.0
COOLING_WATER_PROCESS_LIMIT_C = 50.0
COOLING_WATER_INLET_C = 30.0
COOLING_WATER_OUTLET_C = 40.0
REFRIGERANT_TEMPERATURE_C = 0.0
COOLING_WATER_U_KJ_M2_K_H = 3600.0
PROPYLENE_REFRIGERANT_U_KJ_M2_K_H = 5400.0
PROPYLENE_REFRIGERANT_YEN_PER_MJ = 0.8
COOLING_WATER_YEN_PER_TON = 10.0
STEAM_YEN_PER_MJ = 1.0
WATER_CP_KJ_KG_K = 4.184
REHEATER_U_KJ_M2_K_H = 3600.0
STEAM_TEMPERATURE_C = 130.0

DEPRECIATION_YEARS = 7.0
CAPITAL_COST_INSTALLATION_FACTOR = 2.5

STREAM_REACTOR_OUTLET = "reactor_outlet"
STREAM_SEPARATOR_FEED = "separator_feed"
STREAM_OFF_GAS = "off_gas"
STREAM_WATER_RECYCLE = "water_recycle"
STREAM_DECANTER_OIL = "decanter_outlet"
STREAM_TOWER1_FEED = "tower1_feed"

UNIT_COOLER = "C-1"
UNIT_DECANTER = "V-1"
UNIT_VALVE = "VLV-1"
UNIT_DECANTER_SPREADSHEET = "SPRDSHT-1"

DECANTER_DIAMETER_CELL_ROW = 0
DECANTER_DIAMETER_CELL_COLUMN = 1
DECANTER_HEIGHT_CELL_ROW = 0
DECANTER_HEIGHT_CELL_COLUMN = 2
YEN_PER_OKU_YEN = 1.0e8

DETAILED_COST_SERIES_STYLE = {
    "total": {"label": "評価関数", "color": "black", "linewidth": 2.0},
    "cooling_water": {"label": "冷却水コスト", "color": "tab:blue", "linewidth": 1.5},
    "refrigerant": {"label": "プロピレン冷媒コスト", "color": "tab:green", "linewidth": 1.5},
    "reheat": {"label": "再加熱コスト", "color": "tab:red", "linewidth": 1.5},
    "offgas_loss": {"label": "製品と原料の損失", "color": "tab:purple", "linewidth": 1.5},
    "heat_exchanger": {"label": "熱交換器コスト", "color": "tab:brown", "linewidth": 1.5},
    "decanter": {"label": "三相分離器コスト", "color": "tab:pink", "linewidth": 1.5},
}

VALUABLE_COMPONENT_IDS = ("eb", "styrene", "benzene", "toluene")
HYSYS_COMPONENT_TO_COMPONENT_ID = {
    "methane": "methane",
    "ethylene": "ethylene",
    "ebenzene": "eb",
    "ethylbenzene": "eb",
    "eb": "eb",
    "styrene": "styrene",
    "styrenemonomer": "styrene",
    "benzene": "benzene",
    "bz": "benzene",
    "toluene": "toluene",
    "tl": "toluene",
    "co2": "co2",
    "carbondioxide": "co2",
    "co": "co",
    "carbonmonoxide": "co",
    "h2o": "steam",
    "water": "steam",
    "steam": "steam",
    "hydrogen": "hydrogen",
    "h2": "hydrogen",
}


@dataclass(frozen=True)
class DecanterSweepResult:
    """デカンター温度 1 点の計算結果。"""

    temperature_c: float
    pressure_kpa: float
    valid: bool
    invalid_reason: str
    cooler_duty_kw: float | None
    cooler_area_m2: float | None
    decanter_diameter_m: float | None
    decanter_height_m: float | None
    decanter_volume_m3: float | None
    tower1_feed_vapor_fraction: float | None
    offgas_loss_yen_per_year: float | None
    cooling_water_cost_yen_per_year: float | None
    refrigerant_cost_yen_per_year: float | None
    reheat_steam_cost_yen_per_year: float | None
    heat_exchanger_annual_cost_yen_per_year: float | None
    decanter_annual_cost_yen_per_year: float | None
    total_cost_yen_per_year: float | None
    offgas_component_flow_kmol_h: dict[str, float]
    oil_component_flow_kmol_h: dict[str, float]
    recovery: dict[str, float]


def is_valid_number(value: float | None) -> bool:
    """HYSYS sentinel を除いた有効な数値か判定する。"""
    return value is not None and math.isfinite(value) and not math.isclose(value, HYSYS_INVALID_SENTINEL)


def required_number(value: float | None, name: str) -> float:
    """必須の数値を取り出す。"""
    if not is_valid_number(value):
        raise RuntimeError(f"{name} を取得できませんでした")
    return float(value)


def yen_per_year_to_oku_yen_per_year(value: float | None) -> float:
    """円/year を億円/year に変換する。"""
    return cost_value(value) / YEN_PER_OKU_YEN


def log(message: str) -> None:
    """進行状況を表示する。"""
    if VERBOSE:
        print(message, flush=True)


def component_flows_by_id(stream: Any, flowsheet: Any) -> dict[str, float]:
    """HYSYS stream の成分流量を component id keyed dict に変換する。"""
    component_names = get_component_names(stream, flowsheet)
    component_flows = component_value_map(component_names, get_component_molar_flows(stream))
    mapped: dict[str, float] = {}
    for hysys_name, flow_kmol_h in component_flows.items():
        component_id = HYSYS_COMPONENT_TO_COMPONENT_ID.get(normalized_component_name(hysys_name))
        if component_id is not None and is_valid_number(flow_kmol_h):
            mapped[component_id] = float(flow_kmol_h)
    return mapped


def valuable_component_subset(component_flow_kmol_h: dict[str, float]) -> dict[str, float]:
    """有価成分だけを抽出する。"""
    return {
        component_id: component_flow_kmol_h.get(component_id, 0.0)
        for component_id in VALUABLE_COMPONENT_IDS
    }


def recovery_by_component(
    reactor_component_flow_kmol_h: dict[str, float],
    oil_component_flow_kmol_h: dict[str, float],
) -> dict[str, float]:
    """反応器出口基準の油相回収率を計算する。"""
    recovery: dict[str, float] = {}
    for component_id in VALUABLE_COMPONENT_IDS:
        inlet_flow = reactor_component_flow_kmol_h.get(component_id, 0.0)
        oil_flow = oil_component_flow_kmol_h.get(component_id, 0.0)
        recovery[component_id] = oil_flow / inlet_flow if inlet_flow > 0.0 else math.nan
    return recovery


def spreadsheet_cell_value(spreadsheet: Any, row: int, column: int) -> float | None:
    """HYSYS spreadsheet cell の数値を読む。"""
    for accessor in (
        lambda: spreadsheet.Cell(row, column),
        lambda: spreadsheet.Cell(column, row),
    ):
        try:
            cell = accessor()
        except Exception:
            continue
        if isinstance(cell, (int, float)):
            return float(cell)
        for attr_name in ("CellValue", "Value"):
            try:
                value = getattr(cell, attr_name)
            except Exception:
                continue
            if isinstance(value, (int, float)):
                return float(value)
    return None


def decanter_geometry_from_spreadsheet(spreadsheet: Any) -> tuple[float, float, float]:
    """SPRDSHT-1 の直径と高さから円筒体積を計算する。"""
    diameter_m = required_number(
        spreadsheet_cell_value(
            spreadsheet,
            DECANTER_DIAMETER_CELL_ROW,
            DECANTER_DIAMETER_CELL_COLUMN,
        ),
        "SPRDSHT-1 Cell(0, 1) decanter diameter",
    )
    height_m = required_number(
        spreadsheet_cell_value(
            spreadsheet,
            DECANTER_HEIGHT_CELL_ROW,
            DECANTER_HEIGHT_CELL_COLUMN,
        ),
        "SPRDSHT-1 Cell(0, 2) decanter height",
    )
    volume_m3 = math.pi * diameter_m**2 * height_m / 4.0
    return diameter_m, height_m, volume_m3


def set_cooler_product_temperature(cooler: Any, simulation_case: Any, temperature_c: float) -> float:
    """C-1 の出口温度を設定して duty を読む。"""
    set_quantity(cooler, "ProductTemperature", temperature_c, ("C", "degC"))
    wait_for_hysys_calculation(simulation_case)
    return required_number(get_quantity(cooler, "Duty", ("kW", "kJ/h")), "C-1 Duty")


def positive_section_duty_kw(duty_end_kw: float, duty_start_kw: float) -> float:
    """2つの累積 duty から区間 duty の正値を返す。"""
    return abs(duty_end_kw - duty_start_kw)


def cooler_area_for_section_m2(
    duty_kw: float,
    hot_inlet_c: float,
    hot_outlet_c: float,
    cold_inlet_c: float,
    cold_outlet_c: float,
    overall_heat_transfer_kj_m2_k_h: float,
) -> float:
    """区間 duty から冷却器面積を計算する。"""
    if duty_kw <= 0.0 or math.isclose(duty_kw, 0.0):
        return 0.0
    delta_t_lm_k = log_mean_temperature_difference_k(
        hot_inlet_c=hot_inlet_c,
        hot_outlet_c=hot_outlet_c,
        cold_inlet_c=cold_inlet_c,
        cold_outlet_c=cold_outlet_c,
    )
    return heat_exchanger_area_m2(
        duty_kw=duty_kw,
        overall_heat_transfer_kj_m2_k_h=overall_heat_transfer_kj_m2_k_h,
        delta_t_lm_k=delta_t_lm_k,
    )


def stream_mass_flow_kg_h(stream: Any, flowsheet: Any, stream_name: str) -> float:
    """stream の質量流量を kg/h で読む。"""
    mass_flow_kg_h = get_quantity(stream, "MassFlow", ("kg/h",))
    if is_valid_number(mass_flow_kg_h):
        return float(mass_flow_kg_h)

    component_flow = component_flows_by_id(stream, flowsheet)
    mass_flow_from_components = 0.0
    for component_id, flow_kmol_h in component_flow.items():
        property_value = SPECIES_PHYSICAL_PROPERTIES.get(component_id)
        if property_value is None:
            continue
        mass_flow_from_components += flow_kmol_h * property_value.molecular_weight
    if mass_flow_from_components > 0.0:
        return mass_flow_from_components
    raise RuntimeError(f"{stream_name} MassFlow を取得できませんでした")


def stream_temperature_c(stream: Any, stream_name: str) -> float:
    """stream 温度を ℃ で読む。"""
    return required_number(get_quantity(stream, "Temperature", ("C", "degC")), f"{stream_name} Temperature")


def water_reheat_duty_kw(water_stream: Any, flowsheet: Any) -> float:
    """水相を80 ℃まで再加熱する duty を計算する。"""
    mass_flow_kg_h = stream_mass_flow_kg_h(water_stream, flowsheet, STREAM_WATER_RECYCLE)
    temperature_c = stream_temperature_c(water_stream, STREAM_WATER_RECYCLE)
    duty_kj_h = mass_flow_kg_h * WATER_CP_KJ_KG_K * max(HOT_SIDE_EVALUATION_START_C - temperature_c, 0.0)
    return duty_kj_h / 3600.0


def reheater_area_m2(duty_kw: float, water_inlet_c: float) -> float:
    """水相再加熱器の伝熱面積を計算する。"""
    if duty_kw <= 0.0 or math.isclose(duty_kw, 0.0):
        return 0.0
    if water_inlet_c >= HOT_SIDE_EVALUATION_START_C:
        return 0.0
    return cooler_area_for_section_m2(
        duty_kw=duty_kw,
        hot_inlet_c=STEAM_TEMPERATURE_C,
        hot_outlet_c=STEAM_TEMPERATURE_C,
        cold_inlet_c=water_inlet_c,
        cold_outlet_c=HOT_SIDE_EVALUATION_START_C,
        overall_heat_transfer_kj_m2_k_h=REHEATER_U_KJ_M2_K_H,
    )


def annualized_heat_exchanger_cost_yen_per_year(areas_m2: list[float]) -> float:
    """熱交換器面積群から年換算費を計算する。"""
    capital_cost_yen = sum(cooler_capital_cost_yen(area_m2) for area_m2 in areas_m2 if area_m2 > 0.0)
    return capital_cost_yen * CAPITAL_COST_INSTALLATION_FACTOR / DEPRECIATION_YEARS


def evaluate_temperature(flowsheet: Any, simulation_case: Any, temperature_c: float) -> DecanterSweepResult:
    """指定したデカンター入口温度で HYSYS を更新し、評価値を返す。"""
    reactor_outlet = get_material_stream(flowsheet, STREAM_REACTOR_OUTLET)
    off_gas = get_material_stream(flowsheet, STREAM_OFF_GAS)
    water_recycle = get_material_stream(flowsheet, STREAM_WATER_RECYCLE)
    decanter_oil = get_material_stream(flowsheet, STREAM_DECANTER_OIL)
    tower1_feed = get_material_stream(flowsheet, STREAM_TOWER1_FEED)
    cooler = get_operation(flowsheet, UNIT_COOLER)
    valve = get_operation(flowsheet, UNIT_VALVE)
    decanter_spreadsheet = get_operation(flowsheet, UNIT_DECANTER_SPREADSHEET)

    try:
        if REACTOR_OUTLET_PRESSURE_KPA is not None:
            log(
                f"[case] T_dec={temperature_c:.1f} C: "
                f"set reactor_outlet Pressure={REACTOR_OUTLET_PRESSURE_KPA:.3f} kPa"
            )
            set_quantity(reactor_outlet, "Pressure", REACTOR_OUTLET_PRESSURE_KPA, ("kPa",))
        reactor_pressure_kpa = required_number(
            get_quantity(reactor_outlet, "Pressure", ("kPa",)),
            "reactor_outlet Pressure",
        )
        log(
            f"[case] T_dec={temperature_c:.1f} C: "
            f"reactor_outlet Pressure={reactor_pressure_kpa:.3f} kPa"
        )
        log(f"[case] T_dec={temperature_c:.1f} C: set VLV-1 ProductPressure={TOWER1_PRESSURE_KPA:.3f} kPa")
        set_quantity(valve, "ProductPressure", TOWER1_PRESSURE_KPA, ("kPa",))
        log(f"[case] T_dec={temperature_c:.1f} C: calculate cooling sections")
        duty_80_kw = set_cooler_product_temperature(cooler, simulation_case, HOT_SIDE_EVALUATION_START_C)
        if temperature_c <= COOLING_WATER_PROCESS_LIMIT_C:
            duty_50_kw = set_cooler_product_temperature(cooler, simulation_case, COOLING_WATER_PROCESS_LIMIT_C)
            cooler_duty_kw = set_cooler_product_temperature(cooler, simulation_case, temperature_c)
            cooling_water_duty_kw = positive_section_duty_kw(duty_50_kw, duty_80_kw)
            refrigerant_duty_kw = positive_section_duty_kw(cooler_duty_kw, duty_50_kw)
            cooling_water_hot_outlet_c = COOLING_WATER_PROCESS_LIMIT_C
            refrigerant_hot_inlet_c = COOLING_WATER_PROCESS_LIMIT_C
        else:
            cooler_duty_kw = set_cooler_product_temperature(cooler, simulation_case, temperature_c)
            cooling_water_duty_kw = positive_section_duty_kw(cooler_duty_kw, duty_80_kw)
            refrigerant_duty_kw = 0.0
            cooling_water_hot_outlet_c = temperature_c
            refrigerant_hot_inlet_c = temperature_c
        log(f"[case] T_dec={temperature_c:.1f} C: solve final state")
        wait_for_hysys_calculation(simulation_case)

        separator_feed = get_material_stream(flowsheet, STREAM_SEPARATOR_FEED)
        separator_pressure_kpa = required_number(
            get_quantity(separator_feed, "Pressure", ("kPa",)),
            "separator_feed Pressure",
        )
        tower1_feed_vapor_fraction = required_number(
            get_vapor_fraction(tower1_feed),
            "tower1_feed VapourFraction",
        )
        log(f"[case] T_dec={temperature_c:.1f} C: read cost inputs")
        cooling_water_area_m2 = cooler_area_for_section_m2(
            duty_kw=cooling_water_duty_kw,
            hot_inlet_c=HOT_SIDE_EVALUATION_START_C,
            hot_outlet_c=cooling_water_hot_outlet_c,
            cold_inlet_c=COOLING_WATER_INLET_C,
            cold_outlet_c=COOLING_WATER_OUTLET_C,
            overall_heat_transfer_kj_m2_k_h=COOLING_WATER_U_KJ_M2_K_H,
        )
        refrigerant_area_m2 = cooler_area_for_section_m2(
            duty_kw=refrigerant_duty_kw,
            hot_inlet_c=refrigerant_hot_inlet_c,
            hot_outlet_c=temperature_c,
            cold_inlet_c=REFRIGERANT_TEMPERATURE_C,
            cold_outlet_c=REFRIGERANT_TEMPERATURE_C,
            overall_heat_transfer_kj_m2_k_h=PROPYLENE_REFRIGERANT_U_KJ_M2_K_H,
        )
        cooler_area_m2 = cooling_water_area_m2 + refrigerant_area_m2
        decanter_diameter_m, decanter_height_m, decanter_volume_m3 = decanter_geometry_from_spreadsheet(decanter_spreadsheet)
        reheat_duty_kw = water_reheat_duty_kw(water_recycle, flowsheet)
        reheat_area_m2 = reheater_area_m2(
            duty_kw=reheat_duty_kw,
            water_inlet_c=stream_temperature_c(water_recycle, STREAM_WATER_RECYCLE),
        )
        heat_exchanger_area_m2 = cooler_area_m2 + reheat_area_m2

        reactor_component_flow = valuable_component_subset(component_flows_by_id(reactor_outlet, flowsheet))
        offgas_component_flow = valuable_component_subset(component_flows_by_id(off_gas, flowsheet))
        oil_component_flow = valuable_component_subset(component_flows_by_id(decanter_oil, flowsheet))
        recovery = recovery_by_component(reactor_component_flow, oil_component_flow)

        offgas_loss_yen_per_year = component_loss_cost_yen_per_year(
            component_flow_kmol_h=offgas_component_flow,
            price_yen_per_kg=VALUABLE_COMPONENT_PRICE_YEN_PER_KG,
            hours_per_year=HOURS_PER_YEAR,
        )
        cooling_water_yen_per_year = cooling_water_cost_yen_per_year(
            duty_kw=cooling_water_duty_kw,
            cp_water_kj_kg_k=WATER_CP_KJ_KG_K,
            cooling_water_delta_t_k=COOLING_WATER_OUTLET_C - COOLING_WATER_INLET_C,
            cooling_water_yen_per_ton=COOLING_WATER_YEN_PER_TON,
            hours_per_year=HOURS_PER_YEAR,
        )
        refrigerant_yen_per_year = cooling_utility_cost_yen_per_year(
            duty_kw=refrigerant_duty_kw,
            refrigerant_yen_per_mj=PROPYLENE_REFRIGERANT_YEN_PER_MJ,
            hours_per_year=HOURS_PER_YEAR,
        )
        reheat_steam_yen_per_year = steam_heating_cost_yen_per_year(
            duty_kw=reheat_duty_kw,
            steam_yen_per_mj=STEAM_YEN_PER_MJ,
            hours_per_year=HOURS_PER_YEAR,
        )
        heat_exchanger_annual_cost_yen_per_year = annualized_heat_exchanger_cost_yen_per_year(
            [cooling_water_area_m2, refrigerant_area_m2, reheat_area_m2]
        )
        decanter_annual_cost_yen_per_year = (
            decanter_capital_cost_yen(decanter_volume_m3) * CAPITAL_COST_INSTALLATION_FACTOR / DEPRECIATION_YEARS
        )
        total_cost_yen_per_year = (
            offgas_loss_yen_per_year
            + cooling_water_yen_per_year
            + refrigerant_yen_per_year
            + reheat_steam_yen_per_year
            + heat_exchanger_annual_cost_yen_per_year
            + decanter_annual_cost_yen_per_year
        )

        valid = tower1_feed_vapor_fraction <= MAX_TOWER1_FEED_VAPOR_FRAC
        invalid_reason = "" if valid else "tower1_feed vapor fraction too high"
        log(
            f"[case] T_dec={temperature_c:.1f} C: "
            f"valid={valid}, VF={tower1_feed_vapor_fraction:.5f}, "
            f"duty={cooler_duty_kw / 1000.0:.3f} MW, "
            f"D={decanter_diameter_m:.3f} m, H={decanter_height_m:.3f} m, V={decanter_volume_m3:.3f} m3, "
            f"offgas={offgas_loss_yen_per_year / YEN_PER_OKU_YEN:.4f}, "
            f"CW={cooling_water_yen_per_year / YEN_PER_OKU_YEN:.4f}, "
            f"ref={refrigerant_yen_per_year / YEN_PER_OKU_YEN:.4f}, "
            f"reheat={reheat_steam_yen_per_year / YEN_PER_OKU_YEN:.4f}, "
            f"heat_exchanger={heat_exchanger_annual_cost_yen_per_year / YEN_PER_OKU_YEN:.4f}, "
            f"decanter={decanter_annual_cost_yen_per_year / YEN_PER_OKU_YEN:.4f}, "
            f"J={total_cost_yen_per_year / YEN_PER_OKU_YEN:.4f} 億円/year"
        )
        return DecanterSweepResult(
            temperature_c=temperature_c,
            pressure_kpa=separator_pressure_kpa,
            valid=valid,
            invalid_reason=invalid_reason,
            cooler_duty_kw=cooler_duty_kw,
            cooler_area_m2=heat_exchanger_area_m2,
            decanter_diameter_m=decanter_diameter_m,
            decanter_height_m=decanter_height_m,
            decanter_volume_m3=decanter_volume_m3,
            tower1_feed_vapor_fraction=tower1_feed_vapor_fraction,
            offgas_loss_yen_per_year=offgas_loss_yen_per_year,
            cooling_water_cost_yen_per_year=cooling_water_yen_per_year,
            refrigerant_cost_yen_per_year=refrigerant_yen_per_year,
            reheat_steam_cost_yen_per_year=reheat_steam_yen_per_year,
            heat_exchanger_annual_cost_yen_per_year=heat_exchanger_annual_cost_yen_per_year,
            decanter_annual_cost_yen_per_year=decanter_annual_cost_yen_per_year,
            total_cost_yen_per_year=total_cost_yen_per_year,
            offgas_component_flow_kmol_h=offgas_component_flow,
            oil_component_flow_kmol_h=oil_component_flow,
            recovery=recovery,
        )
    except Exception as exc:
        log(f"[case] T_dec={temperature_c:.1f} C: failed: {exc}")
        fallback_pressure_kpa = get_quantity(reactor_outlet, "Pressure", ("kPa",))
        return DecanterSweepResult(
            temperature_c=temperature_c,
            pressure_kpa=fallback_pressure_kpa if is_valid_number(fallback_pressure_kpa) else math.nan,
            valid=False,
            invalid_reason=str(exc),
            cooler_duty_kw=None,
            cooler_area_m2=None,
            decanter_diameter_m=None,
            decanter_height_m=None,
            decanter_volume_m3=None,
            tower1_feed_vapor_fraction=None,
            offgas_loss_yen_per_year=None,
            cooling_water_cost_yen_per_year=None,
            refrigerant_cost_yen_per_year=None,
            reheat_steam_cost_yen_per_year=None,
            heat_exchanger_annual_cost_yen_per_year=None,
            decanter_annual_cost_yen_per_year=None,
            total_cost_yen_per_year=None,
            offgas_component_flow_kmol_h={},
            oil_component_flow_kmol_h={},
            recovery={},
        )


def valid_results(results: list[DecanterSweepResult]) -> list[DecanterSweepResult]:
    """有効かつ総コストがある結果を返す。"""
    return [
        result
        for result in results
        if result.valid and result.total_cost_yen_per_year is not None
    ]


def cost_value(value: float | None) -> float:
    """None を plot 用 NaN に変換する。"""
    return float("nan") if value is None else value


def configure_temperature_ticks(temperatures: list[float]) -> None:
    """温度軸を 5 ℃刻みで表示する。"""
    if not temperatures:
        return
    start_c = int(min(temperatures))
    end_c = int(max(temperatures))
    plt.xticks(list(range(start_c, end_c + 1, 5)))


def write_figures(results: list[DecanterSweepResult]) -> None:
    """探索結果の図を保存する。"""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    temperatures = [result.temperature_c for result in results]

    plt.figure()
    configure_axes()
    plt.plot(
        temperatures,
        [yen_per_year_to_oku_yen_per_year(result.total_cost_yen_per_year) for result in results],
        marker="o",
        **DETAILED_COST_SERIES_STYLE["total"],
    )
    plt.plot(
        temperatures,
        [yen_per_year_to_oku_yen_per_year(result.cooling_water_cost_yen_per_year) for result in results],
        marker="o",
        **DETAILED_COST_SERIES_STYLE["cooling_water"],
    )
    plt.plot(
        temperatures,
        [yen_per_year_to_oku_yen_per_year(result.refrigerant_cost_yen_per_year) for result in results],
        marker="o",
        **DETAILED_COST_SERIES_STYLE["refrigerant"],
    )
    plt.plot(
        temperatures,
        [yen_per_year_to_oku_yen_per_year(result.reheat_steam_cost_yen_per_year) for result in results],
        marker="o",
        **DETAILED_COST_SERIES_STYLE["reheat"],
    )
    plt.plot(
        temperatures,
        [yen_per_year_to_oku_yen_per_year(result.offgas_loss_yen_per_year) for result in results],
        marker="o",
        **DETAILED_COST_SERIES_STYLE["offgas_loss"],
    )
    plt.plot(
        temperatures,
        [yen_per_year_to_oku_yen_per_year(result.heat_exchanger_annual_cost_yen_per_year) for result in results],
        marker="o",
        **DETAILED_COST_SERIES_STYLE["heat_exchanger"],
    )
    plt.plot(
        temperatures,
        [yen_per_year_to_oku_yen_per_year(result.decanter_annual_cost_yen_per_year) for result in results],
        marker="o",
        **DETAILED_COST_SERIES_STYLE["decanter"],
    )
    configure_temperature_ticks(temperatures)
    plt.xlabel("デカンター入口温度 [℃]")
    plt.ylabel("コスト [億円/year]")
    plt.legend(fontsize=9)
    plt.tight_layout()
    plt.savefig(MEDIA_DIR / "cost_vs_temperature.png", dpi=200)
    plt.close()


def configure_axes() -> None:
    """グラフの目盛と枠線を設定する。"""
    axes = plt.gca()
    axes.grid(False)
    axes.tick_params(
        direction="in",
        top=True,
        right=True,
        bottom=True,
        left=True,
    )


def print_summary(results: list[DecanterSweepResult]) -> None:
    """探索結果の要約を標準出力に出す。"""
    candidates = valid_results(results)
    best = min(candidates, key=lambda result: result.total_cost_yen_per_year or math.inf) if candidates else None
    print(
        "T_dec_C  valid  VF_tower1  duty_MW  A_hx_m2  "
        "D_dec_m  H_dec_m  V_dec_m3  offgas  CW  ref  reheat  heat_exchanger  decanter  total  reason"
    )
    for result in results:
        duty_mw = (result.cooler_duty_kw or math.nan) / 1000.0
        print(
            f"{result.temperature_c:7.1f}  {str(result.valid):5s}  "
            f"{cost_value(result.tower1_feed_vapor_fraction):9.5f}  "
            f"{duty_mw:7.3f}  "
            f"{cost_value(result.cooler_area_m2):11.3f}  "
            f"{cost_value(result.decanter_diameter_m):7.3f}  "
            f"{cost_value(result.decanter_height_m):7.3f}  "
            f"{cost_value(result.decanter_volume_m3):8.3f}  "
            f"{yen_per_year_to_oku_yen_per_year(result.offgas_loss_yen_per_year):7.4f}  "
            f"{yen_per_year_to_oku_yen_per_year(result.cooling_water_cost_yen_per_year):7.4f}  "
            f"{yen_per_year_to_oku_yen_per_year(result.refrigerant_cost_yen_per_year):7.4f}  "
            f"{yen_per_year_to_oku_yen_per_year(result.reheat_steam_cost_yen_per_year):7.4f}  "
            f"{yen_per_year_to_oku_yen_per_year(result.heat_exchanger_annual_cost_yen_per_year):7.4f}  "
            f"{yen_per_year_to_oku_yen_per_year(result.decanter_annual_cost_yen_per_year):9.4f}  "
            f"{yen_per_year_to_oku_yen_per_year(result.total_cost_yen_per_year):7.4f}  "
            f"{result.invalid_reason}"
        )
    if best is not None:
        print()
        print(f"best T_dec_C: {best.temperature_c:.1f}")
        print(f"best J: {yen_per_year_to_oku_yen_per_year(best.total_cost_yen_per_year):.4f} 億円/year")
        print(f"P_dec: {best.pressure_kpa:.3f} kPa")
        print(f"tower1_feed vapor fraction: {best.tower1_feed_vapor_fraction:.6f}")
        print(f"C-1 duty: {best.cooler_duty_kw:.3f} kW")
        print(f"heat exchanger area estimate: {best.cooler_area_m2:.3f} m2")
        print(f"decanter diameter: {best.decanter_diameter_m:.3f} m")
        print(f"decanter height: {best.decanter_height_m:.3f} m")
        print(f"decanter volume: {best.decanter_volume_m3:.3f} m3")
        print(f"offgas loss: {yen_per_year_to_oku_yen_per_year(best.offgas_loss_yen_per_year):.4f} 億円/year")
        print(f"cooling water: {yen_per_year_to_oku_yen_per_year(best.cooling_water_cost_yen_per_year):.4f} 億円/year")
        print(f"refrigerant: {yen_per_year_to_oku_yen_per_year(best.refrigerant_cost_yen_per_year):.4f} 億円/year")
        print(f"reheat steam: {yen_per_year_to_oku_yen_per_year(best.reheat_steam_cost_yen_per_year):.4f} 億円/year")
        print(f"heat exchanger annual: {yen_per_year_to_oku_yen_per_year(best.heat_exchanger_annual_cost_yen_per_year):.4f} 億円/year")
        print(f"decanter annual: {yen_per_year_to_oku_yen_per_year(best.decanter_annual_cost_yen_per_year):.4f} 億円/year")

    detail_results = [
        result
        for result in results
        if any(math.isclose(result.temperature_c, target_c) for target_c in DETAIL_T_DEC_LIST_C)
    ]
    if detail_results:
        print()
        print("selected temperature details")
        for result in detail_results:
            print(
                f"T_dec={result.temperature_c:.1f} C, "
                f"valid={result.valid}, "
                f"VF={cost_value(result.tower1_feed_vapor_fraction):.6f}, "
                f"D={cost_value(result.decanter_diameter_m):.3f} m, "
                f"H={cost_value(result.decanter_height_m):.3f} m, "
                f"V={cost_value(result.decanter_volume_m3):.3f} m3, "
                f"offgas={yen_per_year_to_oku_yen_per_year(result.offgas_loss_yen_per_year):.4f} 億円/year, "
                f"CW={yen_per_year_to_oku_yen_per_year(result.cooling_water_cost_yen_per_year):.4f} 億円/year, "
                f"ref={yen_per_year_to_oku_yen_per_year(result.refrigerant_cost_yen_per_year):.4f} 億円/year, "
                f"reheat={yen_per_year_to_oku_yen_per_year(result.reheat_steam_cost_yen_per_year):.4f} 億円/year, "
                f"heat_exchanger={yen_per_year_to_oku_yen_per_year(result.heat_exchanger_annual_cost_yen_per_year):.4f} 億円/year, "
                f"decanter={yen_per_year_to_oku_yen_per_year(result.decanter_annual_cost_yen_per_year):.4f} 億円/year, "
                f"total={yen_per_year_to_oku_yen_per_year(result.total_cost_yen_per_year):.4f} 億円/year, "
                f"reason={result.invalid_reason}"
            )


def main() -> None:
    """デカンター温度 sweep を実行する。"""
    if not CASE_PATH.exists():
        raise FileNotFoundError(CASE_PATH)
    log(f"[start] case: {CASE_PATH.resolve()}")
    log(f"[start] temperatures: {', '.join(f'{value:.1f}' for value in T_DEC_LIST_C)} C")
    if REACTOR_OUTLET_PRESSURE_KPA is None:
        log("[start] reactor_outlet pressure: use case value")
    else:
        log(f"[start] reactor_outlet pressure: set {REACTOR_OUTLET_PRESSURE_KPA:.3f} kPa")
    log(
        "[assumption] "
        f"U_CW={COOLING_WATER_U_KJ_M2_K_H:.1f}, "
        f"U_ref={PROPYLENE_REFRIGERANT_U_KJ_M2_K_H:.1f} kJ/(m2 K h), "
        f"CW={COOLING_WATER_INLET_C:.1f}->{COOLING_WATER_OUTLET_C:.1f} C, "
        f"ref={REFRIGERANT_TEMPERATURE_C:.1f} C"
    )
    log("[start] decanter volume: use SPRDSHT-1 Cell(0, 1) diameter and Cell(0, 2) height")
    with hysys_case(CASE_PATH.resolve(), visible=False) as (_, simulation_case, _):
        flowsheet = get_flowsheet(simulation_case)
        results = [
            evaluate_temperature(flowsheet, simulation_case, temperature_c)
            for temperature_c in T_DEC_LIST_C
        ]
    log("[finish] write figures")
    write_figures(results)
    print_summary(results)


if __name__ == "__main__":
    main()
