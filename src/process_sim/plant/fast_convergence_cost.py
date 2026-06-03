"""HYSYS session 再利用版の plant convergence + cost 評価入口。"""

from __future__ import annotations

from process_sim.cli import ReactorModelName
from process_sim.plant.const import DEFAULT_HYSYS_CASE_PATH, DEFAULT_TARGET_SM_KMOL_H
from process_sim.plant.convergence import format_plant_convergence_result, run_production_target_convergence
from process_sim.plant.cost.evaluation import evaluate_whole_plant_cost
from process_sim.plant.cost.log import format_whole_plant_cost_report
from process_sim.plant.runner import configure_logging
from process_sim.plant.session_runner import OpenHysysPlantRunner


FAST_COST_REACTOR_MODEL: ReactorModelName = "radial"


def fast_plant_convergence_cost_main() -> None:
    """HYSYS case を開いたまま収束計算、機器読み取り、コスト評価を行う。"""
    configure_logging()
    with OpenHysysPlantRunner(
        case_path=DEFAULT_HYSYS_CASE_PATH,
        reactor_model=FAST_COST_REACTOR_MODEL,
    ) as runner:
        convergence_result = run_production_target_convergence(
            target_sm_kmol_h=DEFAULT_TARGET_SM_KMOL_H,
            production_target_runner=runner,
            convergence_runner=runner,
            reactor_model=FAST_COST_REACTOR_MODEL,
        )
        equipment = runner.read_process_equipment()
    cost_result = evaluate_whole_plant_cost(
        convergence_result=convergence_result,
        equipment=equipment,
    )
    print(format_plant_convergence_result(convergence_result))
    print()
    print(format_whole_plant_cost_report(cost_result))
