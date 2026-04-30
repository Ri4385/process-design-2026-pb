"""Plant-level one-pass runner."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from process_sim.plant.models import PlantRunRecord
from process_sim.reactor.cases import DEFAULT_STYRENE_REACTOR_CASE, ReactorCase
from process_sim.reactor.types import StagedAdiabaticPfrModel
from process_sim.separator import run_hysys_separation_once


DEFAULT_HYSYS_CASE_PATH = Path("data/hysys/process_design_0430v3.hsc")
DEFAULT_HYSYS_RUN_TIMEOUT_SECONDS = 120.0


def run_plant_once(
    case_path: Path = DEFAULT_HYSYS_CASE_PATH,
    reactor_case: ReactorCase = DEFAULT_STYRENE_REACTOR_CASE,
    hysys_visible: bool = True,
) -> PlantRunRecord:
    """反応器出口を HYSYS 分離系へ渡し、主要 stream を記録する。"""
    model = StagedAdiabaticPfrModel()
    reactor_result = model.run(feed=reactor_case.feed, conditions=reactor_case.conditions)

    streams, hysys_metadata = run_hysys_separation_once(
        case_path=case_path,
        reactor_stream=reactor_result.outlet.stream,
        temperature_c=reactor_result.outlet.temperature_c,
        pressure_kpa=reactor_result.outlet.pressure_kpa,
        visible=hysys_visible,
    )
    metadata: dict[str, Any] = {
        **hysys_metadata,
        "reactor_case": asdict(reactor_case),
        "reactor_eb_conversion": reactor_result.eb_conversion,
        "reactor_styrene_selectivity": reactor_result.styrene_selectivity,
    }
    return PlantRunRecord(
        case_path=case_path.resolve(),
        reactor_outlet_temperature_c=reactor_result.outlet.temperature_c,
        reactor_outlet_pressure_kpa=reactor_result.outlet.pressure_kpa,
        streams=streams,
        metadata=metadata,
    )


def run_plant_once_main() -> None:
    """plant one-pass を実行し、JSON 出力する。"""
    if "--plant-run-worker" not in sys.argv:
        run_plant_once_with_subprocess_timeout(timeout_seconds=DEFAULT_HYSYS_RUN_TIMEOUT_SECONDS)
        return

    record = run_plant_once()
    print(json.dumps(asdict(record), ensure_ascii=False, indent=2, default=str))


def run_plant_once_with_subprocess_timeout(timeout_seconds: float) -> None:
    """HYSYS 実行を子 Python プロセスに隔離して timeout をかける。"""
    command = [
        sys.executable,
        "-m",
        "process_sim.plant.runner",
        "--plant-run-worker",
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"HYSYS plant run exceeded timeout: {timeout_seconds:.1f} s"
        ) from exc

    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    run_plant_once_main()
