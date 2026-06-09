"""全体プラントコスト評価ログの整形。"""

from __future__ import annotations

from process_sim.plant.cost.common import yen_to_oku_yen
from process_sim.plant.cost.constants import (
    ANCILLARY_FACILITIES_FACTOR,
    DEPRECIATION_YEARS,
    PLANT_CAPITAL_FACTOR,
)
from process_sim.plant.cost.models import (
    CapitalCostResult,
    CostBreakdownItem,
    ExternalUtilityLoad,
    TQStream,
    WholePlantCostResult,
)


def format_whole_plant_cost_report(result: WholePlantCostResult) -> str:
    """全体プラントコスト評価を Summary と Detail に整形する。"""
    return "\n".join(
        [
            format_whole_plant_cost_summary(result),
            "",
            format_whole_plant_cost_detail(result),
        ]
    )


def format_whole_plant_cost_summary(result: WholePlantCostResult) -> str:
    """全体プラントコスト評価の Summary を整形する。"""
    capital = result.capital
    ancillary_annual = capital.ancillary_facilities_capital_yen * PLANT_CAPITAL_FACTOR / DEPRECIATION_YEARS
    return "\n".join(
        [
            "[Whole Plant Cost Summary]",
            "unit: 億円/year",
            "",
            "revenue",
            format_money_row("SM", result.revenue.sm.yen_per_year, result.revenue.sm.note),
            format_money_row("BZ", result.revenue.benzene.yen_per_year, result.revenue.benzene.note),
            format_money_row("TL", result.revenue.toluene.yen_per_year, result.revenue.toluene.note),
            format_money_row("total", result.revenue.total_yen_per_year),
            "",
            "raw material",
            format_money_row("fresh EB", result.raw_material.fresh_eb.yen_per_year),
            format_money_row("fresh H2O", result.raw_material.fresh_h2o.yen_per_year),
            format_money_row("total", result.raw_material.total_yen_per_year),
            "",
            "capital",
            format_money_row("direct equipment", direct_capital(capital), unit="億円"),
            format_money_row("ancillary facilities", capital.ancillary_facilities_capital_yen, unit="億円"),
            f"  {'plant capital factor':<22} {'x2.5':>10}",
            format_money_row("total plant capital", capital.total_plant_capital_yen, unit="億円"),
            "",
            "annualized equipment",
            format_money_row("reactor", capital.reactor.yen_per_year),
            format_money_row("distillation columns", capital.distillation_columns.yen_per_year),
            format_money_row("heat exchangers", capital.heat_exchangers.yen_per_year),
            format_money_row("decanters", capital.decanters.yen_per_year),
            format_money_row("pumps", capital.pumps.yen_per_year),
            format_money_row("compressors", capital.compressors.yen_per_year),
            format_money_row("ancillary facilities", ancillary_annual),
            format_money_row("total", capital.annualized_equipment_yen_per_year),
            "",
            "utility",
            format_money_row("steam 130C", result.utility.steam_130c.yen_per_year),
            format_money_row("steam 160C", result.utility.steam_160c.yen_per_year),
            format_money_row("steam 250C", result.utility.steam_250c.yen_per_year),
            format_money_row("cooling water", result.utility.cooling_water.yen_per_year),
            format_money_row("propylene ref", result.utility.propylene_refrigerant.yen_per_year),
            format_money_row("electricity", result.utility.electricity.yen_per_year),
            format_money_row("hexane fuel", result.utility.hexane_fuel.yen_per_year),
            format_money_row("total", result.utility.total_yen_per_year),
            "",
            "fixed operating cost",
            format_money_row("labor", result.fixed_operating.labor.yen_per_year),
            format_money_row("maintenance", result.fixed_operating.maintenance.yen_per_year),
            format_money_row("total", result.fixed_operating.total_yen_per_year),
            "",
            "profit",
            format_money_row("annual profit", result.annual_profit_yen_per_year),
        ]
    )


def format_whole_plant_cost_detail(result: WholePlantCostResult) -> str:
    """全体プラントコスト評価の Detail を整形する。"""
    heat_recovery = result.capital.heat_recovery
    lines = [
        "[Whole Plant Cost Detail]",
        "",
        "[Heat Recovery]",
        (
            f"{heat_recovery.hot_equipment_id} -> {heat_recovery.cold_equipment_id}: "
            f"recovered={heat_recovery.recovered_duty_kw:.3f} kW, "
            f"hot residual={heat_recovery.hot_residual_cooling_kw:.3f} kW, "
            f"cold residual={heat_recovery.cold_residual_heating_kw:.3f} kW"
        ),
        (
            f"temperature: hot {heat_recovery.hot_inlet_c:.3f}->{heat_recovery.hot_outlet_c:.3f} C, "
            f"cold {heat_recovery.cold_inlet_c:.3f}->{heat_recovery.cold_outlet_c:.3f} C"
        ),
        (
            f"LMTD={heat_recovery.lmtd_k:.3f} K, "
            f"area={heat_recovery.area_m2:.3f} m2, "
            f"capital={yen_to_oku_yen(heat_recovery.capital_yen):.6f} 億円"
        ),
        "",
        format_tq_stream_table("[T-Q Streams: no heat recovery]", result.tq_streams_no_heat_recovery),
        "",
        format_tq_stream_table("[T-Q Streams: with heat recovery]", result.tq_streams_with_heat_recovery),
        "",
        format_external_utility_load_table(
            "[External Utility Loads: with heat recovery]",
            result.external_utility_loads_with_heat_recovery,
        ),
        "",
        format_external_utility_summary_table(
            "[External Utility Summary: with heat recovery]",
            result.external_utility_loads_with_heat_recovery,
        ),
        "",
        "[Equipment]",
        f"{'name':<32} {'duty[kW]':>12} {'area[m2]':>12} {'capital[億円]':>14} note",
    ]
    for item in result.capital.equipment_details:
        lines.append(format_equipment_detail_row(item))

    lines.extend(
        [
            "",
            "[Construction]",
            (
                f"base equipment = {yen_to_oku_yen(direct_capital(result.capital)):.6f} 億円, "
                f"ancillary = base * {ANCILLARY_FACILITIES_FACTOR:.1f}, "
                f"plant capital = (base + ancillary) * {PLANT_CAPITAL_FACTOR:.1f}"
            ),
            f"total plant capital = {yen_to_oku_yen(result.capital.total_plant_capital_yen):.6f} 億円",
            f"maintenance = {yen_to_oku_yen(result.fixed_operating.maintenance.yen_per_year):.6f} 億円/year",
            "",
            "[Fuel]",
            f"furnace required duty = {result.utility.furnace_required_duty_kw:.3f} kW",
            f"offgas fuel heat = {result.utility.offgas_fuel_heat_mj_h:.3f} MJ/h",
            f"hexane fuel heat = {result.utility.hexane_fuel_heat_mj_h:.3f} MJ/h",
            "",
            "[Warnings]",
        ]
    )
    if result.warnings:
        lines.extend(f"- {warning}" for warning in result.warnings)
    else:
        lines.append("- none")
    return "\n".join(lines)


def format_money_row(label: str, value_yen: float, note: str = "", unit: str = "億円/year") -> str:
    """金額行を整形する。"""
    suffix = f"   {note}" if note else ""
    return f"  {label:<22} {yen_to_oku_yen(value_yen):>10.4f} {unit}{suffix}"


def format_equipment_detail_row(item: CostBreakdownItem) -> str:
    """機器詳細の1行を整形する。"""
    area = "n/a" if item.area_m2 is None else f"{item.area_m2:.3f}"
    return (
        f"{item.name:<32} "
        f"{item.duty_kw:>12.3f} "
        f"{area:>12} "
        f"{yen_to_oku_yen(item.capital_yen):>14.6f} "
        f"{item.note}"
    )


def format_tq_stream_table(title: str, streams: tuple[TQStream, ...]) -> str:
    """T-Q stream 表を整形する。"""
    lines = [
        title,
        f"{'type':<5} {'role':<8} {'id':<32} {'Tin[C]':>10} {'Tout[C]':>10} {'duty[kW]':>12}",
    ]
    for stream in streams:
        lines.append(
            f"{stream.stream_type:<5} "
            f"{stream.role:<8} "
            f"{stream.id:<32} "
            f"{stream.inlet_temperature_c:>10.3f} "
            f"{stream.outlet_temperature_c:>10.3f} "
            f"{stream.duty_kw:>12.3f}"
        )
    return "\n".join(lines)


def format_external_utility_load_table(title: str, loads: tuple[ExternalUtilityLoad, ...]) -> str:
    """外部 utility load 表を整形する。"""
    lines = [
        title,
        f"{'utility':<14} {'target':<32} {'Tin[C]':>10} {'Tout[C]':>10} {'duty[kW]':>12}",
    ]
    for load in loads:
        lines.append(
            f"{load.utility:<14} "
            f"{load.target_id:<32} "
            f"{format_optional_temperature(load.inlet_temperature_c):>10} "
            f"{format_optional_temperature(load.outlet_temperature_c):>10} "
            f"{load.duty_kw:>12.3f}"
        )
    return "\n".join(lines)


def format_external_utility_summary_table(title: str, loads: tuple[ExternalUtilityLoad, ...]) -> str:
    """utility 種類ごとの duty 合計表を整形する。"""
    totals: dict[str, float] = {}
    for load in loads:
        totals[load.utility] = totals.get(load.utility, 0.0) + load.duty_kw

    lines = [
        title,
        f"{'utility':<14} {'Tin[C]':>10} {'Tout[C]':>10} {'total duty[kW]':>16}",
    ]
    for utility in sorted(totals):
        inlet_temperature_c, outlet_temperature_c = utility_temperature_range(utility)
        lines.append(
            f"{utility:<14} "
            f"{format_optional_temperature(inlet_temperature_c):>10} "
            f"{format_optional_temperature(outlet_temperature_c):>10} "
            f"{totals[utility]:>16.3f}"
        )
    return "\n".join(lines)


def utility_temperature_range(utility: str) -> tuple[float | None, float | None]:
    """utility 名から代表温度範囲を返す。"""
    if utility == "cooling water":
        return 30.0, 45.0
    if utility == "propylene":
        return 0.0, 0.0
    if utility == "steam_130c":
        return 130.0, 130.0
    if utility == "steam_160c":
        return 160.0, 160.0
    if utility == "steam_250c":
        return 250.0, 250.0
    if utility == "furnace":
        return None, None
    return None, None


def format_optional_temperature(value: float | None) -> str:
    """None を含む温度を表形式にする。"""
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def direct_capital(capital: CapitalCostResult) -> float:
    """①から⑥までの直接機器費を返す。"""
    return (
        capital.reactor.capital_yen
        + capital.distillation_columns.capital_yen
        + capital.heat_exchangers.capital_yen
        + capital.decanters.capital_yen
        + capital.pumps.capital_yen
        + capital.compressors.capital_yen
    )
