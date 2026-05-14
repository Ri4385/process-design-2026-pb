"""Plant recycle convergence runner."""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging

from process_sim.plant.const import (
    DEFAULT_EB_RECYCLE_TOLERANCE_KMOL_H,
    DEFAULT_H2O_RECYCLE_TOLERANCE_KMOL_H,
    DEFAULT_HYSYS_CASE_PATH,
    DEFAULT_PLANT_CONVERGENCE_MAX_ITERATIONS,
    DEFAULT_TARGET_SM_KMOL_H,
)
from process_sim.plant.feed import FreshFeed, build_reactor_feed
from process_sim.plant.models import PlantRunRecord
from process_sim.plant.production_target import (
    EB_COMPONENT_NAME,
    H2O_COMPONENT_NAME,
    FeedTuningOptions,
    FeedTuningResult,
    PlantRunner,
    read_sm_product_kmol_h,
    read_valid_stream_component,
    run_plant_once_for_reactor_case,
    tune_fresh_feed_fast,
)
from process_sim.plant.runner import configure_logging
from process_sim.plant.summary import format_plant_run_summary
from process_sim.reactor.cases.styrene_default import DEFAULT_STYRENE_REACTOR_CASE, ReactorCase
from process_sim.reactor.core.stream import ReactorFeed


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlantFeedPlan:
    """Recycle convergence に渡す feed 条件。"""

    startup_reactor_feed: ReactorFeed
    steady_fresh_feed: FreshFeed


@dataclass(frozen=True)
class PlantConvergenceIteration:
    """Recycle convergence の1 iteration 記録。"""

    iteration_index: int
    reactor_feed: ReactorFeed
    input_eb_recycle_kmol_h: float
    input_h2o_recycle_kmol_h: float
    output_eb_recycle_kmol_h: float
    output_h2o_recycle_kmol_h: float
    eb_recycle_error_kmol_h: float | None
    h2o_recycle_error_kmol_h: float | None
    sm_product_kmol_h: float
    converged: bool
    plant_record: PlantRunRecord


@dataclass(frozen=True)
class PlantConvergenceResult:
    """Recycle convergence の結果。"""

    converged: bool
    feed_plan: PlantFeedPlan
    iterations: tuple[PlantConvergenceIteration, ...]

    @property
    def final_iteration(self) -> PlantConvergenceIteration:
        """最後の iteration を返す。"""
        return self.iterations[-1]


def feed_plan_from_feed_tuning_result(result: FeedTuningResult) -> PlantFeedPlan:
    """Production target の最終 run から convergence 用 feed plan を作る。"""
    if not result.converged:
        raise ValueError("feed tuning result is not converged")
    final_run = result.runs[-1]
    return PlantFeedPlan(
        startup_reactor_feed=final_run.reactor_feed,
        steady_fresh_feed=final_run.fresh_feed,
    )


def run_plant_convergence(
    feed_plan: PlantFeedPlan,
    base_reactor_case: ReactorCase = DEFAULT_STYRENE_REACTOR_CASE,
    plant_runner: PlantRunner | None = None,
) -> PlantConvergenceResult:
    """固定 fresh feed と直前 recycle output で recycle loop を収束させる。"""
    run_once = plant_runner or run_plant_once_for_reactor_case(
        case_path=DEFAULT_HYSYS_CASE_PATH,
        hysys_visible=False,
    )
    iterations: list[PlantConvergenceIteration] = []
    input_eb_recycle = 0.0
    input_h2o_recycle = 0.0

    for iteration_index in range(1, DEFAULT_PLANT_CONVERGENCE_MAX_ITERATIONS + 1):
        if iteration_index == 1:
            reactor_feed = feed_plan.startup_reactor_feed
        else:
            reactor_feed = build_reactor_feed(
                fresh_feed=feed_plan.steady_fresh_feed,
                eb_recycle=ReactorFeed(eb=input_eb_recycle, steam=0.0),
                water_recycle=ReactorFeed(eb=0.0, steam=input_h2o_recycle),
            )

        plant_record = run_once(replace(base_reactor_case, feed=reactor_feed))
        output_eb_recycle = read_valid_stream_component(
            plant_record=plant_record,
            stream_name="eb_recycle",
            component_name=EB_COMPONENT_NAME,
        )
        output_h2o_recycle = read_valid_stream_component(
            plant_record=plant_record,
            stream_name="water_recycle",
            component_name=H2O_COMPONENT_NAME,
        )
        sm_product = read_sm_product_kmol_h(plant_record)

        eb_error = None
        h2o_error = None
        converged = False
        if iteration_index > 1:
            eb_error = output_eb_recycle - input_eb_recycle
            h2o_error = output_h2o_recycle - input_h2o_recycle
            converged = is_recycle_converged(
                eb_recycle_error_kmol_h=eb_error,
                h2o_recycle_error_kmol_h=h2o_error,
            )

        iteration = PlantConvergenceIteration(
            iteration_index=iteration_index,
            reactor_feed=reactor_feed,
            input_eb_recycle_kmol_h=input_eb_recycle,
            input_h2o_recycle_kmol_h=input_h2o_recycle,
            output_eb_recycle_kmol_h=output_eb_recycle,
            output_h2o_recycle_kmol_h=output_h2o_recycle,
            eb_recycle_error_kmol_h=eb_error,
            h2o_recycle_error_kmol_h=h2o_error,
            sm_product_kmol_h=sm_product,
            converged=converged,
            plant_record=plant_record,
        )
        iterations.append(iteration)
        logger.info("\n%s", format_plant_convergence_table(tuple(iterations)))

        if converged:
            result = PlantConvergenceResult(
                converged=True,
                feed_plan=feed_plan,
                iterations=tuple(iterations),
            )
            logger.info("\n%s", format_plant_convergence_result(result))
            return result

        input_eb_recycle = output_eb_recycle
        input_h2o_recycle = output_h2o_recycle

    result = PlantConvergenceResult(
        converged=False,
        feed_plan=feed_plan,
        iterations=tuple(iterations),
    )
    logger.info("\n%s", format_plant_convergence_result(result))
    return result


def run_fixed_feed_convergence(
    feed_plan: PlantFeedPlan,
    plant_runner: PlantRunner | None = None,
) -> PlantConvergenceResult:
    """ユーザー定義の feed plan で recycle convergence を実行する。"""
    return run_plant_convergence(feed_plan=feed_plan, plant_runner=plant_runner)


def run_production_target_convergence(
    target_sm_kmol_h: float = DEFAULT_TARGET_SM_KMOL_H,
    production_target_runner: PlantRunner | None = None,
    convergence_runner: PlantRunner | None = None,
) -> PlantConvergenceResult:
    """Production target で feed 条件を決めてから recycle convergence を実行する。"""
    tuning_result = tune_fresh_feed_fast(
        options=FeedTuningOptions(target_sm_kmol_h=target_sm_kmol_h),
        plant_runner=production_target_runner,
    )
    feed_plan = feed_plan_from_feed_tuning_result(tuning_result)
    return run_plant_convergence(feed_plan=feed_plan, plant_runner=convergence_runner)


def is_recycle_converged(
    eb_recycle_error_kmol_h: float,
    h2o_recycle_error_kmol_h: float,
) -> bool:
    """Recycle 入出力の自己一致で収束判定する。"""
    return (
        abs(eb_recycle_error_kmol_h) <= DEFAULT_EB_RECYCLE_TOLERANCE_KMOL_H
        and abs(h2o_recycle_error_kmol_h) <= DEFAULT_H2O_RECYCLE_TOLERANCE_KMOL_H
    )


def format_plant_convergence_result(result: PlantConvergenceResult) -> str:
    """PlantConvergenceResult を人間向けに整形する。"""
    status = "converged" if result.converged else "not converged"
    final = result.final_iteration
    return "\n".join(
        [
            "Plant Convergence Summary",
            f"status: {status}",
            f"final iteration: {final.iteration_index}",
            f"final reactor EB: {final.reactor_feed.eb:.3f} kmol/h",
            f"final reactor H2O: {final.reactor_feed.steam:.3f} kmol/h",
            f"final SM product: {final.sm_product_kmol_h:.3f} kmol/h",
            "",
            format_plant_convergence_table(result.iterations),
            "",
            "[Final Plant Summary]",
            format_plant_run_summary(final.plant_record),
        ]
    )


def format_plant_convergence_table(iterations: tuple[PlantConvergenceIteration, ...]) -> str:
    """Recycle convergence の累積表を返す。"""
    lines = [
        "[Plant Recycle Convergence]",
        f"{'iter':>4} {'comp':>4} {'reactor':>10} {'input':>10} {'output':>10} "
        f"{'error':>10} {'tol':>8} {'SM':>10} {'conv':>5}",
    ]
    for iteration in iterations:
        lines.append(
            format_convergence_component_row(
                iteration=iteration,
                component_label="EB",
                reactor_flow_kmol_h=iteration.reactor_feed.eb,
                input_recycle_kmol_h=iteration.input_eb_recycle_kmol_h,
                output_recycle_kmol_h=iteration.output_eb_recycle_kmol_h,
                recycle_error_kmol_h=iteration.eb_recycle_error_kmol_h,
                tolerance_kmol_h=DEFAULT_EB_RECYCLE_TOLERANCE_KMOL_H,
            )
        )
        lines.append(
            format_convergence_component_row(
                iteration=iteration,
                component_label="H2O",
                reactor_flow_kmol_h=iteration.reactor_feed.steam,
                input_recycle_kmol_h=iteration.input_h2o_recycle_kmol_h,
                output_recycle_kmol_h=iteration.output_h2o_recycle_kmol_h,
                recycle_error_kmol_h=iteration.h2o_recycle_error_kmol_h,
                tolerance_kmol_h=DEFAULT_H2O_RECYCLE_TOLERANCE_KMOL_H,
            )
        )
    return "\n".join(lines)


def format_convergence_component_row(
    iteration: PlantConvergenceIteration,
    component_label: str,
    reactor_flow_kmol_h: float,
    input_recycle_kmol_h: float,
    output_recycle_kmol_h: float,
    recycle_error_kmol_h: float | None,
    tolerance_kmol_h: float,
) -> str:
    """1成分分の recycle convergence 表行を返す。"""
    return (
        f"{iteration.iteration_index:>4} "
        f"{component_label:>4} "
        f"{reactor_flow_kmol_h:>10.3f} "
        f"{input_recycle_kmol_h:>10.3f} "
        f"{output_recycle_kmol_h:>10.3f} "
        f"{format_optional_float(recycle_error_kmol_h):>10} "
        f"{tolerance_kmol_h:>8.3f} "
        f"{iteration.sm_product_kmol_h:>10.3f} "
        f"{'yes' if iteration.converged else 'no':>5}"
    )


def format_optional_float(value: float | None) -> str:
    """None を含む数値を表形式にする。"""
    if value is None:
        return "n/a"
    return f"{value:+.3f}"


def run_plant_convergence_main() -> None:
    """Production target 由来の条件で plant recycle convergence を実行する。"""
    configure_logging()
    result = run_production_target_convergence()
    print(format_plant_convergence_result(result))


if __name__ == "__main__":
    run_plant_convergence_main()
