"""Human-readable plant run summaries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from process_sim.plant.models import PlantRunRecord, PlantStreamRecord
from process_sim.reactor.core.models import ReactorResult
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
