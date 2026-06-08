"""2基デカンター案の冷却・再加熱・損失コストを比較する。"""

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
    hysys_case,
    normalized_component_name,
    set_quantity,
    wait_for_hysys_calculation,
)


SCRIPT_DIR = Path(__file__).resolve().parent
ONE_STAGE_CASE_PATH = SCRIPT_DIR / "hysys" / "decanter1_0524v1.hsc"
TWO_STAGE_CASE_PATH = SCRIPT_DIR / "hysys" / "decanter2_0524v1.hsc"
MEDIA_DIR = SCRIPT_DIR / "media"

T1_DECANTER_LIST_C = (50.0, 55.0, 60.0, 65.0, 70.0, 75.0, 80.0)
ONE_STAGE_DECANTER_C = 15.0
T2_DECANTER_C = 15.0

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
TOWER1_PRESSURE_KPA = 10.0
YEN_PER_OKU_YEN = 1.0e8
VERBOSE = True

ONE_STAGE_STREAM_OFF_GAS = "off_gas"
ONE_STAGE_STREAM_WATER = "water_recycle"
ONE_STAGE_UNIT_COOLER = "C-1"
ONE_STAGE_UNIT_SPREADSHEET = "SPRDSHT-1"
ONE_STAGE_UNIT_VALVE = "VLV-1"

TWO_STAGE_STREAM_OFF_GAS = "off_gas"
TWO_STAGE_STREAM_WATER_1 = "water_recycle_1"
TWO_STAGE_STREAM_WATER_2 = "water_recycle_2"
TWO_STAGE_UNIT_COOLER_1 = "C-1"
TWO_STAGE_UNIT_COOLER_2 = "C-2"
TWO_STAGE_UNIT_SPREADSHEET_1 = "SPRDSHT-1"
TWO_STAGE_UNIT_SPREADSHEET_2 = "SPRDSHT-2"
TWO_STAGE_UNIT_VALVE_1 = "VLV-1"
TWO_STAGE_UNIT_VALVE_2 = "VLV-2"

DECANTER_DIAMETER_CELL_ROW = 0
DECANTER_DIAMETER_CELL_COLUMN = 1
DECANTER_HEIGHT_CELL_ROW = 0
DECANTER_HEIGHT_CELL_COLUMN = 2

DETAILED_COST_SERIES_STYLE = {
    "total": {"label": "評価関数", "color": "black", "linewidth": 2.0},
    "cooling_water": {"label": "冷却水コスト", "color": "tab:blue", "linewidth": 1.5},
    "refrigerant": {"label": "プロピレン冷媒コスト", "color": "tab:green", "linewidth": 1.5},
    "reheat": {"label": "再加熱コスト", "color": "tab:red", "linewidth": 1.5},
    "offgas_loss": {"label": "製品と原料の損失", "color": "tab:purple", "linewidth": 1.5},
    "heat_exchanger": {"label": "熱交換器コスト", "color": "tab:brown", "linewidth": 1.5},
    "decanter": {"label": "三相分離器コスト", "color": "tab:pink", "linewidth": 1.5},
}
BREAKDOWN_KEYS = ("offgas_loss", "cooling_water", "refrigerant", "reheat", "heat_exchanger", "decanter")

VALUABLE_COMPONENT_IDS = ("eb", "styrene", "benzene", "toluene")
HYSYS_COMPONENT_TO_COMPONENT_ID = {
    "methane": "methane",
    "ethylene": "ethylene",
    "styrene": "styrene",
    "styrenemonomer": "styrene",
    "ebenzene": "eb",
    "ethylbenzene": "eb",
    "eb": "eb",
    "toluene": "toluene",
    "benzene": "benzene",
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
class CostBreakdown:
    """評価関数の費目別内訳。"""

    offgas_loss_yen_per_year: float
    cooling_water_yen_per_year: float
    refrigerant_yen_per_year: float
    reheat_steam_yen_per_year: float
    heat_exchanger_annual_yen_per_year: float
    decanter_annual_yen_per_year: float

    @property
    def total_yen_per_year(self) -> float:
        """総コストを返す。"""
        return (
            self.offgas_loss_yen_per_year
            + self.cooling_water_yen_per_year
            + self.refrigerant_yen_per_year
            + self.reheat_steam_yen_per_year
            + self.heat_exchanger_annual_yen_per_year
            + self.decanter_annual_yen_per_year
        )


@dataclass(frozen=True)
class DecanterCaseResult:
    """デカンター構成1条件の評価結果。"""

    label: str
    t1_c: float | None
    valid: bool
    invalid_reason: str
    breakdown: CostBreakdown | None
    cooling_water_duty_kw: float | None
    refrigerant_duty_kw: float | None
    reheat_duty_kw: float | None
    cooler_area_m2: float | None
    decanter_volume_m3: float | None


def log(message: str) -> None:
    """進行状況を表示する。"""
    if VERBOSE:
        print(message, flush=True)


def is_valid_number(value: float | None) -> bool:
    """HYSYS sentinel を除いた有効な数値か判定する。"""
    return value is not None and math.isfinite(value) and not math.isclose(value, HYSYS_INVALID_SENTINEL)


def required_number(value: float | None, name: str) -> float:
    """必須の数値を取り出す。"""
    if not is_valid_number(value):
        raise RuntimeError(f"{name} を取得できませんでした")
    return float(value)


def cost_to_oku_yen(value: float | None) -> float:
    """円/year を億円/year に変換する。"""
    return math.nan if value is None else value / YEN_PER_OKU_YEN


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


def decanter_volume_from_spreadsheet(spreadsheet: Any, spreadsheet_name: str) -> float:
    """spreadsheet の直径と高さから円筒体積を計算する。"""
    diameter_m = required_number(
        spreadsheet_cell_value(spreadsheet, DECANTER_DIAMETER_CELL_ROW, DECANTER_DIAMETER_CELL_COLUMN),
        f"{spreadsheet_name} decanter diameter",
    )
    height_m = required_number(
        spreadsheet_cell_value(spreadsheet, DECANTER_HEIGHT_CELL_ROW, DECANTER_HEIGHT_CELL_COLUMN),
        f"{spreadsheet_name} decanter height",
    )
    return math.pi * diameter_m**2 * height_m / 4.0


def set_product_temperature(cooler: Any, temperature_c: float) -> None:
    """cooler の出口温度を設定する。"""
    set_quantity(cooler, "ProductTemperature", temperature_c, ("C", "degC"))


def set_valve_pressure_if_available(flowsheet: Any, valve_name: str) -> None:
    """存在する valve の出口圧力を設定する。"""
    try:
        valve = get_operation(flowsheet, valve_name)
    except Exception:
        return
    try:
        set_quantity(valve, "ProductPressure", TOWER1_PRESSURE_KPA, ("kPa",))
    except Exception as exc:
        log(f"[warn] {valve_name} ProductPressure を設定できませんでした: {exc}")


def read_cooler_duty_kw(cooler: Any, cooler_name: str) -> float:
    """cooler duty を読む。"""
    return required_number(get_quantity(cooler, "Duty", ("kW", "kJ/h")), f"{cooler_name} Duty")


def duty_at_product_temperature_kw(cooler: Any, cooler_name: str, simulation_case: Any, temperature_c: float) -> float:
    """cooler 出口温度を設定して duty を読む。"""
    set_product_temperature(cooler, temperature_c)
    wait_for_hysys_calculation(simulation_case)
    return read_cooler_duty_kw(cooler, cooler_name)


def positive_section_duty_kw(duty_end_kw: float, duty_start_kw: float) -> float:
    """2つの累積 duty から区間 duty の正値を返す。"""
    return abs(duty_end_kw - duty_start_kw)


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
    return {component_id: component_flow_kmol_h.get(component_id, 0.0) for component_id in VALUABLE_COMPONENT_IDS}


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


def water_reheat_duty_kw(water_streams: list[tuple[Any, str]], flowsheet: Any) -> float:
    """水相を80 ℃まで再加熱する duty を計算する。"""
    duty_kj_h = 0.0
    for stream, stream_name in water_streams:
        mass_flow_kg_h = stream_mass_flow_kg_h(stream, flowsheet, stream_name)
        temperature_c = stream_temperature_c(stream, stream_name)
        duty_kj_h += mass_flow_kg_h * WATER_CP_KJ_KG_K * max(HOT_SIDE_EVALUATION_START_C - temperature_c, 0.0)
    return duty_kj_h / 3600.0


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


def heat_exchanger_annual_cost_yen_per_year(areas_m2: list[float]) -> float:
    """熱交換器面積群から年換算費を計算する。"""
    capital_cost_yen = sum(cooler_capital_cost_yen(area_m2) for area_m2 in areas_m2 if area_m2 > 0.0)
    return capital_cost_yen * CAPITAL_COST_INSTALLATION_FACTOR / DEPRECIATION_YEARS


def decanter_annual_cost_yen_per_year(volumes_m3: list[float]) -> float:
    """デカンター体積群から年換算費を計算する。"""
    capital_cost_yen = sum(decanter_capital_cost_yen(volume_m3) for volume_m3 in volumes_m3 if volume_m3 > 0.0)
    return capital_cost_yen * CAPITAL_COST_INSTALLATION_FACTOR / DEPRECIATION_YEARS


def build_breakdown(
    flowsheet: Any,
    offgas_stream: Any,
    cooling_water_duties_kw: list[float],
    refrigerant_duty_kw: float,
    reheat_duty_kw: float,
    heat_exchanger_areas_m2: list[float],
    decanter_volumes_m3: list[float],
) -> CostBreakdown:
    """評価関数内訳を組み立てる。"""
    offgas_component_flow = valuable_component_subset(component_flows_by_id(offgas_stream, flowsheet))
    return CostBreakdown(
        offgas_loss_yen_per_year=component_loss_cost_yen_per_year(
            component_flow_kmol_h=offgas_component_flow,
            price_yen_per_kg=VALUABLE_COMPONENT_PRICE_YEN_PER_KG,
            hours_per_year=HOURS_PER_YEAR,
        ),
        cooling_water_yen_per_year=sum(
            cooling_water_cost_yen_per_year(
                duty_kw=duty_kw,
                cp_water_kj_kg_k=WATER_CP_KJ_KG_K,
                cooling_water_delta_t_k=COOLING_WATER_OUTLET_C - COOLING_WATER_INLET_C,
                cooling_water_yen_per_ton=COOLING_WATER_YEN_PER_TON,
                hours_per_year=HOURS_PER_YEAR,
            )
            for duty_kw in cooling_water_duties_kw
        ),
        refrigerant_yen_per_year=cooling_utility_cost_yen_per_year(
            duty_kw=refrigerant_duty_kw,
            refrigerant_yen_per_mj=PROPYLENE_REFRIGERANT_YEN_PER_MJ,
            hours_per_year=HOURS_PER_YEAR,
        ),
        reheat_steam_yen_per_year=steam_heating_cost_yen_per_year(
            duty_kw=reheat_duty_kw,
            steam_yen_per_mj=STEAM_YEN_PER_MJ,
            hours_per_year=HOURS_PER_YEAR,
        ),
        heat_exchanger_annual_yen_per_year=heat_exchanger_annual_cost_yen_per_year(heat_exchanger_areas_m2),
        decanter_annual_yen_per_year=decanter_annual_cost_yen_per_year(decanter_volumes_m3),
    )


def evaluate_one_stage() -> DecanterCaseResult:
    """1基案の15 ℃条件を評価する。"""
    try:
        with hysys_case(ONE_STAGE_CASE_PATH.resolve(), visible=False) as (_, simulation_case, _):
            flowsheet = get_flowsheet(simulation_case)
            cooler = get_operation(flowsheet, ONE_STAGE_UNIT_COOLER)
            spreadsheet = get_operation(flowsheet, ONE_STAGE_UNIT_SPREADSHEET)
            set_valve_pressure_if_available(flowsheet, ONE_STAGE_UNIT_VALVE)

            duty_80_kw = duty_at_product_temperature_kw(cooler, ONE_STAGE_UNIT_COOLER, simulation_case, HOT_SIDE_EVALUATION_START_C)
            duty_50_kw = duty_at_product_temperature_kw(cooler, ONE_STAGE_UNIT_COOLER, simulation_case, COOLING_WATER_PROCESS_LIMIT_C)
            duty_15_kw = duty_at_product_temperature_kw(cooler, ONE_STAGE_UNIT_COOLER, simulation_case, ONE_STAGE_DECANTER_C)
            wait_for_hysys_calculation(simulation_case)

            cooling_water_duty_kw = positive_section_duty_kw(duty_50_kw, duty_80_kw)
            refrigerant_duty_kw = positive_section_duty_kw(duty_15_kw, duty_50_kw)
            cooling_water_area_m2 = cooler_area_for_section_m2(
                duty_kw=cooling_water_duty_kw,
                hot_inlet_c=HOT_SIDE_EVALUATION_START_C,
                hot_outlet_c=COOLING_WATER_PROCESS_LIMIT_C,
                cold_inlet_c=COOLING_WATER_INLET_C,
                cold_outlet_c=COOLING_WATER_OUTLET_C,
                overall_heat_transfer_kj_m2_k_h=COOLING_WATER_U_KJ_M2_K_H,
            )
            refrigerant_area_m2 = cooler_area_for_section_m2(
                duty_kw=refrigerant_duty_kw,
                hot_inlet_c=COOLING_WATER_PROCESS_LIMIT_C,
                hot_outlet_c=ONE_STAGE_DECANTER_C,
                cold_inlet_c=REFRIGERANT_TEMPERATURE_C,
                cold_outlet_c=REFRIGERANT_TEMPERATURE_C,
                overall_heat_transfer_kj_m2_k_h=PROPYLENE_REFRIGERANT_U_KJ_M2_K_H,
            )
            water_stream = get_material_stream(flowsheet, ONE_STAGE_STREAM_WATER)
            reheat_duty_kw = water_reheat_duty_kw([(water_stream, ONE_STAGE_STREAM_WATER)], flowsheet)
            reheat_area_m2 = reheater_area_m2(
                duty_kw=reheat_duty_kw,
                water_inlet_c=stream_temperature_c(water_stream, ONE_STAGE_STREAM_WATER),
            )
            decanter_volume_m3 = decanter_volume_from_spreadsheet(spreadsheet, ONE_STAGE_UNIT_SPREADSHEET)
            offgas_stream = get_material_stream(flowsheet, ONE_STAGE_STREAM_OFF_GAS)
            breakdown = build_breakdown(
                flowsheet=flowsheet,
                offgas_stream=offgas_stream,
                cooling_water_duties_kw=[cooling_water_duty_kw],
                refrigerant_duty_kw=refrigerant_duty_kw,
                reheat_duty_kw=reheat_duty_kw,
                heat_exchanger_areas_m2=[cooling_water_area_m2, refrigerant_area_m2, reheat_area_m2],
                decanter_volumes_m3=[decanter_volume_m3],
            )
            return DecanterCaseResult(
                label="1基 15 ℃",
                t1_c=None,
                valid=True,
                invalid_reason="",
                breakdown=breakdown,
                cooling_water_duty_kw=cooling_water_duty_kw,
                refrigerant_duty_kw=refrigerant_duty_kw,
                reheat_duty_kw=reheat_duty_kw,
                cooler_area_m2=cooling_water_area_m2 + refrigerant_area_m2 + reheat_area_m2,
                decanter_volume_m3=decanter_volume_m3,
            )
    except Exception as exc:
        return DecanterCaseResult(
            label="1基 15 ℃",
            t1_c=None,
            valid=False,
            invalid_reason=str(exc),
            breakdown=None,
            cooling_water_duty_kw=None,
            refrigerant_duty_kw=None,
            reheat_duty_kw=None,
            cooler_area_m2=None,
            decanter_volume_m3=None,
        )


def evaluate_two_stage_temperature(flowsheet: Any, simulation_case: Any, t1_c: float) -> DecanterCaseResult:
    """2基案の指定 T1 条件を評価する。"""
    try:
        cooler_1 = get_operation(flowsheet, TWO_STAGE_UNIT_COOLER_1)
        cooler_2 = get_operation(flowsheet, TWO_STAGE_UNIT_COOLER_2)
        set_valve_pressure_if_available(flowsheet, TWO_STAGE_UNIT_VALVE_1)
        set_valve_pressure_if_available(flowsheet, TWO_STAGE_UNIT_VALVE_2)

        duty_c1_80_kw = duty_at_product_temperature_kw(cooler_1, TWO_STAGE_UNIT_COOLER_1, simulation_case, HOT_SIDE_EVALUATION_START_C)
        duty_c1_t1_kw = duty_at_product_temperature_kw(cooler_1, TWO_STAGE_UNIT_COOLER_1, simulation_case, t1_c)
        cw1_duty_kw = positive_section_duty_kw(duty_c1_t1_kw, duty_c1_80_kw)

        duty_c2_50_kw = duty_at_product_temperature_kw(cooler_2, TWO_STAGE_UNIT_COOLER_2, simulation_case, COOLING_WATER_PROCESS_LIMIT_C)
        duty_c2_15_kw = duty_at_product_temperature_kw(cooler_2, TWO_STAGE_UNIT_COOLER_2, simulation_case, T2_DECANTER_C)
        cw2_duty_kw = abs(duty_c2_50_kw) if t1_c > COOLING_WATER_PROCESS_LIMIT_C else 0.0
        ref_duty_kw = positive_section_duty_kw(duty_c2_15_kw, duty_c2_50_kw)
        wait_for_hysys_calculation(simulation_case)

        cw1_area_m2 = cooler_area_for_section_m2(
            duty_kw=cw1_duty_kw,
            hot_inlet_c=HOT_SIDE_EVALUATION_START_C,
            hot_outlet_c=t1_c,
            cold_inlet_c=COOLING_WATER_INLET_C,
            cold_outlet_c=COOLING_WATER_OUTLET_C,
            overall_heat_transfer_kj_m2_k_h=COOLING_WATER_U_KJ_M2_K_H,
        )
        cw2_area_m2 = cooler_area_for_section_m2(
            duty_kw=cw2_duty_kw,
            hot_inlet_c=t1_c,
            hot_outlet_c=COOLING_WATER_PROCESS_LIMIT_C,
            cold_inlet_c=COOLING_WATER_INLET_C,
            cold_outlet_c=COOLING_WATER_OUTLET_C,
            overall_heat_transfer_kj_m2_k_h=COOLING_WATER_U_KJ_M2_K_H,
        )
        ref_area_m2 = cooler_area_for_section_m2(
            duty_kw=ref_duty_kw,
            hot_inlet_c=COOLING_WATER_PROCESS_LIMIT_C,
            hot_outlet_c=T2_DECANTER_C,
            cold_inlet_c=REFRIGERANT_TEMPERATURE_C,
            cold_outlet_c=REFRIGERANT_TEMPERATURE_C,
            overall_heat_transfer_kj_m2_k_h=PROPYLENE_REFRIGERANT_U_KJ_M2_K_H,
        )
        water_1 = get_material_stream(flowsheet, TWO_STAGE_STREAM_WATER_1)
        water_2 = get_material_stream(flowsheet, TWO_STAGE_STREAM_WATER_2)
        reheat_duty_kw = water_reheat_duty_kw(
            [(water_1, TWO_STAGE_STREAM_WATER_1), (water_2, TWO_STAGE_STREAM_WATER_2)],
            flowsheet,
        )
        reheat_area_1_m2 = reheater_area_m2(
            duty_kw=water_reheat_duty_kw([(water_1, TWO_STAGE_STREAM_WATER_1)], flowsheet),
            water_inlet_c=stream_temperature_c(water_1, TWO_STAGE_STREAM_WATER_1),
        )
        reheat_area_2_m2 = reheater_area_m2(
            duty_kw=water_reheat_duty_kw([(water_2, TWO_STAGE_STREAM_WATER_2)], flowsheet),
            water_inlet_c=stream_temperature_c(water_2, TWO_STAGE_STREAM_WATER_2),
        )
        volume_1_m3 = decanter_volume_from_spreadsheet(
            get_operation(flowsheet, TWO_STAGE_UNIT_SPREADSHEET_1),
            TWO_STAGE_UNIT_SPREADSHEET_1,
        )
        volume_2_m3 = decanter_volume_from_spreadsheet(
            get_operation(flowsheet, TWO_STAGE_UNIT_SPREADSHEET_2),
            TWO_STAGE_UNIT_SPREADSHEET_2,
        )
        offgas_stream = get_material_stream(flowsheet, TWO_STAGE_STREAM_OFF_GAS)
        breakdown = build_breakdown(
            flowsheet=flowsheet,
            offgas_stream=offgas_stream,
            cooling_water_duties_kw=[cw1_duty_kw, cw2_duty_kw],
            refrigerant_duty_kw=ref_duty_kw,
            reheat_duty_kw=reheat_duty_kw,
            heat_exchanger_areas_m2=[cw1_area_m2, cw2_area_m2, ref_area_m2, reheat_area_1_m2, reheat_area_2_m2],
            decanter_volumes_m3=[volume_1_m3, volume_2_m3],
        )
        return DecanterCaseResult(
            label=f"2基 T1={t1_c:.0f} ℃",
            t1_c=t1_c,
            valid=True,
            invalid_reason="",
            breakdown=breakdown,
            cooling_water_duty_kw=cw1_duty_kw + cw2_duty_kw,
            refrigerant_duty_kw=ref_duty_kw,
            reheat_duty_kw=reheat_duty_kw,
            cooler_area_m2=cw1_area_m2 + cw2_area_m2 + ref_area_m2 + reheat_area_1_m2 + reheat_area_2_m2,
            decanter_volume_m3=volume_1_m3 + volume_2_m3,
        )
    except Exception as exc:
        return DecanterCaseResult(
            label=f"2基 T1={t1_c:.0f} ℃",
            t1_c=t1_c,
            valid=False,
            invalid_reason=str(exc),
            breakdown=None,
            cooling_water_duty_kw=None,
            refrigerant_duty_kw=None,
            reheat_duty_kw=None,
            cooler_area_m2=None,
            decanter_volume_m3=None,
        )


def evaluate_two_stage() -> list[DecanterCaseResult]:
    """2基案の T1 sweep を評価する。"""
    results: list[DecanterCaseResult] = []
    with hysys_case(TWO_STAGE_CASE_PATH.resolve(), visible=False) as (_, simulation_case, _):
        flowsheet = get_flowsheet(simulation_case)
        for t1_c in T1_DECANTER_LIST_C:
            log(f"[case] 2基 T1={t1_c:.1f} ℃")
            results.append(evaluate_two_stage_temperature(flowsheet, simulation_case, t1_c))
    return results


def configure_axes() -> None:
    """グラフの目盛と枠線を設定する。"""
    axes = plt.gca()
    axes.grid(False)
    axes.tick_params(direction="in", top=True, right=True, bottom=True, left=True)


def breakdown_values_oku(result: DecanterCaseResult) -> list[float]:
    """作図用の費目別内訳を億円/yearで返す。"""
    if result.breakdown is None:
        return [math.nan] * 6
    return [
        cost_to_oku_yen(result.breakdown.offgas_loss_yen_per_year),
        cost_to_oku_yen(result.breakdown.cooling_water_yen_per_year),
        cost_to_oku_yen(result.breakdown.refrigerant_yen_per_year),
        cost_to_oku_yen(result.breakdown.reheat_steam_yen_per_year),
        cost_to_oku_yen(result.breakdown.heat_exchanger_annual_yen_per_year),
        cost_to_oku_yen(result.breakdown.decanter_annual_yen_per_year),
    ]


def write_two_stage_cost_figure(two_stage_results: list[DecanterCaseResult]) -> None:
    """T1 に対する2基案コスト図を保存する。"""
    valid_results = [result for result in two_stage_results if result.valid and result.breakdown is not None]
    if not valid_results:
        return
    t1_values = [result.t1_c or math.nan for result in valid_results]
    plt.figure()
    configure_axes()

    plt.plot(
        t1_values,
        [cost_to_oku_yen(result.breakdown.total_yen_per_year if result.breakdown else None) for result in valid_results],
        marker="o",
        **DETAILED_COST_SERIES_STYLE["total"],
    )
    for index, key in enumerate(BREAKDOWN_KEYS):
        values = [breakdown_values_oku(result)[index] for result in valid_results]
        plt.plot(t1_values, values, marker="o", **DETAILED_COST_SERIES_STYLE[key])
    plt.xticks(list(T1_DECANTER_LIST_C))
    plt.xlabel("1基目デカンター温度 T1 [℃]")
    plt.ylabel("コスト [億円/year]")
    plt.legend(loc="upper right", bbox_to_anchor=(1.0, 0.85), fontsize=9)
    plt.tight_layout()
    plt.savefig(MEDIA_DIR / "two_stage_decanter_cost_vs_t1.png", dpi=200)
    plt.close()


def write_best_breakdown_figure(one_stage_result: DecanterCaseResult, two_stage_results: list[DecanterCaseResult]) -> None:
    """1基案と2基案最適条件の内訳棒グラフを保存する。"""
    valid_two_stage = [result for result in two_stage_results if result.valid and result.breakdown is not None]
    if not one_stage_result.valid or one_stage_result.breakdown is None or not valid_two_stage:
        return
    best_two_stage = min(valid_two_stage, key=lambda result: result.breakdown.total_yen_per_year if result.breakdown else math.inf)
    plot_results = [one_stage_result, best_two_stage]
    x_positions = [0, 1]
    bottoms = [0.0, 0.0]
    plt.figure(figsize=(7.5, 5.5))
    axes = plt.gca()
    axes.grid(False)
    axes.tick_params(direction="in", top=False, right=True, bottom=False, left=True)
    for index, key in enumerate(BREAKDOWN_KEYS):
        values = [breakdown_values_oku(result)[index] for result in plot_results]
        style = DETAILED_COST_SERIES_STYLE[key]
        plt.bar(x_positions, values, bottom=bottoms, label=style["label"], color=style["color"], alpha=0.8)
        bottoms = [bottom + value for bottom, value in zip(bottoms, values, strict=True)]
    plt.xticks(x_positions, [result.label for result in plot_results])
    plt.ylabel("コスト [億円/year]")
    plt.legend(fontsize=9)
    plt.tight_layout()
    plt.savefig(MEDIA_DIR / "decanter_best_case_cost_breakdown.png", dpi=200)
    plt.close()


def write_figures(one_stage_result: DecanterCaseResult, two_stage_results: list[DecanterCaseResult]) -> None:
    """解析結果の図を保存する。"""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    write_two_stage_cost_figure(two_stage_results)
    write_best_breakdown_figure(one_stage_result, two_stage_results)


def print_result(result: DecanterCaseResult) -> None:
    """1条件の結果を表示する。"""
    total = result.breakdown.total_yen_per_year if result.breakdown is not None else None
    print(
        f"{result.label:14s} valid={str(result.valid):5s} "
        f"J={cost_to_oku_yen(total):9.4f} "
        f"CW={cost_to_oku_yen(result.breakdown.cooling_water_yen_per_year if result.breakdown else None):8.4f} "
        f"ref={cost_to_oku_yen(result.breakdown.refrigerant_yen_per_year if result.breakdown else None):8.4f} "
        f"reheat={cost_to_oku_yen(result.breakdown.reheat_steam_yen_per_year if result.breakdown else None):8.4f} "
        f"loss={cost_to_oku_yen(result.breakdown.offgas_loss_yen_per_year if result.breakdown else None):8.4f} "
        f"equip={cost_to_oku_yen((result.breakdown.heat_exchanger_annual_yen_per_year + result.breakdown.decanter_annual_yen_per_year) if result.breakdown else None):8.4f} "
        f"reason={result.invalid_reason}"
    )


def print_summary(one_stage_result: DecanterCaseResult, two_stage_results: list[DecanterCaseResult]) -> None:
    """解析結果の要約を表示する。"""
    print("label          valid  J[億円/y]  CW       ref      reheat   loss     equip    reason")
    print_result(one_stage_result)
    for result in two_stage_results:
        print_result(result)
    valid_two_stage = [result for result in two_stage_results if result.valid and result.breakdown is not None]
    if valid_two_stage:
        best_two_stage = min(valid_two_stage, key=lambda result: result.breakdown.total_yen_per_year if result.breakdown else math.inf)
        print()
        print(f"best two-stage: {best_two_stage.label}")
        print(f"best two-stage J: {cost_to_oku_yen(best_two_stage.breakdown.total_yen_per_year if best_two_stage.breakdown else None):.4f} 億円/year")


def main() -> None:
    """2基デカンター解析を実行する。"""
    if not ONE_STAGE_CASE_PATH.exists():
        raise FileNotFoundError(ONE_STAGE_CASE_PATH)
    if not TWO_STAGE_CASE_PATH.exists():
        raise FileNotFoundError(TWO_STAGE_CASE_PATH)
    log(f"[start] one-stage case: {ONE_STAGE_CASE_PATH.resolve()}")
    one_stage_result = evaluate_one_stage()
    log(f"[start] two-stage case: {TWO_STAGE_CASE_PATH.resolve()}")
    two_stage_results = evaluate_two_stage()
    write_figures(one_stage_result, two_stage_results)
    print_summary(one_stage_result, two_stage_results)


if __name__ == "__main__":
    main()
