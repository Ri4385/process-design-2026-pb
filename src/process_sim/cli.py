"""CLI entry points for process_sim."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, cast

from process_sim.reactor.cases import DEFAULT_STYRENE_REACTOR_CASE, ReactorCase
from process_sim.reactor.core.models import ReactorResult, ReactorRunConditions, ReactorStageLog
from process_sim.reactor.core.stream import COMPONENT_ORDER, ReactorFeed, ReactorStream
from process_sim.reactor.types import StagedAdiabaticPfrModel


def default_case_payload() -> dict[str, Any]:
    """既定ケースを JSON 化しやすい辞書で返す。"""
    return asdict(DEFAULT_STYRENE_REACTOR_CASE)


def _deep_update(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(cast(dict[str, Any], base[key]), cast(dict[str, Any], value))
        else:
            base[key] = value
    return base


def apply_input_overrides(values: dict[str, Any], input_json: Path | None) -> dict[str, Any]:
    """入力 JSON が指定された場合だけ既定ケースを上書きする。"""
    if input_json is None:
        return values

    loaded = json.loads(input_json.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("input JSON must be an object")
    return _deep_update(values, cast(dict[str, Any], loaded))


def case_from_payload(payload: dict[str, Any]) -> ReactorCase:
    """辞書から反応器ケースを作る。"""
    conditions_payload = dict(payload["conditions"])
    conditions_payload["stage_inlet_temperatures_c"] = tuple(conditions_payload["stage_inlet_temperatures_c"])
    conditions_payload["stage_lengths_m"] = tuple(conditions_payload["stage_lengths_m"])
    return ReactorCase(
        feed=ReactorFeed(**payload["feed"]),
        conditions=ReactorRunConditions(**conditions_payload),
    )


def parse_run_reactor_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-json",
        type=Path,
        default=None,
        help="入力値を上書きする JSON ファイルパス",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="人間向け整形ではなく JSON を出力する",
    )
    return parser.parse_args()


def _format_percentage(value: float) -> str:
    return f"{value * 100.0:.2f} %"


def _format_flow_delta(before: float, after: float) -> str:
    delta = after - before
    return f"{after:.2f} kmol/h  差分 {delta:+.2f}"


def _stream_total_line(label: str, stream: ReactorStream) -> str:
    return f"- {label}: {stream.total_flow_kmol_h():.2f} kmol/h"


def _stream_component_lines(label: str, stream: ReactorStream) -> list[str]:
    flows = stream.to_component_flows_kmol_h()
    return [f"- {label} {name}: {flows[name]:.2f} kmol/h" for name in COMPONENT_ORDER]


def _stage_delta_lines(stage_log: ReactorStageLog) -> list[str]:
    inlet = stage_log.inlet.to_component_flows_kmol_h()
    outlet = stage_log.outlet.to_component_flows_kmol_h()
    return [f"- {name}: {_format_flow_delta(inlet[name], outlet[name])}" for name in COMPONENT_ORDER]


def format_reactor_report(result: ReactorResult, payload: dict[str, Any]) -> str:
    feed = case_from_payload(payload).feed
    outlet = result.outlet.stream
    feed_flows = feed.to_component_flows_kmol_h()
    outlet_flows = outlet.to_component_flows_kmol_h()

    lines = [
        "反応器ログ",
        "",
        "入口条件 feed",
        _stream_total_line("総流量", feed),
        *_stream_component_lines("入口", feed),
        "",
        "",
        "全体サマリー",
        f"- 出口温度: {result.outlet.temperature_c:.2f} degC",
        f"- 圧力: {result.outlet.pressure_kpa:.3f} kPa",
        f"- EB転化率: {_format_percentage(result.eb_conversion)}",
        f"- スチレン選択率: {_format_percentage(result.styrene_selectivity)}",
        f"- 反応器断面積: {result.log.cross_section_area_m2:.4f} m2",
        f"- 第1段入口体積流量: {result.log.inlet_volumetric_flow_m3_s:.4f} m3/s",
        "",
        "出口流量",
        _stream_total_line("総流量", outlet),
        *_stream_component_lines("出口", outlet),
        "",
        "入口から出口までの差分",
        *[f"- {name}: {_format_flow_delta(feed_flows[name], outlet_flows[name])}" for name in COMPONENT_ORDER],
        "",
        "各段ログ",
    ]

    for stage_log in result.log.stage_logs:
        lines.extend(
            [
                f"第{stage_log.stage_index}段",
                f"- 温度: {stage_log.inlet_temperature_c:.2f} -> {stage_log.outlet_temperature_c:.2f} degC",
                f"- 温度変化: {stage_log.outlet_temperature_c - stage_log.inlet_temperature_c:+.2f} degC",
                f"- 段長: {stage_log.stage_length_m:.2f} m",
                f"- 線速: {stage_log.inlet_superficial_velocity_m_per_s:.3f} -> {stage_log.outlet_superficial_velocity_m_per_s:.3f} m/s",
                f"- EB転化率: {_format_percentage(stage_log.eb_conversion)}",
                f"- スチレン選択率: {_format_percentage(stage_log.styrene_selectivity)}",
            ]
        )
        if stage_log.reheat_duty_mw is None:
            lines.append("- 段間再加熱負荷: 最終段のためなし")
        else:
            lines.append(f"- 段間再加熱負荷: {stage_log.reheat_duty_mw:.3f} MW")
        lines.extend(["- 段内の流量変化", *_stage_delta_lines(stage_log), ""])

    return "\n".join(lines).rstrip()


def run_reactor_case_main() -> None:
    args = parse_run_reactor_args()

    payload = default_case_payload()
    payload = apply_input_overrides(payload, args.input_json)

    reactor_case = case_from_payload(payload)
    model = StagedAdiabaticPfrModel()
    result = model.run(feed=reactor_case.feed, conditions=reactor_case.conditions)

    if not args.json:
        print(format_reactor_report(result=result, payload=payload))
        return

    output = {
        "input": payload,
        "result": asdict(result),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
