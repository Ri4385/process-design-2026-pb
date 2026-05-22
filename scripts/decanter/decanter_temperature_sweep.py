"""デカンター入口温度を振って局所最適条件を確認する。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import japanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt

from process_sim.plant.const import HOURS_PER_YEAR, HYSYS_INVALID_SENTINEL
from process_sim.plant.economics import (
    VALUABLE_COMPONENT_PRICE_YEN_PER_KG,
    component_loss_cost_yen_per_year,
    cooling_utility_cost_yen_per_year,
    cooler_capital_cost_yen,
    decanter_capital_cost_yen,
    heat_exchanger_area_m2,
    log_mean_temperature_difference_k,
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
CASE_PATH = SCRIPT_DIR / "hysys" / "decanter_0521v1.hsc"
MEDIA_DIR = SCRIPT_DIR / "media"

T_DEC_LIST_C = tuple(float(value) for value in range(15, 79, 5))
DETAIL_T_DEC_LIST_C = (15.0, 75.0)
REACTOR_OUTLET_PRESSURE_KPA: float | None = None
TOWER1_PRESSURE_KPA = 10.0
MAX_TOWER1_FEED_VAPOR_FRAC = 0.05
VERBOSE = True

# 表 C.1 の「液 - ガス(凝縮)」を採用する。
COOLER_U_KJ_M2_K_H = 3600.0
COOLANT_TEMPERATURE_C = 0.0
PROPYLENE_REFRIGERANT_YEN_PER_MJ = 0.8

DEPRECIATION_YEARS = 7.0

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

VALUABLE_COMPONENT_IDS = ("eb", "styrene", "benzene", "toluene")
HYSYS_COMPONENT_TO_COMPONENT_ID = {
    "ebenzene": "eb",
    "ethylbenzene": "eb",
    "eb": "eb",
    "styrene": "styrene",
    "styrenemonomer": "styrene",
    "benzene": "benzene",
    "bz": "benzene",
    "toluene": "toluene",
    "tl": "toluene",
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
    cooling_utility_cost_yen_per_year: float | None
    cooler_annual_cost_yen_per_year: float | None
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


def cooler_area_from_lmtd_m2(cooler: Any) -> float:
    """C-1 の duty と LMTD 仮定から冷却器面積を推算する。"""
    duty_kw = required_number(get_quantity(cooler, "Duty", ("kW", "kJ/h")), "C-1 Duty")
    hot_inlet_c = required_number(get_quantity(cooler, "FeedTemperature", ("C", "degC")), "C-1 FeedTemperature")
    hot_outlet_c = required_number(get_quantity(cooler, "ProductTemperature", ("C", "degC")), "C-1 ProductTemperature")
    delta_t_lm_k = log_mean_temperature_difference_k(
        hot_inlet_c=hot_inlet_c,
        hot_outlet_c=hot_outlet_c,
        cold_inlet_c=COOLANT_TEMPERATURE_C,
        cold_outlet_c=COOLANT_TEMPERATURE_C,
    )
    return heat_exchanger_area_m2(
        duty_kw=duty_kw,
        overall_heat_transfer_kj_m2_k_h=COOLER_U_KJ_M2_K_H,
        delta_t_lm_k=delta_t_lm_k,
    )


def evaluate_temperature(flowsheet: Any, simulation_case: Any, temperature_c: float) -> DecanterSweepResult:
    """指定したデカンター入口温度で HYSYS を更新し、評価値を返す。"""
    reactor_outlet = get_material_stream(flowsheet, STREAM_REACTOR_OUTLET)
    off_gas = get_material_stream(flowsheet, STREAM_OFF_GAS)
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
        log(f"[case] T_dec={temperature_c:.1f} C: set C-1 ProductTemperature")
        set_quantity(cooler, "ProductTemperature", temperature_c, ("C", "degC"))
        log(f"[case] T_dec={temperature_c:.1f} C: set VLV-1 ProductPressure={TOWER1_PRESSURE_KPA:.3f} kPa")
        set_quantity(valve, "ProductPressure", TOWER1_PRESSURE_KPA, ("kPa",))
        log(f"[case] T_dec={temperature_c:.1f} C: solve")
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
        cooler_duty_kw = required_number(get_quantity(cooler, "Duty", ("kW", "kJ/h")), "C-1 Duty")
        cooler_area_m2 = cooler_area_from_lmtd_m2(cooler)
        decanter_diameter_m, decanter_height_m, decanter_volume_m3 = decanter_geometry_from_spreadsheet(decanter_spreadsheet)

        reactor_component_flow = valuable_component_subset(component_flows_by_id(reactor_outlet, flowsheet))
        offgas_component_flow = valuable_component_subset(component_flows_by_id(off_gas, flowsheet))
        oil_component_flow = valuable_component_subset(component_flows_by_id(decanter_oil, flowsheet))
        recovery = recovery_by_component(reactor_component_flow, oil_component_flow)

        offgas_loss_yen_per_year = component_loss_cost_yen_per_year(
            component_flow_kmol_h=offgas_component_flow,
            price_yen_per_kg=VALUABLE_COMPONENT_PRICE_YEN_PER_KG,
            hours_per_year=HOURS_PER_YEAR,
        )
        cooling_utility_yen_per_year = cooling_utility_cost_yen_per_year(
            duty_kw=cooler_duty_kw,
            refrigerant_yen_per_mj=PROPYLENE_REFRIGERANT_YEN_PER_MJ,
            hours_per_year=HOURS_PER_YEAR,
        )
        cooler_annual_cost_yen_per_year = cooler_capital_cost_yen(cooler_area_m2) / DEPRECIATION_YEARS
        decanter_annual_cost_yen_per_year = decanter_capital_cost_yen(decanter_volume_m3) / DEPRECIATION_YEARS
        total_cost_yen_per_year = (
            offgas_loss_yen_per_year
            + cooling_utility_yen_per_year
            + cooler_annual_cost_yen_per_year
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
            f"cooling={cooling_utility_yen_per_year / YEN_PER_OKU_YEN:.4f}, "
            f"cooler={cooler_annual_cost_yen_per_year / YEN_PER_OKU_YEN:.4f}, "
            f"decanter={decanter_annual_cost_yen_per_year / YEN_PER_OKU_YEN:.4f}, "
            f"J={total_cost_yen_per_year / YEN_PER_OKU_YEN:.4f} 億円/year"
        )
        return DecanterSweepResult(
            temperature_c=temperature_c,
            pressure_kpa=separator_pressure_kpa,
            valid=valid,
            invalid_reason=invalid_reason,
            cooler_duty_kw=cooler_duty_kw,
            cooler_area_m2=cooler_area_m2,
            decanter_diameter_m=decanter_diameter_m,
            decanter_height_m=decanter_height_m,
            decanter_volume_m3=decanter_volume_m3,
            tower1_feed_vapor_fraction=tower1_feed_vapor_fraction,
            offgas_loss_yen_per_year=offgas_loss_yen_per_year,
            cooling_utility_cost_yen_per_year=cooling_utility_yen_per_year,
            cooler_annual_cost_yen_per_year=cooler_annual_cost_yen_per_year,
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
            cooling_utility_cost_yen_per_year=None,
            cooler_annual_cost_yen_per_year=None,
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
    plt.plot(temperatures, [yen_per_year_to_oku_yen_per_year(result.total_cost_yen_per_year) for result in results], marker="o", label="合計")
    plt.plot(
        temperatures,
        [yen_per_year_to_oku_yen_per_year(result.cooling_utility_cost_yen_per_year) for result in results],
        marker="o",
        label="冷却用役",
    )
    plt.plot(
        temperatures,
        [yen_per_year_to_oku_yen_per_year(result.offgas_loss_yen_per_year) for result in results],
        marker="o",
        label="オフガス損失",
    )
    plt.plot(
        temperatures,
        [yen_per_year_to_oku_yen_per_year(result.cooler_annual_cost_yen_per_year) for result in results],
        marker="o",
        label="冷却器年換算",
    )
    plt.plot(
        temperatures,
        [yen_per_year_to_oku_yen_per_year(result.decanter_annual_cost_yen_per_year) for result in results],
        marker="o",
        label="デカンター年換算",
    )
    configure_temperature_ticks(temperatures)
    plt.xlabel("デカンター入口温度 [℃]")
    plt.ylabel("コスト [億円/year]")
    plt.legend()
    plt.tight_layout()
    plt.savefig(MEDIA_DIR / "cost_vs_temperature.png", dpi=200)
    plt.close()

    plt.figure()
    configure_axes()
    plt.plot(temperatures, [cost_value(result.cooler_duty_kw) / 1000.0 for result in results], marker="o")
    configure_temperature_ticks(temperatures)
    plt.xlabel("デカンター入口温度 [℃]")
    plt.ylabel("C-1 duty [MW]")
    plt.tight_layout()
    plt.savefig(MEDIA_DIR / "cooling_duty_vs_temperature.png", dpi=200)
    plt.close()

    plt.figure()
    configure_axes()
    plt.plot(temperatures, [cost_value(result.tower1_feed_vapor_fraction) for result in results], marker="o")
    plt.axhline(MAX_TOWER1_FEED_VAPOR_FRAC, color="red", linestyle="--")
    configure_temperature_ticks(temperatures)
    plt.xlabel("デカンター入口温度 [℃]")
    plt.ylabel("tower1_feed ベーパー率 [-]")
    plt.tight_layout()
    plt.savefig(MEDIA_DIR / "tower1_vapor_fraction_vs_temperature.png", dpi=200)
    plt.close()

    plt.figure()
    configure_axes()
    for component_id in VALUABLE_COMPONENT_IDS:
        plt.plot(
            temperatures,
            [result.offgas_component_flow_kmol_h.get(component_id, math.nan) for result in results],
            marker="o",
            label=component_id,
        )
    configure_temperature_ticks(temperatures)
    plt.xlabel("デカンター入口温度 [℃]")
    plt.ylabel("オフガス成分流量 [kmol/h]")
    plt.legend()
    plt.tight_layout()
    plt.savefig(MEDIA_DIR / "offgas_components_vs_temperature.png", dpi=200)
    plt.close()

    plt.figure()
    configure_axes()
    for component_id in VALUABLE_COMPONENT_IDS:
        plt.plot(
            temperatures,
            [result.recovery.get(component_id, math.nan) for result in results],
            marker="o",
            label=component_id,
        )
    configure_temperature_ticks(temperatures)
    plt.xlabel("デカンター入口温度 [℃]")
    plt.ylabel("油相回収率 [-]")
    plt.legend()
    plt.tight_layout()
    plt.savefig(MEDIA_DIR / "recovery_vs_temperature.png", dpi=200)
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
        "T_dec_C  valid  VF_tower1  duty_MW  A_cooler_m2  "
        "D_dec_m  H_dec_m  V_dec_m3  offgas  cooling  cooler  decanter  total  reason"
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
            f"{yen_per_year_to_oku_yen_per_year(result.cooling_utility_cost_yen_per_year):7.4f}  "
            f"{yen_per_year_to_oku_yen_per_year(result.cooler_annual_cost_yen_per_year):7.4f}  "
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
        print(f"cooler area estimate: {best.cooler_area_m2:.3f} m2")
        print(f"decanter diameter: {best.decanter_diameter_m:.3f} m")
        print(f"decanter height: {best.decanter_height_m:.3f} m")
        print(f"decanter volume: {best.decanter_volume_m3:.3f} m3")
        print(f"offgas loss: {yen_per_year_to_oku_yen_per_year(best.offgas_loss_yen_per_year):.4f} 億円/year")
        print(f"cooling utility: {yen_per_year_to_oku_yen_per_year(best.cooling_utility_cost_yen_per_year):.4f} 億円/year")
        print(f"cooler annual: {yen_per_year_to_oku_yen_per_year(best.cooler_annual_cost_yen_per_year):.4f} 億円/year")
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
                f"cooling={yen_per_year_to_oku_yen_per_year(result.cooling_utility_cost_yen_per_year):.4f} 億円/year, "
                f"cooler={yen_per_year_to_oku_yen_per_year(result.cooler_annual_cost_yen_per_year):.4f} 億円/year, "
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
    log(f"[assumption] U={COOLER_U_KJ_M2_K_H:.1f} kJ/(m2 K h), coolant T={COOLANT_TEMPERATURE_C:.1f} C")
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
