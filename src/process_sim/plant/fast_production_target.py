"""HYSYS session 再利用版の production target 実行入口。"""

from __future__ import annotations

from process_sim.cli import ReactorModelName
from process_sim.plant.const import DEFAULT_HYSYS_CASE_PATH, DEFAULT_TARGET_SM_KMOL_H
from process_sim.plant.production_target import (
    FeedTuningOptions,
    default_reactor_case_for_model,
    format_feed_tuning_result,
    tune_fresh_feed_fast,
)
from process_sim.plant.runner import configure_logging
from process_sim.plant.session_runner import OpenHysysPlantRunner


FAST_REACTOR_MODEL: ReactorModelName = "radial"


def fast_production_target_main() -> None:
    """HYSYS case を開いたまま production target を実行する。"""
    configure_logging()
    with OpenHysysPlantRunner(
        case_path=DEFAULT_HYSYS_CASE_PATH,
        reactor_model=FAST_REACTOR_MODEL,
    ) as runner:
        result = tune_fresh_feed_fast(
            options=FeedTuningOptions(target_sm_kmol_h=DEFAULT_TARGET_SM_KMOL_H),
            base_reactor_case=default_reactor_case_for_model(FAST_REACTOR_MODEL),
            plant_runner=runner,
            reactor_model=FAST_REACTOR_MODEL,
        )
    print(format_feed_tuning_result(result))
