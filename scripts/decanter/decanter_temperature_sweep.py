"""デカンター入口温度を振って局所最適条件を確認する。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

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
CASE_PATH = SCRIPT_DIR / "hysys" / "decanter_0520v2.hsc"
MEDIA_DIR = SCRIPT_DIR / "media"

T_DEC_LIST_C = tuple(float(value) for value in range(15, 81, 5))
REACTOR_OUTLET_PRESSURE_KPA: float | None = None
TOWER1_PRESSURE_KPA = 10.0
MAX_TOWER1_FEED_VAPOR_FRAC = 0.05
VERBOSE = True

# 表 C.1 の「液 - ガス(凝縮)」を採用する。
COOLER_U_KJ_M2_K_H = 3600.0
COOLANT_TEMPERATURE_C = 0.0
PROPYLENE_REFRIGERANT_YEN_PER_MJ = 0.8

DECANTER_RESIDENCE_TIME_MIN = 10.0
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


def decanter_volume_from_residence_time_m3(decanter: Any) -> float:
    """液相体積流量と滞留時間からデカンター体積を推算する。"""
    oil_volume_flow_m3_h = required_number(
        get_quantity(decanter, "LiquidVolumeFlow", ("m3/h",)),
        "V-1 LiquidVolumeFlow",
    )
    water_volume_flow_m3_h = required_number(
        get_quantity(decanter, "HeavyLiquidVolumeFlow", ("m3/h",)),
        "V-1 HeavyLiquidVolumeFlow",
    )
    return (oil_volume_flow_m3_h + water_volume_flow_m3_h) * DECANTER_RESIDENCE_TIME_MIN / 60.0


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
    decanter = get_operation(flowsheet, UNIT_DECANTER)
    valve = get_operation(flowsheet, UNIT_VALVE)

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
        decanter_volume_m3 = decanter_volume_from_residence_time_m3(decanter)

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
            f"duty={cooler_duty_kw / 1000.0:.3f} MW, J={total_cost_yen_per_year / 1.0e8:.4f} oku-yen/y"
        )
        return DecanterSweepResult(
            temperature_c=temperature_c,
            pressure_kpa=separator_pressure_kpa,
            valid=valid,
            invalid_reason=invalid_reason,
            cooler_duty_kw=cooler_duty_kw,
            cooler_area_m2=cooler_area_m2,
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


def write_figures(results: list[DecanterSweepResult]) -> None:
    """探索結果の図を保存する。"""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    temperatures = [result.temperature_c for result in results]

    plt.figure()
    configure_axes()
    plt.plot(temperatures, [cost_value(result.total_cost_yen_per_year) for result in results], marker="o", label="total")
    plt.plot(temperatures, [cost_value(result.cooling_utility_cost_yen_per_year) for result in results], marker="o", label="cooling utility")
    plt.plot(temperatures, [cost_value(result.offgas_loss_yen_per_year) for result in results], marker="o", label="offgas loss")
    plt.plot(temperatures, [cost_value(result.cooler_annual_cost_yen_per_year) for result in results], marker="o", label="cooler annual")
    plt.plot(temperatures, [cost_value(result.decanter_annual_cost_yen_per_year) for result in results], marker="o", label="decanter annual")
    plt.xlabel("Decanter feed temperature [degC]")
    plt.ylabel("Cost [yen/year]")
    plt.legend()
    plt.tight_layout()
    plt.savefig(MEDIA_DIR / "cost_vs_temperature.png", dpi=200)
    plt.close()

    plt.figure()
    configure_axes()
    plt.plot(temperatures, [cost_value(result.cooler_duty_kw) / 1000.0 for result in results], marker="o")
    plt.xlabel("Decanter feed temperature [degC]")
    plt.ylabel("C-1 duty [MW]")
    plt.tight_layout()
    plt.savefig(MEDIA_DIR / "cooling_duty_vs_temperature.png", dpi=200)
    plt.close()

    plt.figure()
    configure_axes()
    plt.plot(temperatures, [cost_value(result.tower1_feed_vapor_fraction) for result in results], marker="o")
    plt.axhline(MAX_TOWER1_FEED_VAPOR_FRAC, color="red", linestyle="--")
    plt.xlabel("Decanter feed temperature [degC]")
    plt.ylabel("tower1_feed vapor fraction [-]")
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
    plt.xlabel("Decanter feed temperature [degC]")
    plt.ylabel("Offgas component flow [kmol/h]")
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
    plt.xlabel("Decanter feed temperature [degC]")
    plt.ylabel("Oil recovery [-]")
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
    print("T_dec_C  valid  VF_tower1  duty_MW  A_cooler_m2  V_dec_m3  J_oku_yen_y  reason")
    for result in results:
        total_oku_yen_y = (result.total_cost_yen_per_year or math.nan) / 1.0e8
        duty_mw = (result.cooler_duty_kw or math.nan) / 1000.0
        print(
            f"{result.temperature_c:7.1f}  {str(result.valid):5s}  "
            f"{cost_value(result.tower1_feed_vapor_fraction):9.5f}  "
            f"{duty_mw:7.3f}  "
            f"{cost_value(result.cooler_area_m2):11.3f}  "
            f"{cost_value(result.decanter_volume_m3):8.3f}  "
            f"{total_oku_yen_y:11.4f}  "
            f"{result.invalid_reason}"
        )
    if best is not None:
        print()
        print(f"best T_dec_C: {best.temperature_c:.1f}")
        print(f"best J: {(best.total_cost_yen_per_year or math.nan):.3f} yen/year")
        print(f"P_dec: {best.pressure_kpa:.3f} kPa")
        print(f"tower1_feed vapor fraction: {best.tower1_feed_vapor_fraction:.6f}")
        print(f"C-1 duty: {best.cooler_duty_kw:.3f} kW")
        print(f"cooler area estimate: {best.cooler_area_m2:.3f} m2")
        print(f"decanter volume estimate: {best.decanter_volume_m3:.3f} m3")


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
    log(f"[assumption] decanter residence time={DECANTER_RESIDENCE_TIME_MIN:.1f} min")
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
