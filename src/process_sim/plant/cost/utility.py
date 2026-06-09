"""外部 utility と燃料費の計算。"""

from __future__ import annotations

from process_sim.plant.const import HOURS_PER_YEAR
from process_sim.plant.cost.common import annual_energy_value_yen, annual_mass_value_yen
from process_sim.plant.cost.constants import (
    COOLING_WATER_DELTA_T_K,
    CP_WATER_KJ_KG_K,
    FURNACE_EFFICIENCY,
    HEXANE_LHV_MJ_PER_KG,
    LHV_MJ_PER_KMOL,
    STEAM_TEMPERATURE_C,
    UTILITY_PRICE,
)
from process_sim.plant.cost.equipment import cooler_outlet_temperature_for_cost, selected_reboiler_steam_temperature_c
from process_sim.plant.cost.models import CostBreakdownItem, HeatRecoveryResult, UtilityCostResult
from process_sim.plant.feed import reactor_feed_from_plant_stream
from process_sim.plant.models import PlantRunRecord
from process_sim.reactor.core.models import ReactorResult
from process_sim.separator.equipment import Cooler, Heater, ProcessEquipment


def evaluate_utility_cost(
    plant_record: PlantRunRecord,
    equipment: ProcessEquipment,
    reactor_result: ReactorResult,
    heat_recovery: HeatRecoveryResult,
) -> UtilityCostResult:
    """外部 utility と燃料費を計算する。"""
    steam_130_duty = 0.0
    steam_160_duty = 0.0
    steam_250_duty = 0.0
    cooling_water_duty = 0.0
    propylene_duty = 0.0
    electricity_kw = sum(pump.power_kw for pump in equipment.pumps) + sum(
        compressor.power_kw for compressor in equipment.compressors
    )

    furnace_required_duty = reactor_interstage_reheat_duty_kw(reactor_result)

    for heater in equipment.heaters:
        duty = residual_heater_duty_kw(heater, heat_recovery)
        if heater.id in {"steam_inlet_heater1", "steam_inlet_heater2", "steam_inlet_heater3", "reactor_trim_heater"}:
            furnace_required_duty += duty
            continue
        steam_name = selected_heater_steam_name(heater)
        if steam_name == "steam_130c":
            steam_130_duty += duty
        elif steam_name == "steam_160c":
            steam_160_duty += duty
        else:
            steam_250_duty += duty

    for column in equipment.distillation_columns:
        steam_name = selected_reboiler_steam_name(column.bottom_temperature_c)
        if steam_name == "steam_130c":
            steam_130_duty += abs(column.reboiler_duty_kw)
        elif steam_name == "steam_160c":
            steam_160_duty += abs(column.reboiler_duty_kw)
        else:
            steam_250_duty += abs(column.reboiler_duty_kw)
        if column.top_temperature_c - 30.0 >= 10.0:
            cooling_water_duty += abs(column.condenser_duty_kw)
        else:
            propylene_duty += abs(column.condenser_duty_kw)

    for cooler in equipment.coolers:
        duty = residual_cooler_duty_kw(cooler, heat_recovery)
        if cooler_uses_cooling_water(cooler):
            cooling_water_duty += duty
        else:
            propylene_duty += duty

    offgas_fuel_heat = offgas_combustion_heat_mj_h(plant_record)
    required_fuel_heat = furnace_required_duty * 3.6 / FURNACE_EFFICIENCY
    hexane_fuel_heat = max(required_fuel_heat - offgas_fuel_heat, 0.0)
    hexane_kg_h = hexane_fuel_heat / HEXANE_LHV_MJ_PER_KG

    steam_130 = CostBreakdownItem(
        name="steam 130C",
        yen_per_year=annual_energy_value_yen(steam_130_duty, UTILITY_PRICE["steam_130c_yen_per_mj"]),
        duty_kw=steam_130_duty,
    )
    steam_160 = CostBreakdownItem(
        name="steam 160C",
        yen_per_year=annual_energy_value_yen(steam_160_duty, UTILITY_PRICE["steam_160c_yen_per_mj"]),
        duty_kw=steam_160_duty,
    )
    steam_250 = CostBreakdownItem(
        name="steam 250C",
        yen_per_year=annual_energy_value_yen(steam_250_duty, UTILITY_PRICE["steam_250c_yen_per_mj"]),
        duty_kw=steam_250_duty,
    )
    cooling_water = CostBreakdownItem(
        name="cooling water",
        yen_per_year=cooling_water_cost_yen_per_year(cooling_water_duty),
        duty_kw=cooling_water_duty,
    )
    propylene = CostBreakdownItem(
        name="propylene refrigerant",
        yen_per_year=annual_energy_value_yen(propylene_duty, UTILITY_PRICE["propylene_yen_per_mj"]),
        duty_kw=propylene_duty,
    )
    electricity = CostBreakdownItem(
        name="electricity",
        yen_per_year=electricity_kw * UTILITY_PRICE["electricity_yen_per_kwh"] * HOURS_PER_YEAR,
        duty_kw=electricity_kw,
    )
    hexane = CostBreakdownItem(
        name="hexane fuel",
        yen_per_year=annual_mass_value_yen(hexane_kg_h, UTILITY_PRICE["hexane_yen_per_kg"]),
        duty_kw=hexane_kg_h,
        note=f"heat={hexane_fuel_heat:.3f} MJ/h",
    )
    total = sum(
        item.yen_per_year
        for item in (steam_130, steam_160, steam_250, cooling_water, propylene, electricity, hexane)
    )
    return UtilityCostResult(
        steam_130c=steam_130,
        steam_160c=steam_160,
        steam_250c=steam_250,
        cooling_water=cooling_water,
        propylene_refrigerant=propylene,
        electricity=electricity,
        hexane_fuel=hexane,
        total_yen_per_year=total,
        furnace_required_duty_kw=furnace_required_duty,
        offgas_fuel_heat_mj_h=offgas_fuel_heat,
        hexane_fuel_heat_mj_h=hexane_fuel_heat,
    )


def residual_cooler_duty_kw(cooler: Cooler, heat_recovery: HeatRecoveryResult) -> float:
    """熱回収後に外部冷却へ残る duty を返す。"""
    if cooler.id == heat_recovery.hot_equipment_id:
        return heat_recovery.hot_residual_cooling_kw
    return abs(cooler.duty_kw)


def residual_heater_duty_kw(heater: Heater, heat_recovery: HeatRecoveryResult) -> float:
    """熱回収後に外部加熱へ残る duty を返す。"""
    if heater.id == heat_recovery.cold_equipment_id:
        return heat_recovery.cold_residual_heating_kw
    return abs(heater.duty_kw)


def selected_heater_steam_name(heater: Heater) -> str:
    """heater に使う steam 種類を返す。"""
    maximum_process_temperature = max(heater.inlet_temperature_c, heater.outlet_temperature_c)
    if STEAM_TEMPERATURE_C["steam_130c"] - maximum_process_temperature >= 20.0:
        return "steam_130c"
    if STEAM_TEMPERATURE_C["steam_160c"] - maximum_process_temperature >= 20.0:
        return "steam_160c"
    return "steam_250c"


def selected_reboiler_steam_name(bottom_temperature_c: float) -> str:
    """リボイラーに使う steam 種類を返す。"""
    temperature = selected_reboiler_steam_temperature_c(bottom_temperature_c)
    if temperature == 130.0:
        return "steam_130c"
    if temperature == 160.0:
        return "steam_160c"
    return "steam_250c"


def cooler_uses_cooling_water(cooler: Cooler) -> bool:
    """cooler が冷却水で成立するか判定する。"""
    return cooler_outlet_temperature_for_cost(cooler) - 30.0 >= 10.0


def cooling_water_cost_yen_per_year(duty_kw: float) -> float:
    """冷却水 duty から年間費用を計算する。"""
    cooling_water_kg_s = abs(duty_kw) / (CP_WATER_KJ_KG_K * COOLING_WATER_DELTA_T_K)
    cooling_water_ton_h = cooling_water_kg_s * 3.6
    return cooling_water_ton_h * UTILITY_PRICE["cooling_water_yen_per_ton"] * HOURS_PER_YEAR


def reactor_interstage_reheat_duty_kw(reactor_result: ReactorResult) -> float:
    """反応器段間再加熱 duty を合計する。"""
    return sum((stage.reheat_duty_mw or 0.0) * 1000.0 for stage in reactor_result.log.stage_logs)


def offgas_combustion_heat_mj_h(plant_record: PlantRunRecord) -> float:
    """オフガス H2 と CH4 の燃焼熱を計算する。"""
    offgas = reactor_feed_from_plant_stream(plant_record.streams.get("off_gas"))
    return offgas.hydrogen * LHV_MJ_PER_KMOL["hydrogen"] + offgas.methane * LHV_MJ_PER_KMOL["methane"]
