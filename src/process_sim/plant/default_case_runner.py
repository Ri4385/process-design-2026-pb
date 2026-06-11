"""Default plant case の cost 評価 runner。"""

from __future__ import annotations

from process_sim.optimization.separator.hysys_controls import (
    build_separator_control_plan,
    merge_hysys_control_plans,
)
from process_sim.optimization.separator.parameters import SeparatorOperatingCandidate
from process_sim.plant.cases.default import DEFAULT_CASE
from process_sim.plant.cases.models import DefaultCase, SeparatorCondition
from process_sim.plant.const import DEFAULT_HYSYS_CASE_PATH, DEFAULT_TARGET_SM_KMOL_H
from process_sim.plant.convergence import (
    format_plant_convergence_result,
    run_production_target_convergence,
)
from process_sim.plant.cost.evaluation import evaluate_whole_plant_cost
from process_sim.plant.cost.log import format_whole_plant_cost_report
from process_sim.plant.cost.models import WholePlantCostResult
from process_sim.plant.hysys_controls import build_inlet_control_plan
from process_sim.plant.production_target import (
    FeedTuningOptions,
    InitialRecycleGuessPolicy,
)
from process_sim.plant.runner import configure_logging
from process_sim.plant.session_runner import OpenHysysPlantRunner


def run_default_cost(case: DefaultCase = DEFAULT_CASE) -> WholePlantCostResult:
    """default plant 条件で収束計算と cost 評価を行う。"""
    feed_tuning_options = FeedTuningOptions(
        initial_guess_policy=InitialRecycleGuessPolicy(
            steam_to_eb_ratio=case.steam_to_eb_ratio,
        ),
    )
    with OpenHysysPlantRunner(
        case_path=DEFAULT_HYSYS_CASE_PATH,
        reactor_model="radial",
    ) as runner:
        convergence_result = run_production_target_convergence(
            target_sm_kmol_h=DEFAULT_TARGET_SM_KMOL_H,
            production_target_runner=runner,
            convergence_runner=runner,
            reactor_model="radial",
            base_reactor_case=case.reactor,
            feed_tuning_options=feed_tuning_options,
        )
        runner.apply_post_convergence_controls(
            merge_hysys_control_plans(
                build_inlet_control_plan(
                    convergence_result=convergence_result,
                    base_reactor_case=case.reactor,
                ),
                build_separator_control_plan(
                    separator_candidate_from_condition(case.separator)
                ),
            )
        )
        equipment = runner.read_process_equipment()
    cost_result = evaluate_whole_plant_cost(
        convergence_result=convergence_result,
        equipment=equipment,
    )
    print(format_plant_convergence_result(convergence_result))
    print()
    print(format_whole_plant_cost_report(cost_result))
    return cost_result


def separator_candidate_from_condition(
    condition: SeparatorCondition,
) -> SeparatorOperatingCandidate:
    """default case の分離器条件を既存 HYSYS control 用 model へ変換する。"""
    return SeparatorOperatingCandidate(
        decanter_1_temperature_c=condition.decanter_1_temperature_c,
        sm_column_reflux_ratio=condition.sm_column_reflux_ratio,
    )


def run_default_cost_main() -> None:
    """CLI から default plant cost 評価を実行する。"""
    configure_logging()
    run_default_cost()
