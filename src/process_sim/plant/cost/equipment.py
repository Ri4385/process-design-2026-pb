"""全体プラントの装置費計算。"""

from __future__ import annotations

import math

from process_sim.plant.cost.common import (
    heat_exchanger_area_m2,
    log_mean_temperature_difference_k,
)
from process_sim.plant.cost.constants import (
    ANCILLARY_FACILITIES_FACTOR,
    DEPRECIATION_YEARS,
    PLANT_CAPITAL_FACTOR,
    U_KJ_M2_K_H,
)
from process_sim.plant.cost.models import CapitalCostResult, CostBreakdownItem, HeatRecoveryResult
from process_sim.reactor.core.models import ReactorResult
from process_sim.separator.equipment import Cooler, Heater, ProcessEquipment


def evaluate_capital_cost(equipment: ProcessEquipment, reactor_result: ReactorResult) -> CapitalCostResult:
    """ProcessEquipment と ReactorResult から建設費を計算する。"""
    heat_recovery = evaluate_c11_h22_heat_recovery(equipment)
    reactor = evaluate_reactor_capital(reactor_result)
    columns, column_details = evaluate_distillation_columns(equipment)
    heat_exchangers, heat_exchanger_details = evaluate_heat_exchangers(equipment, heat_recovery)
    decanters, decanter_details = evaluate_decanters(equipment)
    pumps, pump_details = evaluate_pumps(equipment)
    compressors, compressor_details = evaluate_compressors(equipment)

    base_capital_yen = (
        reactor.capital_yen
        + columns.capital_yen
        + heat_exchangers.capital_yen
        + decanters.capital_yen
        + pumps.capital_yen
        + compressors.capital_yen
    )
    ancillary_yen = base_capital_yen * ANCILLARY_FACILITIES_FACTOR
    total_plant_capital_yen = (base_capital_yen + ancillary_yen) * PLANT_CAPITAL_FACTOR
    annualized_yen_per_year = total_plant_capital_yen / DEPRECIATION_YEARS

    return CapitalCostResult(
        reactor=with_annualized_cost(reactor),
        distillation_columns=with_annualized_cost(columns),
        heat_exchangers=with_annualized_cost(heat_exchangers),
        decanters=with_annualized_cost(decanters),
        pumps=with_annualized_cost(pumps),
        compressors=with_annualized_cost(compressors),
        ancillary_facilities_capital_yen=ancillary_yen,
        total_plant_capital_yen=total_plant_capital_yen,
        annualized_equipment_yen_per_year=annualized_yen_per_year,
        heat_recovery=heat_recovery,
        equipment_details=(
            *column_details,
            *heat_exchanger_details,
            *decanter_details,
            *pump_details,
            *compressor_details,
        ),
    )


def with_annualized_cost(item: CostBreakdownItem) -> CostBreakdownItem:
    """建設費係数を配分した年換算寄与へ変換する。"""
    return item.model_copy(update={"yen_per_year": item.capital_yen * PLANT_CAPITAL_FACTOR / DEPRECIATION_YEARS})


def evaluate_c11_h22_heat_recovery(equipment: ProcessEquipment) -> HeatRecoveryResult:
    """C-11 と H-22 の熱回収器を評価する。"""
    c11 = get_cooler(equipment, "decanter_1_cooler1")
    h22 = get_heater(equipment, "steam_inlet_heater2")
    minimum_approach_c = 20.0
    available_hot_outlet_c = h22.inlet_temperature_c + minimum_approach_c
    if available_hot_outlet_c >= c11.inlet_temperature_c:
        raise ValueError("C-11 hot stream is not hot enough for H-22 heat recovery")

    c11_temperature_limited_duty_kw = abs(c11.duty_kw) * (
        (c11.inlet_temperature_c - available_hot_outlet_c)
        / (c11.inlet_temperature_c - c11.outlet_temperature_c)
    )
    recovered_duty_kw = min(abs(c11.duty_kw), abs(h22.duty_kw), c11_temperature_limited_duty_kw)
    hot_outlet_c = c11.inlet_temperature_c - (
        (c11.inlet_temperature_c - c11.outlet_temperature_c) * recovered_duty_kw / abs(c11.duty_kw)
    )
    cold_outlet_c = h22.outlet_temperature_c
    lmtd_k = log_mean_temperature_difference_k(
        hot_inlet_c=c11.inlet_temperature_c,
        hot_outlet_c=hot_outlet_c,
        cold_inlet_c=h22.inlet_temperature_c,
        cold_outlet_c=cold_outlet_c,
    )
    area_m2 = heat_exchanger_area_m2(
        duty_kw=recovered_duty_kw,
        u_kj_m2_k_h=U_KJ_M2_K_H["boiling_liquid_gas"],
        lmtd_k=lmtd_k,
    )
    capital_yen = heat_exchanger_capital_yen(area_m2=area_m2, k_factor=1.0)
    return HeatRecoveryResult(
        hot_equipment_id=c11.id,
        cold_equipment_id=h22.id,
        recovered_duty_kw=recovered_duty_kw,
        hot_residual_cooling_kw=max(abs(c11.duty_kw) - recovered_duty_kw, 0.0),
        cold_residual_heating_kw=max(abs(h22.duty_kw) - recovered_duty_kw, 0.0),
        hot_inlet_c=c11.inlet_temperature_c,
        hot_outlet_c=hot_outlet_c,
        cold_inlet_c=h22.inlet_temperature_c,
        cold_outlet_c=cold_outlet_c,
        lmtd_k=lmtd_k,
        area_m2=area_m2,
        capital_yen=capital_yen,
    )


def evaluate_reactor_capital(reactor_result: ReactorResult) -> CostBreakdownItem:
    """反応器本体の直接機器費を計算する。"""
    capital_yen = 0.0
    for stage in reactor_result.log.stage_logs:
        if stage.outer_radius_m is not None and stage.bed_height_m is not None:
            diameter_m = 2.0 * stage.outer_radius_m
            height_m = stage.bed_height_m
        elif stage.equivalent_diameter_m is not None:
            diameter_m = stage.equivalent_diameter_m
            height_m = stage.stage_length_m
        else:
            raise ValueError("reactor stage log does not include reactor dimensions")
        capital_yen += 20_000_000.0 * diameter_m**1.066 * height_m**0.82
    return CostBreakdownItem(name="reactor", capital_yen=capital_yen)


def evaluate_distillation_columns(equipment: ProcessEquipment) -> tuple[CostBreakdownItem, tuple[CostBreakdownItem, ...]]:
    """蒸留塔本体、コンデンサー、リボイラーの直接機器費を計算する。"""
    details: list[CostBreakdownItem] = []
    total = 0.0
    for column in equipment.distillation_columns:
        shell = 1_500_000.0 * column.diameter_m**1.066 * column.height_m**0.82
        condenser = heat_exchanger_capital_yen(
            area_m2=area_for_utility_exchanger(
                duty_kw=column.condenser_duty_kw,
                hot_inlet_c=column.top_temperature_c,
                hot_outlet_c=column.top_temperature_c,
                cold_inlet_c=30.0,
                cold_outlet_c=45.0,
                u_key="liquid_condensing_gas",
            ),
            k_factor=1.0,
        )
        reboiler = heat_exchanger_capital_yen(
            area_m2=area_for_constant_hot_utility(
                duty_kw=column.reboiler_duty_kw,
                hot_temperature_c=selected_reboiler_steam_temperature_c(column.bottom_temperature_c),
                cold_inlet_c=column.bottom_temperature_c,
                cold_outlet_c=column.bottom_temperature_c,
                u_key="boiling_liquid_condensing_gas",
            ),
            k_factor=2.0,
        )
        capital = shell + condenser + reboiler
        total += capital
        details.append(
            CostBreakdownItem(
                name=column.id,
                capital_yen=capital,
                duty_kw=abs(column.condenser_duty_kw) + abs(column.reboiler_duty_kw),
                note=f"shell + condenser {column.condenser_energy_name} + reboiler {column.reboiler_energy_name}",
            )
        )
    return CostBreakdownItem(name="distillation columns", capital_yen=total), tuple(details)


def evaluate_heat_exchangers(
    equipment: ProcessEquipment,
    heat_recovery: HeatRecoveryResult,
) -> tuple[CostBreakdownItem, tuple[CostBreakdownItem, ...]]:
    """heater と cooler の直接機器費を計算する。"""
    details: list[CostBreakdownItem] = [
        CostBreakdownItem(
            name="C-11 -> H-22 heat recovery",
            capital_yen=heat_recovery.capital_yen,
            duty_kw=heat_recovery.recovered_duty_kw,
            area_m2=heat_recovery.area_m2,
        )
    ]
    total = heat_recovery.capital_yen

    for cooler in equipment.coolers:
        duty_kw = residual_cooler_duty_kw(cooler, heat_recovery)
        if duty_kw <= 0.0:
            continue
        area_m2 = cooler_area_m2(cooler, duty_kw)
        capital = heat_exchanger_capital_yen(area_m2=area_m2, k_factor=1.0)
        total += capital
        details.append(
            CostBreakdownItem(
                name=cooler.id,
                capital_yen=capital,
                duty_kw=duty_kw,
                area_m2=area_m2,
                note=cooler.energy_name,
            )
        )

    for heater in equipment.heaters:
        duty_kw = residual_heater_duty_kw(heater, heat_recovery)
        if duty_kw <= 0.0:
            continue
        area_m2 = heater_area_m2(heater, duty_kw)
        capital = heat_exchanger_capital_yen(area_m2=area_m2, k_factor=1.0)
        total += capital
        details.append(
            CostBreakdownItem(
                name=heater.id,
                capital_yen=capital,
                duty_kw=duty_kw,
                area_m2=area_m2,
                note=heater.energy_name,
            )
        )
    return CostBreakdownItem(name="heat exchangers", capital_yen=total), tuple(details)


def evaluate_decanters(equipment: ProcessEquipment) -> tuple[CostBreakdownItem, tuple[CostBreakdownItem, ...]]:
    """デカンターの直接機器費を計算する。"""
    details = tuple(
        CostBreakdownItem(
            name=decanter.id,
            capital_yen=bare_module_cost_yen(
                a=decanter.volume_m3,
                k1=3.5565,
                k2=0.3776,
                k3=0.0905,
                b1=0.96,
                b2=1.21,
                fp=1.0,
                fm=1.0,
            ),
            note=f"volume={decanter.volume_m3:.3f} m3",
        )
        for decanter in equipment.decanters
    )
    return CostBreakdownItem(name="decanters", capital_yen=sum(item.capital_yen for item in details)), details


def evaluate_pumps(equipment: ProcessEquipment) -> tuple[CostBreakdownItem, tuple[CostBreakdownItem, ...]]:
    """ポンプの直接機器費を計算する。"""
    details = tuple(
        CostBreakdownItem(
            name=pump.id,
            capital_yen=bare_module_cost_yen(
                a=max(pump.power_kw, 1e-9),
                k1=3.3892,
                k2=0.0536,
                k3=0.1538,
                b1=1.89,
                b2=1.35,
                fp=1.0,
                fm=1.0,
            ),
            duty_kw=pump.power_kw,
            note=pump.energy_name,
        )
        for pump in equipment.pumps
    )
    return CostBreakdownItem(name="pumps", capital_yen=sum(item.capital_yen for item in details)), details


def evaluate_compressors(equipment: ProcessEquipment) -> tuple[CostBreakdownItem, tuple[CostBreakdownItem, ...]]:
    """コンプレッサーの直接機器費を計算する。"""
    details = tuple(
        CostBreakdownItem(
            name=compressor.id,
            capital_yen=500_000.0 * max(compressor.power_kw, 1e-9) ** 0.82,
            duty_kw=compressor.power_kw,
            note=compressor.energy_name,
        )
        for compressor in equipment.compressors
    )
    return CostBreakdownItem(name="compressors", capital_yen=sum(item.capital_yen for item in details)), details


def heat_exchanger_capital_yen(area_m2: float, k_factor: float) -> float:
    """docs/cost.md ①の熱交換器費を計算する。"""
    if area_m2 <= 0.0:
        raise ValueError("area_m2 must be positive")
    return 1_500_000.0 * area_m2**0.65 * k_factor


def bare_module_cost_yen(
    a: float,
    k1: float,
    k2: float,
    k3: float,
    b1: float,
    b2: float,
    fp: float,
    fm: float,
) -> float:
    """docs/cost.md ⑥の Bare Module Cost を計算する。"""
    if a <= 0.0:
        raise ValueError("bare module size parameter must be positive")
    log_a = math.log10(a)
    return 10.0 ** (k1 + k2 * log_a + k3 * log_a**2) * (b1 + b2 * fp * fm) * (813.0 / 397.0) * 160.0


def area_for_constant_hot_utility(
    duty_kw: float,
    hot_temperature_c: float,
    cold_inlet_c: float,
    cold_outlet_c: float,
    u_key: str,
) -> float:
    """温度一定の高温 utility を使う熱交換器面積を計算する。"""
    lmtd = log_mean_temperature_difference_k(
        hot_inlet_c=hot_temperature_c,
        hot_outlet_c=hot_temperature_c,
        cold_inlet_c=cold_inlet_c,
        cold_outlet_c=cold_outlet_c,
    )
    return heat_exchanger_area_m2(duty_kw=duty_kw, u_kj_m2_k_h=U_KJ_M2_K_H[u_key], lmtd_k=lmtd)


def area_for_utility_exchanger(
    duty_kw: float,
    hot_inlet_c: float,
    hot_outlet_c: float,
    cold_inlet_c: float,
    cold_outlet_c: float,
    u_key: str,
) -> float:
    """外部 utility 熱交換器面積を計算する。"""
    lmtd = log_mean_temperature_difference_k(
        hot_inlet_c=hot_inlet_c,
        hot_outlet_c=hot_outlet_c,
        cold_inlet_c=cold_inlet_c,
        cold_outlet_c=cold_outlet_c,
    )
    return heat_exchanger_area_m2(duty_kw=duty_kw, u_kj_m2_k_h=U_KJ_M2_K_H[u_key], lmtd_k=lmtd)


def selected_reboiler_steam_temperature_c(bottom_temperature_c: float) -> float:
    """リボイラーに使う steam 温度を決める。"""
    if 130.0 - bottom_temperature_c >= 20.0:
        return 130.0
    if 160.0 - bottom_temperature_c >= 20.0:
        return 160.0
    return 250.0


def residual_cooler_duty_kw(cooler: Cooler, heat_recovery: HeatRecoveryResult) -> float:
    """熱回収後に外部冷却器として残る duty を返す。"""
    if cooler.id == heat_recovery.hot_equipment_id:
        return heat_recovery.hot_residual_cooling_kw
    return abs(cooler.duty_kw)


def residual_heater_duty_kw(heater: Heater, heat_recovery: HeatRecoveryResult) -> float:
    """熱回収後に外部加熱器として残る duty を返す。"""
    if heater.id == heat_recovery.cold_equipment_id:
        return heat_recovery.cold_residual_heating_kw
    return abs(heater.duty_kw)


def cooler_area_m2(cooler: Cooler, duty_kw: float) -> float:
    """cooler の伝熱面積を計算する。"""
    if cooler.id == "decanter_1_cooler2":
        u_key = "liquid_condensing_gas"
    elif "product" in cooler.id:
        u_key = "liquid_liquid"
    else:
        u_key = "gas_liquid"

    hot_outlet_c = cooler_outlet_temperature_for_cost(cooler)
    if hot_outlet_c - 30.0 < 10.0:
        return area_for_utility_exchanger(
            duty_kw=duty_kw,
            hot_inlet_c=cooler.inlet_temperature_c,
            hot_outlet_c=hot_outlet_c,
            cold_inlet_c=0.0,
            cold_outlet_c=0.0,
            u_key=u_key,
        )

    return area_for_utility_exchanger(
        duty_kw=duty_kw,
        hot_inlet_c=cooler.inlet_temperature_c,
        hot_outlet_c=hot_outlet_c,
        cold_inlet_c=30.0,
        cold_outlet_c=45.0,
        u_key=u_key,
    )


def cooler_outlet_temperature_for_cost(cooler: Cooler) -> float:
    """コスト評価で使う cooler 出口温度を返す。"""
    if "product" in cooler.id:
        return 40.0
    return cooler.outlet_temperature_c


def heater_area_m2(heater: Heater, duty_kw: float) -> float:
    """heater の伝熱面積を計算する。"""
    if heater.id in {"steam_inlet_heater2", "eb_inlet_heater2"}:
        u_key = "boiling_liquid_condensing_gas"
    else:
        u_key = "liquid_condensing_gas"
    return area_for_constant_hot_utility(
        duty_kw=duty_kw,
        hot_temperature_c=selected_heater_utility_temperature_c(heater),
        cold_inlet_c=heater.inlet_temperature_c,
        cold_outlet_c=heater.outlet_temperature_c,
        u_key=u_key,
    )


def selected_heater_utility_temperature_c(heater: Heater) -> float:
    """heater に使う外部加熱源の代表温度を返す。"""
    if heater.id in {"steam_inlet_heater1", "steam_inlet_heater2", "steam_inlet_heater3", "reactor_trim_heater"}:
        return 900.0
    if 130.0 - max(heater.inlet_temperature_c, heater.outlet_temperature_c) >= 20.0:
        return 130.0
    if 160.0 - max(heater.inlet_temperature_c, heater.outlet_temperature_c) >= 20.0:
        return 160.0
    return 250.0


def get_cooler(equipment: ProcessEquipment, equipment_id: str) -> Cooler:
    """id から cooler を取得する。"""
    for cooler in equipment.coolers:
        if cooler.id == equipment_id:
            return cooler
    raise ValueError(f"cooler is missing: {equipment_id}")


def get_heater(equipment: ProcessEquipment, equipment_id: str) -> Heater:
    """id から heater を取得する。"""
    for heater in equipment.heaters:
        if heater.id == equipment_id:
            return heater
    raise ValueError(f"heater is missing: {equipment_id}")
