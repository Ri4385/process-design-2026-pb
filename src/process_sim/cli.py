"""CLI entry points for process_sim."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from process_sim.constants import DEFAULT_REACTOR_CONFIG
from process_sim.reactor.models import ReactorFeed, ReactorResult, ReactorRunConditions, ReactorStageLog, ReactorStream
from process_sim.reactor.simulator import StyreneReactorModel


def build_default_input() -> dict[str, Any]:
    """反応器の参照ケース入力を返す。"""
    return {
        "feed": {
            "eb": 605.9,
            "steam": 3029.5,
            "styrene": 0.0606,
            "hydrogen": 0.0,
            "benzene": 0.0606,
            "toluene": 0.0606,
            "co2": 0.0,
            "ethylene": 0.0,
            "methane": 0.0,
            "co": 0.0,
        },
        "conditions": {
            "pressure_kpa": DEFAULT_REACTOR_CONFIG.operation.pressure_kpa,
            "stage_inlet_temperatures_c": list(DEFAULT_REACTOR_CONFIG.operation.stage_inlet_temperatures_c),
            "stage_lengths_m": list(DEFAULT_REACTOR_CONFIG.operation.stage_lengths_m),
            "inlet_superficial_velocity_m_per_s": DEFAULT_REACTOR_CONFIG.operation.inlet_superficial_velocity_m_per_s,
            "segments_per_stage": DEFAULT_REACTOR_CONFIG.operation.segments_per_stage,
            "profile_points_per_stage": DEFAULT_REACTOR_CONFIG.operation.profile_points_per_stage,
        },
    }


def _deep_update(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def apply_input_overrides(values: dict[str, Any], input_json: Path | None) -> dict[str, Any]:
    if input_json is None:
        return values

    loaded = json.loads(input_json.read_text(encoding="utf-8"))
    return _deep_update(values, loaded)


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
    return [
        f"- {label} EB: {stream.eb:.2f} kmol/h",
        f"- {label} Steam: {stream.steam:.2f} kmol/h",
        f"- {label} Styrene: {stream.styrene:.2f} kmol/h",
        f"- {label} Hydrogen: {stream.hydrogen:.2f} kmol/h",
        f"- {label} Benzene: {stream.benzene:.2f} kmol/h",
        f"- {label} Toluene: {stream.toluene:.2f} kmol/h",
        f"- {label} CO2: {stream.co2:.2f} kmol/h",
    ]


def _stage_delta_lines(stage_log: ReactorStageLog) -> list[str]:
    inlet = stage_log.inlet
    outlet = stage_log.outlet
    return [
        f"- EB: {_format_flow_delta(inlet.eb, outlet.eb)}",
        f"- Steam: {_format_flow_delta(inlet.steam, outlet.steam)}",
        f"- Styrene: {_format_flow_delta(inlet.styrene, outlet.styrene)}",
        f"- Hydrogen: {_format_flow_delta(inlet.hydrogen, outlet.hydrogen)}",
        f"- Benzene: {_format_flow_delta(inlet.benzene, outlet.benzene)}",
        f"- Toluene: {_format_flow_delta(inlet.toluene, outlet.toluene)}",
        f"- CO2: {_format_flow_delta(inlet.co2, outlet.co2)}",
    ]


def format_reactor_report(result: ReactorResult, payload: dict[str, Any]) -> str:
    feed = ReactorFeed(**payload["feed"])
    outlet = result.outlet.stream

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
        f"- EB: {_format_flow_delta(feed.eb, outlet.eb)}",
        f"- Steam: {_format_flow_delta(feed.steam, outlet.steam)}",
        f"- Styrene: {_format_flow_delta(feed.styrene, outlet.styrene)}",
        f"- Hydrogen: {_format_flow_delta(feed.hydrogen, outlet.hydrogen)}",
        f"- Benzene: {_format_flow_delta(feed.benzene, outlet.benzene)}",
        f"- Toluene: {_format_flow_delta(feed.toluene, outlet.toluene)}",
        f"- CO2: {_format_flow_delta(feed.co2, outlet.co2)}",
        "",
        "各段ログ",
    ]

    for stage_log in result.log.stage_logs:
        lines.extend(
            [
                f"第{stage_log.stage_index}段",
                f"- 温度: {stage_log.inlet_temperature_c:.2f} -> {stage_log.outlet_temperature_c:.2f} degC",
                f"- 温度低下: {stage_log.outlet_temperature_c - stage_log.inlet_temperature_c:+.2f} degC",
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

    payload = build_default_input()
    payload = apply_input_overrides(payload, args.input_json)

    feed = ReactorFeed(**payload["feed"])
    conditions = ReactorRunConditions(**payload["conditions"])
    model = StyreneReactorModel(config=DEFAULT_REACTOR_CONFIG)
    result = model.run(feed=feed, conditions=conditions)

    if not args.json:
        print(format_reactor_report(result=result, payload=payload))
        return

    output = {
        "input": payload,
        "result": asdict(result),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
