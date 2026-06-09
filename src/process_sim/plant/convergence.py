"""Plant recycle convergence runner."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import logging
from pathlib import Path

from process_sim.cli import ReactorModelName
from process_sim.plant.const import (
    DEFAULT_EB_RECYCLE_TOLERANCE_KMOL_H,
    DEFAULT_H2O_RECYCLE_TOLERANCE_KMOL_H,
    DEFAULT_HYSYS_CASE_PATH,
    DEFAULT_PLANT_CONVERGENCE_MAX_ITERATIONS,
    DEFAULT_TARGET_SM_KMOL_H,
)
from process_sim.plant.feed import FreshFeed, build_reactor_feed, reactor_feed_from_plant_stream
from process_sim.plant.models import PlantRunRecord
from process_sim.plant.production_target import (
    EB_COMPONENT_NAME,
    H2O_COMPONENT_NAME,
    FeedTuningOptions,
    FeedTuningResult,
    PlantRunner,
    ReactorCaseLike,
    default_reactor_case_for_model,
    read_sm_product_kmol_h,
    read_valid_stream_component,
    run_plant_once_for_reactor_case,
    tune_fresh_feed_fast,
)
from process_sim.plant.runner import configure_logging
from process_sim.plant.summary import format_final_plant_summary_section
from process_sim.reactor.cases.styrene_radial_default import DEFAULT_STYRENE_RADIAL_REACTOR_CASE
from process_sim.reactor.core.models import ReactorResult
from process_sim.reactor.core.stream import ReactorFeed


logger = logging.getLogger(__name__)
DEFAULT_PLANT_CONVERGENCE_MIN_ITERATIONS = 3  # recycle convergence の最小 iteration 数


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
    reactor_result: ReactorResult | None = None


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
    base_reactor_case: ReactorCaseLike = DEFAULT_STYRENE_RADIAL_REACTOR_CASE,
    plant_runner: PlantRunner | None = None,
    reactor_model: ReactorModelName = "radial",
) -> PlantConvergenceResult:
    """固定 fresh feed と直前 recycle output で recycle loop を収束させる。"""
    run_once = plant_runner or run_plant_once_for_reactor_case(
        case_path=DEFAULT_HYSYS_CASE_PATH,
        hysys_visible=False,
        reactor_model=reactor_model,
    )
    iterations: list[PlantConvergenceIteration] = []
    input_eb_recycle = ReactorFeed(eb=0.0, steam=0.0)
    input_h2o_recycle = ReactorFeed(eb=0.0, steam=0.0)

    for iteration_index in range(1, DEFAULT_PLANT_CONVERGENCE_MAX_ITERATIONS + 1):
        if iteration_index == 1:
            reactor_feed = feed_plan.startup_reactor_feed
        else:
            reactor_feed = build_reactor_feed(
                fresh_feed=feed_plan.steady_fresh_feed,
                eb_recycle=input_eb_recycle,
                water_recycle=input_h2o_recycle,
            )

        plant_record = run_once(replace(base_reactor_case, feed=reactor_feed))
        reactor_result = read_runner_reactor_result(run_once)
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
        output_eb_recycle_feed = reactor_feed_from_plant_stream(plant_record.streams.get("eb_recycle"))
        output_h2o_recycle_feed = reactor_feed_from_plant_stream(plant_record.streams.get("water_recycle"))
        sm_product = read_sm_product_kmol_h(plant_record)

        eb_error = None
        h2o_error = None
        converged = False
        if iteration_index > 1:
            eb_error = output_eb_recycle - input_eb_recycle.eb
            h2o_error = output_h2o_recycle - input_h2o_recycle.steam
            if iteration_index >= DEFAULT_PLANT_CONVERGENCE_MIN_ITERATIONS:
                converged = is_recycle_converged(
                    eb_recycle_error_kmol_h=eb_error,
                    h2o_recycle_error_kmol_h=h2o_error,
                )

        iteration = PlantConvergenceIteration(
            iteration_index=iteration_index,
            reactor_feed=reactor_feed,
            input_eb_recycle_kmol_h=input_eb_recycle.eb,
            input_h2o_recycle_kmol_h=input_h2o_recycle.steam,
            output_eb_recycle_kmol_h=output_eb_recycle,
            output_h2o_recycle_kmol_h=output_h2o_recycle,
            eb_recycle_error_kmol_h=eb_error,
            h2o_recycle_error_kmol_h=h2o_error,
            sm_product_kmol_h=sm_product,
            converged=converged,
            plant_record=plant_record,
            reactor_result=reactor_result,
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

        input_eb_recycle = output_eb_recycle_feed
        input_h2o_recycle = output_h2o_recycle_feed

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
    reactor_model: ReactorModelName = "radial",
    base_reactor_case: ReactorCaseLike | None = None,
    feed_tuning_options: FeedTuningOptions | None = None,
) -> PlantConvergenceResult:
    """Production target で feed 条件を決めてから recycle convergence を実行する。"""
    selected_base_reactor_case = base_reactor_case or default_reactor_case_for_model(reactor_model)
    selected_feed_tuning_options = feed_tuning_options or FeedTuningOptions()
    tuning_result = tune_fresh_feed_fast(
        options=replace(selected_feed_tuning_options, target_sm_kmol_h=target_sm_kmol_h),
        base_reactor_case=selected_base_reactor_case,
        plant_runner=production_target_runner,
        reactor_model=reactor_model,
    )
    feed_plan = feed_plan_from_feed_tuning_result(tuning_result)
    return run_plant_convergence(
        feed_plan=feed_plan,
        base_reactor_case=selected_base_reactor_case,
        plant_runner=convergence_runner,
        reactor_model=reactor_model,
    )


def is_recycle_converged(
    eb_recycle_error_kmol_h: float,
    h2o_recycle_error_kmol_h: float,
) -> bool:
    """Recycle 入出力の自己一致で収束判定する。"""
    return (
        abs(eb_recycle_error_kmol_h) <= DEFAULT_EB_RECYCLE_TOLERANCE_KMOL_H
        and abs(h2o_recycle_error_kmol_h) <= DEFAULT_H2O_RECYCLE_TOLERANCE_KMOL_H
    )


def read_runner_reactor_result(runner: PlantRunner) -> ReactorResult | None:
    """runner が保持している直近の ReactorResult を読む。"""
    value = getattr(runner, "last_reactor_result", None)
    if value is None:
        return None
    if not isinstance(value, ReactorResult):
        raise TypeError("runner.last_reactor_result must be ReactorResult")
    return value


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
            format_final_plant_summary_section(final.plant_record),
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


def parse_plant_convergence_args() -> argparse.Namespace:
    """Plant convergence CLI の引数を読む。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-sm-kmol-h", type=float, default=DEFAULT_TARGET_SM_KMOL_H)
    parser.add_argument(
        "--reactor-model",
        choices=("radial", "pfr"),
        default="radial",
        help="使用する反応器モデル。既定は radial",
    )
    parser.add_argument("--case-path", type=Path, default=DEFAULT_HYSYS_CASE_PATH)
    return parser.parse_args()


def run_plant_convergence_main() -> None:
    """Production target 由来の条件で plant recycle convergence を実行する。"""
    configure_logging()
    args = parse_plant_convergence_args()
    runner = run_plant_once_for_reactor_case(
        case_path=args.case_path,
        hysys_visible=False,
        reactor_model=args.reactor_model,
    )
    result = run_production_target_convergence(
        target_sm_kmol_h=args.target_sm_kmol_h,
        production_target_runner=runner,
        convergence_runner=runner,
        reactor_model=args.reactor_model,
    )
    print(format_plant_convergence_result(result))


if __name__ == "__main__":
    run_plant_convergence_main()
