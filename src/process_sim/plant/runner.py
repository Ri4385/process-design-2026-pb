"""Plant-level one-pass runner."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import logging
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from process_sim.plant.const import DEFAULT_HYSYS_CASE_PATH, DEFAULT_HYSYS_RUN_TIMEOUT_SECONDS
from process_sim.plant.models import PlantRunRecord
from process_sim.plant.summary import (
    format_plant_run_summary,
    format_reactor_calculation_summary,
    format_recycle_product_component_summary,
)
from process_sim.reactor.cases.styrene_default import DEFAULT_STYRENE_REACTOR_CASE, ReactorCase
from process_sim.reactor.types.staged_adiabatic_pfr import StagedAdiabaticPfrModel
from process_sim.separator.hysys_io import run_hysys_separation_once


logger = logging.getLogger(__name__)


def run_plant_once(
    case_path: Path = DEFAULT_HYSYS_CASE_PATH,
    reactor_case: ReactorCase = DEFAULT_STYRENE_REACTOR_CASE,
    hysys_visible: bool = True,
) -> PlantRunRecord:
    """反応器出口を HYSYS 分離系へ渡し、主要 stream を記録する。"""
    plant_started_at = time.perf_counter()
    logger.info("plant run started")
    logger.info("HYSYS case path: %s", case_path.resolve())
    logger.info("HYSYS visible: %s", hysys_visible)

    model = StagedAdiabaticPfrModel()
    reactor_started_at = time.perf_counter()
    logger.info("reactor run started")
    reactor_result = model.run(feed=reactor_case.feed, conditions=reactor_case.conditions)
    logger.info("reactor run finished in %.2f s", time.perf_counter() - reactor_started_at)
    logger.info("\n%s", format_reactor_calculation_summary(feed=reactor_case.feed, result=reactor_result))

    separator_started_at = time.perf_counter()
    logger.info("separator run started")
    streams, hysys_metadata = run_hysys_separation_once(
        case_path=case_path,
        reactor_stream=reactor_result.outlet.stream,
        temperature_c=reactor_result.outlet.temperature_c,
        pressure_kpa=reactor_result.outlet.pressure_kpa,
        visible=hysys_visible,
    )
    logger.info("separator run finished in %.2f s", time.perf_counter() - separator_started_at)
    metadata: dict[str, Any] = {
        **hysys_metadata,
        "reactor_case": asdict(reactor_case),
        "reactor_feed": reactor_case.feed.to_component_flows_kmol_h(),
        "reactor_eb_conversion": reactor_result.eb_conversion,
        "reactor_styrene_selectivity": reactor_result.styrene_selectivity,
    }
    preview_record = PlantRunRecord(
        case_path=case_path.resolve(),
        reactor_outlet_temperature_c=reactor_result.outlet.temperature_c,
        reactor_outlet_pressure_kpa=reactor_result.outlet.pressure_kpa,
        streams=streams,
        metadata=metadata,
    )
    logger.info("\n%s", format_recycle_product_component_summary(preview_record))
    logger.info("plant run finished in %.2f s", time.perf_counter() - plant_started_at)
    return preview_record


def run_plant_once_main() -> None:
    """plant one-pass を実行し、JSON 出力する。"""
    configure_logging()
    args = parse_plant_run_args()
    if not args.plant_run_worker:
        run_plant_once_with_subprocess_timeout(
            case_path=args.case_path,
            hysys_visible=not args.hidden,
            timeout_seconds=args.timeout_seconds,
        )
        return

    record = run_plant_once(
        case_path=args.case_path,
        hysys_visible=not args.hidden,
    )
    print(json.dumps(asdict(record), ensure_ascii=False, indent=2, default=str))
    print(format_plant_run_summary(record))


def run_plant_once_with_subprocess_timeout(
    case_path: Path,
    hysys_visible: bool,
    timeout_seconds: float,
) -> None:
    """HYSYS 実行を子 Python プロセスに隔離して timeout をかける。"""
    command = [
        sys.executable,
        "-m",
        "process_sim.plant.runner",
        "--plant-run-worker",
        "--case-path",
        str(case_path),
    ]
    if not hysys_visible:
        command.append("--hidden")

    try:
        completed = subprocess.run(
            command,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"HYSYS plant run exceeded timeout: {timeout_seconds:.1f} s"
        ) from exc

    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def parse_plant_run_args() -> argparse.Namespace:
    """plant one-pass CLI の引数を読む。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-path", type=Path, default=DEFAULT_HYSYS_CASE_PATH)
    parser.add_argument("--hidden", action="store_true", help="HYSYS GUI を表示しない")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_HYSYS_RUN_TIMEOUT_SECONDS)
    parser.add_argument("--plant-run-worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def configure_logging() -> None:
    """CLI 実行時の簡易進行ログを設定する。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


if __name__ == "__main__":
    run_plant_once_main()
