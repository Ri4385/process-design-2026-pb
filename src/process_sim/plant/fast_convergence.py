"""HYSYS session 再利用版の plant convergence 実行入口。"""

from __future__ import annotations

from process_sim.cli import ReactorModelName
from process_sim.plant.const import DEFAULT_HYSYS_CASE_PATH, DEFAULT_TARGET_SM_KMOL_H
from process_sim.plant.convergence import format_plant_convergence_result, run_production_target_convergence
from process_sim.plant.runner import configure_logging
from process_sim.plant.session_runner import OpenHysysPlantRunner


FAST_REACTOR_MODEL: ReactorModelName = "radial"


def fast_plant_convergence_main() -> None:
    """HYSYS case を開いたまま production target と convergence を連続実行する。"""
    configure_logging()
    with OpenHysysPlantRunner(
        case_path=DEFAULT_HYSYS_CASE_PATH,
        reactor_model=FAST_REACTOR_MODEL,
    ) as runner:
        result = run_production_target_convergence(
            target_sm_kmol_h=DEFAULT_TARGET_SM_KMOL_H,
            production_target_runner=runner,
            convergence_runner=runner,
            reactor_model=FAST_REACTOR_MODEL,
        )
    print(format_plant_convergence_result(result))
