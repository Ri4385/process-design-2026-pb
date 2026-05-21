"""Human-readable plant run summaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import cast

from process_sim.plant.models import PlantRunRecord, PlantStreamRecord
from process_sim.reactor.core.models import ReactorResult, ReactorStageLog
from process_sim.reactor.core.stream import COMPONENT_ORDER
from process_sim.reactor.core.stream import ReactorFeed, ReactorStream


PRODUCT_STREAMS: tuple[tuple[str, str], ...] = (
    ("sm_product", "Styrene"),
    ("bz_product", "Benzene"),
    ("tl_product", "Toluene"),
)
RECYCLE_STREAMS: tuple[tuple[str, str], ...] = (
    ("eb_recycle", "E-Benzene"),
    ("water_recycle", "H2O"),
)
RECYCLE_PRODUCT_COMPONENT_STREAMS: tuple[tuple[str, str], ...] = (
    ("recEB", "eb_recycle"),
    ("recH2O", "water_recycle"),
    ("productSM", "sm_product"),
    ("productTL", "tl_product"),
    ("productBZ", "bz_product"),
)
OFF_GAS_COMPONENTS: tuple[str, ...] = ("Hydrogen", "Methane", "CO2", "Styrene", "E-Benzene", "H2O")
REACTOR_COMPONENT_LABELS: dict[str, str] = {
    "eb": "EB",
    "steam": "H2O",
    "styrene": "SM",
    "hydrogen": "H2",
    "benzene": "BZ",
    "toluene": "TL",
    "co2": "CO2",
    "ethylene": "C2H4",
    "methane": "CH4",
    "co": "CO",
}
REACTOR_FIELD_TO_HYSYS_COMPONENT: dict[str, str] = {
    "eb": "E-Benzene",
    "steam": "H2O",
    "styrene": "Styrene",
    "hydrogen": "Hydrogen",
    "benzene": "Benzene",
    "toluene": "Toluene",
    "co2": "CO2",
    "ethylene": "Ethylene",
    "methane": "Methane",
    "co": "CO",
}


def format_plant_run_summary(record: PlantRunRecord) -> str:
    """PlantRunRecord から人間向けの要約を作る。"""
    lines = [
        "Plant Run Summary",
        f"case: {record.case_path.name}",
        "",
        "[Separation feed]",
        *format_separation_feed(record),
        "",
        "[Reactor Overall]",
        *format_reactor_overall(record),
        "",
        "[Products]",
        *format_stream_table(record, PRODUCT_STREAMS),
        "",
        "[Recycle]",
        *format_stream_table(record, RECYCLE_STREAMS),
        "",
        "[Recycle and Products by Component]",
        *format_recycle_product_component_table(record),
        "",
        "[Off gas]",
        *format_off_gas(record),
        "",
        "[Recoveries]",
        *format_recoveries(record),
    ]
    warnings = format_warnings(record)
    if warnings:
        lines.extend(["", "[Warnings]", *warnings])
    return "\n".join(lines)


def format_recycle_product_component_summary(record: PlantRunRecord) -> str:
    """Recycle と product stream の成分流量表を返す。"""
    return "\n".join(
        [
            "[Recycle and Products by Component]",
            *format_recycle_product_component_table(record),
        ]
    )


def format_final_plant_summary_section(record: PlantRunRecord) -> str:
    """最終 plant summary section を区切り線付きで返す。"""
    return "\n".join(
        [
            "============================================",
            "[Final Plant Summary]",
            format_plant_run_summary(record),
        ]
    )


def format_reactor_calculation_summary(feed: ReactorFeed, result: ReactorResult) -> str:
    """HYSYS 実行前に出す反応器計算の要約を返す。"""
    lines = [
        "[Reactor Overall]",
        *format_reactor_stream_balance(feed=feed, outlet=result.outlet.stream),
        "",
        "[Reactor Metrics]",
        f"EB single-pass conversion: {fmt_percent(result.eb_conversion)}",
        f"SM selectivity: {fmt_percent(result.styrene_selectivity)}",
    ]
    return "\n".join(lines)


def format_radial_reactor_report(feed: ReactorFeed, result: ReactorResult) -> str:
    """ラジアルフロー反応器の詳細ログを設計書形式で返す。"""
    stage_logs = result.log.stage_logs
    lines = [
        "[Radial Reactor Summary]",
        "",
        "[Feed]",
        f"  total        : {feed.total_flow_kmol_h():.2f} kmol/h",
        f"  EB           : {feed.eb:.2f} kmol/h",
        f"  steam        : {feed.steam:.2f} kmol/h",
        f"  Steam/EB     : {safe_ratio(feed.steam, feed.eb) or 0.0:.2f} mol/mol",
        "",
        "[Overall]",
        f"  outlet T     : {result.outlet.temperature_c:.2f} degC",
        f"  inlet P      : {fmt(stage_logs[0].inlet_pressure_kpa if stage_logs else None, 3)} kPa abs",
        f"  outlet P     : {result.outlet.pressure_kpa:.3f} kPa abs",
        f"  reactor pressure drop : {fmt(result.log.reactor_pressure_drop_kpa, 3)} kPa",
        f"  reheat pressure drop  : {fmt(result.log.reheat_pressure_drop_kpa, 3)} kPa",
        f"  total pressure drop   : {fmt(result.log.total_pressure_drop_kpa, 3)} kPa",
        f"  EB conversion: {format_table_value(result.eb_conversion * 100.0, 2)} %",
        f"  SM selectivity: {format_table_value(result.styrene_selectivity * 100.0, 2)} %",
        f"  catalyst volume: {fmt(result.log.total_catalyst_volume_m3, 2)} m3",
        f"  catalyst mass  : {format_table_value(result.log.total_catalyst_mass_kg, 0)} kg",
        f"  max Re/(1-eps): {fmt(result.log.max_re_over_one_minus_void, 1)}",
        "  atom balance:",
        f"    C error : {fmt_percent(result.log.carbon_balance_error_fraction)}",
        f"    H error : {fmt_percent(result.log.hydrogen_balance_error_fraction)}",
        "  constraints:",
        f"    outlet pressure >= 30 kPa : {format_ok(result.log.outlet_pressure_ok)}",
        f"    Re/(1-eps) < 500         : {format_ok(result.log.ergun_range_ok)}",
        f"    pressure positive        : {format_ok(result.log.pressure_positive_ok)}",
        f"    atom balance             : {format_ok(result.log.atom_balance_ok)}",
        "",
        "[Stage Summary]",
        *format_radial_stage_summary(stage_logs),
        "",
        "[Stage Outlet Molar Flows, kmol/h]",
        *format_radial_stage_outlet_flows(feed=feed, stage_logs=stage_logs),
    ]
    return "\n".join(lines)


def format_pfr_reactor_report(feed: ReactorFeed, result: ReactorResult) -> str:
    """PFR 反応器の詳細ログを設計書形式で返す。"""
    stage_logs = result.log.stage_logs
    equivalent_diameter_m = equivalent_diameter(result.log.cross_section_area_m2)
    lines = [
        "[PFR Reactor Summary]",
        "",
        "[Feed]",
        f"  total        : {feed.total_flow_kmol_h():.2f} kmol/h",
        f"  EB           : {feed.eb:.2f} kmol/h",
        f"  steam        : {feed.steam:.2f} kmol/h",
        f"  Steam/EB     : {safe_ratio(feed.steam, feed.eb) or 0.0:.2f} mol/mol",
        "",
        "[Overall]",
        f"  outlet T     : {result.outlet.temperature_c:.2f} degC",
        f"  inlet P      : {fmt(stage_logs[0].inlet_pressure_kpa if stage_logs else None, 3)} kPa abs",
        f"  outlet P     : {result.outlet.pressure_kpa:.3f} kPa abs",
        f"  reactor pressure drop : {fmt(result.log.reactor_pressure_drop_kpa, 3)} kPa",
        f"  reheat pressure drop  : {fmt(result.log.reheat_pressure_drop_kpa, 3)} kPa",
        f"  total pressure drop   : {fmt(result.log.total_pressure_drop_kpa, 3)} kPa",
        f"  cross section area: {result.log.cross_section_area_m2:.3f} m2",
        f"  equivalent diameter: {equivalent_diameter_m:.3f} m",
        f"  EB conversion: {format_table_value(result.eb_conversion * 100.0, 2)} %",
        f"  SM selectivity: {format_table_value(result.styrene_selectivity * 100.0, 2)} %",
        f"  catalyst volume: {fmt(result.log.total_catalyst_volume_m3, 2)} m3",
        f"  catalyst mass  : {format_table_value(result.log.total_catalyst_mass_kg, 0)} kg",
        f"  max Re/(1-eps): {fmt(result.log.max_re_over_one_minus_void, 1)}",
        "  atom balance:",
        f"    C error : {fmt_percent(result.log.carbon_balance_error_fraction)}",
        f"    H error : {fmt_percent(result.log.hydrogen_balance_error_fraction)}",
        "  constraints:",
        f"    outlet pressure >= 30 kPa : {format_ok(result.log.outlet_pressure_ok)}",
        f"    Re/(1-eps) < 500         : {format_ok(result.log.ergun_range_ok)}",
        f"    pressure positive        : {format_ok(result.log.pressure_positive_ok)}",
        f"    atom balance             : {format_ok(result.log.atom_balance_ok)}",
        "",
        "[Stage Summary]",
        *format_pfr_stage_summary(stage_logs=stage_logs, cross_section_area_m2=result.log.cross_section_area_m2),
        "",
        "[Stage Outlet Molar Flows, kmol/h]",
        *format_radial_stage_outlet_flows(feed=feed, stage_logs=stage_logs),
    ]
    return "\n".join(lines)


def format_pfr_stage_summary(stage_logs: tuple[ReactorStageLog, ...], cross_section_area_m2: float) -> list[str]:
    """PFR の各段横持ち表を返す。"""
    equivalent_diameter_m = equivalent_diameter(cross_section_area_m2)
    headers = ["item", *[f"stage {log.stage_index}" for log in stage_logs]]
    rows: list[tuple[str, Sequence[float | None], int]] = [
        ("inlet T [degC]", [log.inlet_temperature_c for log in stage_logs], 2),
        ("outlet T [degC]", [log.outlet_temperature_c for log in stage_logs], 2),
        ("inlet P [kPa abs]", [log.inlet_pressure_kpa for log in stage_logs], 3),
        ("outlet P [kPa abs]", [log.outlet_pressure_kpa for log in stage_logs], 3),
        ("reactor pressure drop [kPa]", [log.reactor_pressure_drop_kpa for log in stage_logs], 3),
        ("reheat pressure drop [kPa]", [log.reheat_pressure_drop_kpa for log in stage_logs], 3),
        ("stage length [m]", [log.stage_length_m for log in stage_logs], 3),
        ("cross section area [m2]", [cross_section_area_m2 for _ in stage_logs], 3),
        ("equivalent diameter [m]", [equivalent_diameter_m for _ in stage_logs], 3),
        ("catalyst volume [m3]", [log.catalyst_volume_m3 for log in stage_logs], 2),
        ("catalyst mass [kg]", [log.catalyst_mass_kg for log in stage_logs], 0),
        ("inlet velocity [m/s]", [log.inlet_superficial_velocity_m_per_s for log in stage_logs], 3),
        ("outlet velocity [m/s]", [log.outlet_superficial_velocity_m_per_s for log in stage_logs], 3),
        ("min Re/(1-eps) [-]", [log.min_re_over_one_minus_void for log in stage_logs], 1),
        ("max Re/(1-eps) [-]", [log.max_re_over_one_minus_void for log in stage_logs], 1),
        ("EB conversion [%]", [log.eb_conversion * 100.0 for log in stage_logs], 2),
        ("SM selectivity [%]", [log.styrene_selectivity * 100.0 for log in stage_logs], 2),
        ("reheat duty [MW]", [log.reheat_duty_mw for log in stage_logs], 3),
        ("C balance error [%]", [optional_percent(log.carbon_balance_error_fraction) for log in stage_logs], 4),
        ("H balance error [%]", [optional_percent(log.hydrogen_balance_error_fraction) for log in stage_logs], 4),
    ]
    return format_wide_rows(headers=headers, rows=rows)


def format_radial_stage_summary(stage_logs: tuple[ReactorStageLog, ...]) -> list[str]:
    """ラジアルフロー反応器の各段横持ち表を返す。"""
    headers = ["item", *[f"stage {log.stage_index}" for log in stage_logs]]
    rows: list[tuple[str, Sequence[float | None], int]] = [
        ("inlet T [degC]", [log.inlet_temperature_c for log in stage_logs], 2),
        ("outlet T [degC]", [log.outlet_temperature_c for log in stage_logs], 2),
        ("inlet P [kPa abs]", [log.inlet_pressure_kpa for log in stage_logs], 3),
        ("outlet P [kPa abs]", [log.outlet_pressure_kpa for log in stage_logs], 3),
        ("reactor pressure drop [kPa]", [log.reactor_pressure_drop_kpa for log in stage_logs], 3),
        ("reheat pressure drop [kPa]", [log.reheat_pressure_drop_kpa for log in stage_logs], 3),
        ("inner radius [m]", [log.inner_radius_m for log in stage_logs], 3),
        ("inner diameter [m]", [optional_double(log.inner_radius_m) for log in stage_logs], 3),
        ("outer radius [m]", [log.outer_radius_m for log in stage_logs], 3),
        ("bed height [m]", [log.bed_height_m for log in stage_logs], 3),
        ("bed thickness [m]", [log.bed_thickness_m for log in stage_logs], 3),
        ("catalyst volume [m3]", [log.catalyst_volume_m3 for log in stage_logs], 2),
        ("catalyst mass [kg]", [log.catalyst_mass_kg for log in stage_logs], 0),
        ("inlet velocity [m/s]", [log.inlet_superficial_velocity_m_per_s for log in stage_logs], 3),
        ("outlet velocity [m/s]", [log.outlet_superficial_velocity_m_per_s for log in stage_logs], 3),
        ("min Re/(1-eps) [-]", [log.min_re_over_one_minus_void for log in stage_logs], 1),
        ("max Re/(1-eps) [-]", [log.max_re_over_one_minus_void for log in stage_logs], 1),
        ("EB conversion [%]", [log.eb_conversion * 100.0 for log in stage_logs], 2),
        ("SM selectivity [%]", [log.styrene_selectivity * 100.0 for log in stage_logs], 2),
        ("reheat duty [MW]", [log.reheat_duty_mw for log in stage_logs], 3),
        ("C balance error [%]", [optional_percent(log.carbon_balance_error_fraction) for log in stage_logs], 4),
        ("H balance error [%]", [optional_percent(log.hydrogen_balance_error_fraction) for log in stage_logs], 4),
    ]
    return format_wide_rows(headers=headers, rows=rows)


def format_radial_stage_outlet_flows(feed: ReactorFeed, stage_logs: tuple[ReactorStageLog, ...]) -> list[str]:
    """段出口モル流量の横持ち表を返す。"""
    headers = ["component", "inlet", *[f"stage {log.stage_index} out" for log in stage_logs]]
    rows: list[tuple[str, Sequence[float | None], int]] = []
    feed_flows = feed.to_component_flows_kmol_h()
    for field_name in COMPONENT_ORDER:
        values: list[float | None] = [feed_flows[field_name]]
        for log in stage_logs:
            values.append(log.outlet.to_component_flows_kmol_h()[field_name])
        rows.append((REACTOR_COMPONENT_LABELS[field_name], values, 3))
    return format_wide_rows(headers=headers, rows=rows)


def format_wide_rows(
    headers: list[str],
    rows: Sequence[tuple[str, Sequence[float | None], int]],
) -> list[str]:
    """項目名と数値列を横持ち表に整形する。"""
    item_width = max(len(headers[0]), *(len(row[0]) for row in rows))
    value_width = 14
    lines = [
        f"  {headers[0]:<{item_width}} "
        + " ".join(f"{header:>{value_width}}" for header in headers[1:])
    ]
    for label_text, values, digits in rows:
        rendered = [format_table_value(value, digits) for value in values]
        lines.append(
            f"  {label_text:<{item_width}} "
            + " ".join(f"{value:>{value_width}}" for value in rendered)
        )
    return lines


def format_table_value(value: float | None, digits: int) -> str:
    """表内の数値または欠損値を返す。"""
    if value is None:
        return "-"
    if digits == 0:
        return f"{value:,.0f}"
    return f"{value:.{digits}f}"


def optional_percent(value: float | None) -> float | None:
    """None を保ったまま percent 表示用の値へ変換する。"""
    if value is None:
        return None
    return value * 100.0


def optional_double(value: float | None) -> float | None:
    """None を保ったまま2倍値へ変換する。"""
    if value is None:
        return None
    return value * 2.0


def format_ok(value: bool | None) -> str:
    """制約判定を OK/NG 表示にする。"""
    if value is None:
        return "n/a"
    return "OK" if value else "NG"


def equivalent_diameter(cross_section_area_m2: float) -> float:
    """断面積から円形断面の等価直径を返す。"""
    return math.sqrt(4.0 * cross_section_area_m2 / math.pi)


def format_reactor_overall(record: PlantRunRecord) -> list[str]:
    """反応器入口・出口だけから全体指標を返す。"""
    inlet_flows = reactor_inlet_flows(record)
    outlet = record.streams.get("reactor_outlet")
    if inlet_flows is None or outlet is None:
        return ["n/a"]

    rows = [
        f"{'component':<10} {'inlet kmol/h':>14} {'outlet kmol/h':>15} {'delta kmol/h':>14}",
    ]
    for field_name in COMPONENT_ORDER:
        inlet = inlet_flows.get(field_name, 0.0)
        outlet_flow = component_flow(outlet, REACTOR_FIELD_TO_HYSYS_COMPONENT[field_name]) or 0.0
        rows.append(
            f"{REACTOR_COMPONENT_LABELS[field_name]:<10} "
            f"{inlet:>14.3f} "
            f"{outlet_flow:>15.3f} "
            f"{outlet_flow - inlet:>+14.3f}"
        )

    eb_in = inlet_flows.get("eb", 0.0)
    eb_out = component_flow(outlet, "E-Benzene")
    sm_in = inlet_flows.get("styrene", 0.0)
    sm_out = component_flow(outlet, "Styrene")
    eb_consumed = None if eb_out is None else eb_in - eb_out
    sm_net = None if sm_out is None else sm_out - sm_in
    rows.extend(
        [
            "",
            "[Reactor Metrics]",
            f"EB single-pass conversion: {fmt_percent(safe_ratio(eb_consumed, eb_in))}",
            f"SM selectivity: {fmt_percent(safe_ratio(sm_net, eb_consumed))}",
        ]
    )
    return rows


def format_reactor_stream_balance(feed: ReactorFeed, outlet: ReactorStream) -> list[str]:
    """反応器入口・出口の成分収支表を返す。"""
    rows = [
        f"{'component':<10} {'inlet kmol/h':>14} {'outlet kmol/h':>15} {'delta kmol/h':>14}",
    ]
    for field_name in COMPONENT_ORDER:
        inlet = getattr(feed, field_name)
        outlet_flow = getattr(outlet, field_name)
        rows.append(
            f"{REACTOR_COMPONENT_LABELS[field_name]:<10} "
            f"{inlet:>14.3f} "
            f"{outlet_flow:>15.3f} "
            f"{outlet_flow - inlet:>+14.3f}"
        )
    return rows


def format_recycle_product_component_table(record: PlantRunRecord) -> list[str]:
    """Recycle と product stream の成分流量を成分ごとに返す。"""
    headers = " ".join(f"{column_label:>10}" for column_label, _ in RECYCLE_PRODUCT_COMPONENT_STREAMS)
    rows = [f"{'component':<10} {headers}"]
    for field_name in COMPONENT_ORDER:
        component_name = REACTOR_FIELD_TO_HYSYS_COMPONENT[field_name]
        values = [
            fmt(component_flow(record.streams.get(stream_name), component_name), 3)
            for _, stream_name in RECYCLE_PRODUCT_COMPONENT_STREAMS
        ]
        rows.append(
            f"{REACTOR_COMPONENT_LABELS[field_name]:<10} "
            + " ".join(f"{value:>10}" for value in values)
        )
    return rows


def reactor_inlet_flows(record: PlantRunRecord) -> dict[str, float] | None:
    """metadata に記録した reactor feed を返す。"""
    value = record.metadata.get("reactor_feed")
    if not isinstance(value, Mapping):
        return None
    raw_flows = cast(Mapping[str, object], value)
    flows: dict[str, float] = {}
    for field_name in COMPONENT_ORDER:
        component_value = raw_flows.get(field_name)
        if isinstance(component_value, (int, float)):
            flows[field_name] = float(component_value)
        else:
            flows[field_name] = 0.0
    return flows


def format_separation_feed(record: PlantRunRecord) -> list[str]:
    """反応器出口と分離系入口の要約を返す。"""
    reactor_outlet = record.streams.get("reactor_outlet")
    separator_feed = record.streams.get("separator_feed")
    return [
        f"reactor_outlet T: {fmt(stream_temperature(reactor_outlet), 2)} C",
        f"separator_feed T: {fmt(stream_temperature(separator_feed), 2)} C",
        f"separator_feed total: {fmt(stream_total_flow(separator_feed), 2)} kmol/h",
    ]


def format_stream_table(record: PlantRunRecord, streams: tuple[tuple[str, str], ...]) -> list[str]:
    """主要 stream 表を返す。"""
    rows = [
        f"{'stream':<15} {'total kmol/h':>13} {'main comp':>10} {'purity mol%':>12} {'main flow kmol/h':>17}"
    ]
    for stream_name, component_name in streams:
        stream = record.streams.get(stream_name)
        rows.append(
            f"{stream_name:<15} "
            f"{fmt(stream_total_flow(stream), 2):>13} "
            f"{label(component_name):>10} "
            f"{fmt(component_purity(stream, component_name), 3):>12} "
            f"{fmt(component_flow(stream, component_name), 2):>17}"
        )
    return rows


def format_off_gas(record: PlantRunRecord) -> list[str]:
    """off gas の主要成分を返す。"""
    off_gas = record.streams.get("off_gas")
    lines = [f"total: {fmt(stream_total_flow(off_gas), 2)} kmol/h"]
    for component_name in OFF_GAS_COMPONENTS:
        lines.append(f"{label(component_name)}: {fmt(component_flow(off_gas, component_name), 2)} kmol/h")
    return lines


def format_recoveries(record: PlantRunRecord) -> list[str]:
    """主要成分の回収率を返す。"""
    return [
        format_recovery_line(record, "SM to sm_product", "Styrene", "sm_product"),
        format_recovery_line(record, "EB to eb_recycle", "E-Benzene", "eb_recycle"),
        format_recovery_line(record, "H2O to water_recycle", "H2O", "water_recycle"),
    ]


def format_recovery_line(
    record: PlantRunRecord,
    label: str,
    component_name: str,
    outlet_stream_name: str,
) -> str:
    """1成分の回収率行を返す。"""
    separator_feed = record.streams.get("separator_feed")
    outlet_stream = record.streams.get(outlet_stream_name)
    inlet_flow = component_flow(separator_feed, component_name)
    outlet_flow = component_flow(outlet_stream, component_name)
    if inlet_flow is None or outlet_flow is None or inlet_flow <= 0.0:
        return f"{label}: n/a"
    return f"{label}: {outlet_flow / inlet_flow * 100.0:.2f} %"


def format_warnings(record: PlantRunRecord) -> list[str]:
    """調整対象になりそうな項目を警告として返す。"""
    warnings: list[str] = []
    bz_purity = component_purity(record.streams.get("bz_product"), "Benzene")
    if bz_purity is not None and bz_purity < 99.5:
        warnings.append(f"BZ product purity is low: {bz_purity:.3f} mol%")

    off_gas = record.streams.get("off_gas")
    for component_name, threshold in (("Styrene", 1.0), ("E-Benzene", 1.0), ("H2O", 10.0)):
        flow = component_flow(off_gas, component_name)
        if flow is not None and flow > threshold:
            warnings.append(f"Off gas contains {label(component_name)}: {flow:.2f} kmol/h")
    return warnings


def component_flow(stream: PlantStreamRecord | None, component_name: str) -> float | None:
    """成分モル流量を返す。"""
    if stream is None:
        return None
    return stream.component_molar_flow_kmol_h.get(component_name)


def component_purity(stream: PlantStreamRecord | None, component_name: str) -> float | None:
    """成分モル分率を mol% で返す。"""
    if stream is None:
        return None
    fraction = stream.component_molar_fraction.get(component_name)
    if fraction is None:
        return None
    return fraction * 100.0


def stream_temperature(stream: PlantStreamRecord | None) -> float | None:
    """stream 温度を返す。"""
    return None if stream is None else stream.temperature_c


def stream_total_flow(stream: PlantStreamRecord | None) -> float | None:
    """stream 総モル流量を返す。"""
    return None if stream is None else stream.total_molar_flow_kmol_h


def label(component_name: str) -> str:
    """表示用の成分略称を返す。"""
    labels = {
        "Styrene": "SM",
        "E-Benzene": "EB",
        "Benzene": "BZ",
        "Toluene": "TL",
        "H2O": "H2O",
        "Hydrogen": "H2",
        "Methane": "CH4",
        "CO2": "CO2",
    }
    return labels.get(component_name, component_name)


def fmt(value: float | None, digits: int) -> str:
    """None を含む数値を表示用に整形する。"""
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    """0 割りと None を避けて比率を返す。"""
    if numerator is None or denominator is None or denominator <= 0.0:
        return None
    return numerator / denominator


def fmt_percent(value: float | None) -> str:
    """比率を percent 表示する。"""
    if value is None:
        return "n/a"
    return f"{value * 100.0:.3f} %"
