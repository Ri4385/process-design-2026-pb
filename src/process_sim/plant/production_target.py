"""Fast fresh-feed tuning for a target SM production rate."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import logging
from pathlib import Path
from typing import Callable

from process_sim.cli import ReactorModelName
from process_sim.plant.feed import (
    FreshFeed,
    FreshFeedPolicy,
    build_reactor_feed,
    reactor_feed_from_plant_stream,
)
from process_sim.plant.const import (
    DEFAULT_EB_RECYCLE_TOLERANCE_KMOL_H,
    DEFAULT_H2O_RECYCLE_TOLERANCE_KMOL_H,
    DEFAULT_HYSYS_CASE_PATH,
    DEFAULT_SM_MARGIN_TOLERANCE_KMOL_H,
    DEFAULT_SM_PRODUCT_STYRENE_MOL_FRACTION,
    DEFAULT_TARGET_SM_KMOL_H,
    FLOAT_ABS_TOLERANCE,
    HYSYS_INVALID_SENTINEL,
)
from process_sim.plant.models import PlantRunRecord, PlantStreamRecord
from process_sim.plant.runner import configure_logging, run_plant_once
from process_sim.plant.summary import format_final_plant_summary_section
from process_sim.reactor.cases.styrene_radial_default import DEFAULT_STYRENE_RADIAL_REACTOR_CASE, RadialReactorCase
from process_sim.reactor.cases.styrene_default import DEFAULT_STYRENE_REACTOR_CASE, ReactorCase
from process_sim.reactor.core.stream import ReactorFeed


EB_COMPONENT_NAME = "E-Benzene"
H2O_COMPONENT_NAME = "H2O"
DEFAULT_SINGLE_PASS_SM_YIELD_FROM_EB = 0.50  # 初期値生成用の EB 基準 SM 単通収率
DEFAULT_EB_RECYCLE_FRACTION = 0.99  # 初期値生成用の未反応 EB recycle 率
DEFAULT_H2O_RECYCLE_FRACTION = 0.99  # 初期値生成用の H2O recycle 率
DEFAULT_STEAM_TO_EB_RATIO = 5.0  # 初期値生成用の reactor inlet H2O/EB 比
DEFAULT_MAX_RUNS = 5  # feed tuning 最大実行回数
DEFAULT_MIN_RUNS = 1  # feed tuning 最小実行回数


ReactorCaseLike = ReactorCase | RadialReactorCase
PlantRunner = Callable[[ReactorCaseLike], PlantRunRecord]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InitialRecycleGuessPolicy:
    """目標 SM 流量から初期 fresh/recycle を作るための仮定。"""

    single_pass_sm_yield_from_eb: float = DEFAULT_SINGLE_PASS_SM_YIELD_FROM_EB
    eb_recycle_fraction: float = DEFAULT_EB_RECYCLE_FRACTION
    h2o_recycle_fraction: float = DEFAULT_H2O_RECYCLE_FRACTION
    steam_to_eb_ratio: float = DEFAULT_STEAM_TO_EB_RATIO


@dataclass(frozen=True)
class InitialFeedGuess:
    """初回 plant run に使う fresh feed と recycle 初期値。"""

    fresh_feed: FreshFeed
    eb_recycle: ReactorFeed
    water_recycle: ReactorFeed
    reactor_feed: ReactorFeed
    reactor_inlet_eb_kmol_h: float
    reactor_inlet_h2o_kmol_h: float
    unreacted_eb_kmol_h: float
    fresh_eb_kmol_h: float
    recycle_eb_kmol_h: float
    fresh_h2o_kmol_h: float
    recycle_h2o_kmol_h: float


@dataclass(frozen=True)
class FeedTuningOptions:
    """高速 feed 調整の設定。"""

    target_sm_kmol_h: float = DEFAULT_TARGET_SM_KMOL_H
    max_runs: int = DEFAULT_MAX_RUNS
    min_runs: int = DEFAULT_MIN_RUNS
    sm_tolerance_kmol_h: float = DEFAULT_SM_MARGIN_TOLERANCE_KMOL_H
    eb_recycle_tolerance_kmol_h: float = DEFAULT_EB_RECYCLE_TOLERANCE_KMOL_H
    h2o_recycle_tolerance_kmol_h: float = DEFAULT_H2O_RECYCLE_TOLERANCE_KMOL_H
    max_feed_step_fraction: float = 0.3
    feed_policy: FreshFeedPolicy = FreshFeedPolicy()
    initial_guess_policy: InitialRecycleGuessPolicy = InitialRecycleGuessPolicy()


@dataclass(frozen=True)
class FeedTuningRun:
    """feed 調整の1実行分の記録。"""

    run_index: int
    fresh_feed: FreshFeed
    reactor_feed: ReactorFeed
    input_eb_recycle_kmol_h: float
    input_h2o_recycle_kmol_h: float
    output_eb_recycle_kmol_h: float
    output_h2o_recycle_kmol_h: float
    eb_recycle_error_kmol_h: float
    h2o_recycle_error_kmol_h: float
    converged: bool
    sm_product_kmol_h: float
    sm_error_kmol_h: float
    plant_record: PlantRunRecord


@dataclass(frozen=True)
class FeedTuningResult:
    """feed 調整の結果。"""

    target_sm_kmol_h: float
    sm_tolerance_kmol_h: float
    eb_recycle_tolerance_kmol_h: float
    h2o_recycle_tolerance_kmol_h: float
    converged: bool
    runs: tuple[FeedTuningRun, ...]

    @property
    def best_run(self) -> FeedTuningRun:
        """目標 SM 流量に最も近い実行を返す。"""
        return min(self.runs, key=lambda run: abs(run.sm_error_kmol_h))


def default_reactor_case_for_model(reactor_model: ReactorModelName) -> ReactorCaseLike:
    """反応器モデル名に対応する既定ケースを返す。"""
    if reactor_model == "radial":
        return DEFAULT_STYRENE_RADIAL_REACTOR_CASE
    return DEFAULT_STYRENE_REACTOR_CASE


def run_plant_once_for_reactor_case(
    case_path: Path,
    hysys_visible: bool,
    reactor_model: ReactorModelName = "radial",
) -> PlantRunner:
    """既存 runner を FeedTuning 用の callable に包む。"""

    def _run(reactor_case: ReactorCaseLike) -> PlantRunRecord:
        return run_plant_once(
            case_path=case_path,
            reactor_case=reactor_case,
            reactor_model=reactor_model,
            hysys_visible=hysys_visible,
            log_reactor_detail=False,
        )

    return _run


def tune_fresh_feed_fast(
    options: FeedTuningOptions = FeedTuningOptions(),
    base_reactor_case: ReactorCaseLike = DEFAULT_STYRENE_RADIAL_REACTOR_CASE,
    plant_runner: PlantRunner | None = None,
    reactor_model: ReactorModelName = "radial",
) -> FeedTuningResult:
    """初期値と直前 run の実効係数から fresh/recycle を更新する。"""
    if options.max_runs < 1:
        raise ValueError("max_runs must be at least 1")
    if options.min_runs < 1:
        raise ValueError("min_runs must be at least 1")
    if options.min_runs > options.max_runs:
        raise ValueError("min_runs must be less than or equal to max_runs")

    run_once = plant_runner or run_plant_once_for_reactor_case(
        case_path=DEFAULT_HYSYS_CASE_PATH,
        hysys_visible=False,
        reactor_model=reactor_model,
    )
    initial_guess = build_initial_feed_guess(
        target_sm_kmol_h=options.target_sm_kmol_h,
        feed_policy=options.feed_policy,
        guess_policy=options.initial_guess_policy,
    )
    runs: list[FeedTuningRun] = []
    fresh_feed = initial_guess.fresh_feed
    eb_recycle = initial_guess.eb_recycle
    water_recycle = initial_guess.water_recycle
    logger.info(
        "feed tuning settings: target SM %.3f kmol/h, SM tolerance %.3f kmol/h, "
        "EB recycle tolerance %.3f kmol/h, H2O recycle tolerance %.3f kmol/h, min runs %d, max runs %d",
        options.target_sm_kmol_h,
        options.sm_tolerance_kmol_h,
        options.eb_recycle_tolerance_kmol_h,
        options.h2o_recycle_tolerance_kmol_h,
        options.min_runs,
        options.max_runs,
    )
    logger.info(
        "initial feed guess: fresh EB %.3f kmol/h, recycle EB %.3f kmol/h, "
        "fresh H2O %.3f kmol/h, recycle H2O %.3f kmol/h",
        initial_guess.fresh_eb_kmol_h,
        initial_guess.recycle_eb_kmol_h,
        initial_guess.fresh_h2o_kmol_h,
        initial_guess.recycle_h2o_kmol_h,
    )

    for run_index in range(1, options.max_runs + 1):
        reactor_feed = build_reactor_feed(
            fresh_feed=fresh_feed,
            eb_recycle=eb_recycle,
            water_recycle=water_recycle,
            policy=options.feed_policy,
        )
        reactor_case = replace(base_reactor_case, feed=reactor_feed)
        plant_record = run_once(reactor_case)
        sm_product_kmol_h = read_sm_product_kmol_h(plant_record)
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
        eb_recycle_error = output_eb_recycle - eb_recycle.eb
        h2o_recycle_error = output_h2o_recycle - water_recycle.steam
        sm_error = sm_product_kmol_h - options.target_sm_kmol_h
        converged = is_converged(
            sm_margin_kmol_h=sm_error,
            eb_recycle_error_kmol_h=eb_recycle_error,
            h2o_recycle_error_kmol_h=h2o_recycle_error,
            options=options,
        )
        run = FeedTuningRun(
            run_index=run_index,
            fresh_feed=fresh_feed,
            reactor_feed=reactor_feed,
            input_eb_recycle_kmol_h=eb_recycle.eb,
            input_h2o_recycle_kmol_h=water_recycle.steam,
            output_eb_recycle_kmol_h=output_eb_recycle,
            output_h2o_recycle_kmol_h=output_h2o_recycle,
            eb_recycle_error_kmol_h=eb_recycle_error,
            h2o_recycle_error_kmol_h=h2o_recycle_error,
            converged=converged,
            sm_product_kmol_h=sm_product_kmol_h,
            sm_error_kmol_h=sm_error,
            plant_record=plant_record,
        )
        runs.append(run)
        logger.info("\n%s", format_cumulative_run_tables(tuple(runs), options))

        if run_index >= options.min_runs and run.converged:
            logger.info("feed tuning converged in %d runs", run_index)
            return FeedTuningResult(
                target_sm_kmol_h=options.target_sm_kmol_h,
                sm_tolerance_kmol_h=options.sm_tolerance_kmol_h,
                eb_recycle_tolerance_kmol_h=options.eb_recycle_tolerance_kmol_h,
                h2o_recycle_tolerance_kmol_h=options.h2o_recycle_tolerance_kmol_h,
                converged=True,
                runs=tuple(runs),
            )

        if run_index < options.max_runs:
            fresh_feed, eb_recycle, water_recycle = estimate_next_feed_from_run(
                run=run,
                target_sm_kmol_h=options.target_sm_kmol_h,
                feed_policy=options.feed_policy,
            )

    logger.info("feed tuning did not converge in %d runs", options.max_runs)
    return FeedTuningResult(
        target_sm_kmol_h=options.target_sm_kmol_h,
        sm_tolerance_kmol_h=options.sm_tolerance_kmol_h,
        eb_recycle_tolerance_kmol_h=options.eb_recycle_tolerance_kmol_h,
        h2o_recycle_tolerance_kmol_h=options.h2o_recycle_tolerance_kmol_h,
        converged=False,
        runs=tuple(runs),
    )


def build_initial_feed_guess(
    target_sm_kmol_h: float,
    feed_policy: FreshFeedPolicy = FreshFeedPolicy(),
    guess_policy: InitialRecycleGuessPolicy = InitialRecycleGuessPolicy(),
) -> InitialFeedGuess:
    """目標 SM 流量と比率仮定から初期 fresh/recycle を作る。"""
    validate_initial_guess_policy(guess_policy)
    if target_sm_kmol_h <= 0.0:
        raise ValueError("target_sm_kmol_h must be positive")
    if feed_policy.eb_mol_fraction <= 0.0:
        raise ValueError("feed_policy.eb_mol_fraction must be positive")

    target_styrene_kmol_h = target_sm_kmol_h * DEFAULT_SM_PRODUCT_STYRENE_MOL_FRACTION
    reactor_inlet_eb = target_styrene_kmol_h / guess_policy.single_pass_sm_yield_from_eb
    unreacted_eb = reactor_inlet_eb * (1.0 - guess_policy.single_pass_sm_yield_from_eb)
    recycle_eb = unreacted_eb * guess_policy.eb_recycle_fraction
    fresh_eb = reactor_inlet_eb - recycle_eb
    reactor_inlet_h2o = reactor_inlet_eb * guess_policy.steam_to_eb_ratio
    recycle_h2o = reactor_inlet_h2o * guess_policy.h2o_recycle_fraction
    fresh_h2o = reactor_inlet_h2o - recycle_h2o

    fresh_feed = FreshFeed(
        hydrocarbon_kmol_h=fresh_eb / feed_policy.eb_mol_fraction,
        steam_kmol_h=fresh_h2o,
    )
    eb_recycle = ReactorFeed(eb=recycle_eb, steam=0.0)
    water_recycle = ReactorFeed(eb=0.0, steam=recycle_h2o)
    reactor_feed = build_reactor_feed(
        fresh_feed=fresh_feed,
        eb_recycle=eb_recycle,
        water_recycle=water_recycle,
        policy=feed_policy,
    )
    return InitialFeedGuess(
        fresh_feed=fresh_feed,
        eb_recycle=eb_recycle,
        water_recycle=water_recycle,
        reactor_feed=reactor_feed,
        reactor_inlet_eb_kmol_h=reactor_inlet_eb,
        reactor_inlet_h2o_kmol_h=reactor_inlet_h2o,
        unreacted_eb_kmol_h=unreacted_eb,
        fresh_eb_kmol_h=fresh_eb,
        recycle_eb_kmol_h=recycle_eb,
        fresh_h2o_kmol_h=fresh_h2o,
        recycle_h2o_kmol_h=recycle_h2o,
    )


def validate_initial_guess_policy(policy: InitialRecycleGuessPolicy) -> None:
    """初期値生成用の比率が計算可能な範囲にあることを確認する。"""
    if not 0.0 < policy.single_pass_sm_yield_from_eb < 1.0:
        raise ValueError("single_pass_sm_yield_from_eb must be between 0 and 1")
    if not 0.0 <= policy.eb_recycle_fraction <= 1.0:
        raise ValueError("eb_recycle_fraction must be between 0 and 1")
    if not 0.0 <= policy.h2o_recycle_fraction <= 1.0:
        raise ValueError("h2o_recycle_fraction must be between 0 and 1")
    if policy.steam_to_eb_ratio <= 0.0:
        raise ValueError("steam_to_eb_ratio must be positive")


def is_valid_recycle_stream(stream: PlantStreamRecord | None, major_component_name: str) -> bool:
    """HYSYS 異常値を recycle 入力に使わないための簡易検査。"""
    if stream is None or not is_valid_flow(stream.total_molar_flow_kmol_h):
        return False
    return is_valid_flow(stream.component_molar_flow_kmol_h.get(major_component_name))


def is_valid_flow(value: float | None) -> bool:
    """HYSYS の欠損値、負値、異常 sentinel を除外する。"""
    if value is None or value < 0.0:
        return False
    return abs(value - HYSYS_INVALID_SENTINEL) > 1e-6


def read_valid_stream_component(
    plant_record: PlantRunRecord,
    stream_name: str,
    component_name: str,
) -> float:
    """stream 主要成分を読み、HYSYS 異常値なら停止する。"""
    stream = plant_record.streams.get(stream_name)
    if stream is None:
        raise ValueError(f"{stream_name} stream is missing")
    if not is_valid_flow(stream.total_molar_flow_kmol_h):
        raise ValueError(f"{stream_name} total flow is invalid: {stream.total_molar_flow_kmol_h}")
    value = stream.component_molar_flow_kmol_h.get(component_name)
    if value is None or not is_valid_flow(value):
        raise ValueError(f"{stream_name} {component_name} flow is invalid: {value}")
    return value


def estimate_next_feed_from_run(
    run: FeedTuningRun,
    target_sm_kmol_h: float,
    feed_policy: FreshFeedPolicy,
) -> tuple[FreshFeed, ReactorFeed, ReactorFeed]:
    """直前 run の実効収率と回収率を固定して次回 feed/recycle を推定する。"""
    reactor_outlet_eb = read_valid_stream_component(
        plant_record=run.plant_record,
        stream_name="reactor_outlet",
        component_name=EB_COMPONENT_NAME,
    )
    reactor_outlet_h2o = read_valid_stream_component(
        plant_record=run.plant_record,
        stream_name="reactor_outlet",
        component_name=H2O_COMPONENT_NAME,
    )
    require_positive(run.reactor_feed.eb, "reactor inlet EB")
    require_positive(run.reactor_feed.steam, "reactor inlet H2O")
    require_positive(run.sm_product_kmol_h, "SM product")
    require_positive(reactor_outlet_eb, "reactor outlet EB")
    require_positive(reactor_outlet_h2o, "reactor outlet H2O")

    sm_product_yield = run.sm_product_kmol_h / run.reactor_feed.eb
    eb_unreacted_fraction = reactor_outlet_eb / run.reactor_feed.eb
    eb_recycle_recovery = run.output_eb_recycle_kmol_h / reactor_outlet_eb
    steam_to_eb_ratio = run.reactor_feed.steam / run.reactor_feed.eb
    h2o_remaining_fraction = reactor_outlet_h2o / run.reactor_feed.steam
    h2o_recycle_recovery = run.output_h2o_recycle_kmol_h / reactor_outlet_h2o

    require_positive(sm_product_yield, "EB-based SM product yield")
    require_fraction(eb_unreacted_fraction, "EB unreacted fraction")
    require_fraction(eb_recycle_recovery, "EB recycle recovery")
    require_positive(steam_to_eb_ratio, "steam to EB ratio")
    require_fraction(h2o_remaining_fraction, "H2O remaining fraction")
    require_fraction(h2o_recycle_recovery, "H2O recycle recovery")

    next_reactor_eb = target_sm_kmol_h / sm_product_yield
    next_reactor_outlet_eb = next_reactor_eb * eb_unreacted_fraction
    next_recycle_eb = next_reactor_outlet_eb * eb_recycle_recovery
    next_fresh_eb = next_reactor_eb - next_recycle_eb

    next_reactor_h2o = next_reactor_eb * steam_to_eb_ratio
    next_reactor_outlet_h2o = next_reactor_h2o * h2o_remaining_fraction
    next_recycle_h2o = next_reactor_outlet_h2o * h2o_recycle_recovery
    next_fresh_h2o = next_reactor_h2o - next_recycle_h2o

    require_positive(next_fresh_eb, "next fresh EB")
    require_positive(next_fresh_h2o, "next fresh H2O")
    fresh_feed = FreshFeed(
        hydrocarbon_kmol_h=next_fresh_eb / feed_policy.eb_mol_fraction,
        steam_kmol_h=next_fresh_h2o,
    )
    next_eb_recycle = scale_reactor_feed_to_component(
        feed=reactor_feed_from_plant_stream(run.plant_record.streams.get("eb_recycle")),
        component_name="eb",
        target_component_kmol_h=next_recycle_eb,
    )
    next_h2o_recycle = scale_reactor_feed_to_component(
        feed=reactor_feed_from_plant_stream(run.plant_record.streams.get("water_recycle")),
        component_name="steam",
        target_component_kmol_h=next_recycle_h2o,
    )
    return (
        fresh_feed,
        next_eb_recycle,
        next_h2o_recycle,
    )


def scale_reactor_feed_to_component(
    feed: ReactorFeed,
    component_name: str,
    target_component_kmol_h: float,
) -> ReactorFeed:
    """指定成分が目標流量になるように recycle feed 全体を比例調整する。"""
    current_component_kmol_h = getattr(feed, component_name)
    require_positive(current_component_kmol_h, f"current recycle {component_name}")
    factor = target_component_kmol_h / current_component_kmol_h
    return ReactorFeed(
        **{
            name: value * factor
            for name, value in feed.to_component_flows_kmol_h().items()
        }
    )


def require_positive(value: float, label: str) -> None:
    """正の値でない場合に停止する。"""
    if value <= 0.0:
        raise ValueError(f"{label} must be positive: {value}")


def require_fraction(value: float, label: str) -> None:
    """比率が 0 以上 1 以下でない場合に停止する。"""
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{label} must be between 0 and 1: {value}")


def is_converged(
    sm_margin_kmol_h: float,
    eb_recycle_error_kmol_h: float,
    h2o_recycle_error_kmol_h: float,
    options: FeedTuningOptions,
) -> bool:
    """SM 過不足と recycle 自己一致で収束判定する。"""
    return (
        -FLOAT_ABS_TOLERANCE
        <= sm_margin_kmol_h
        <= options.sm_tolerance_kmol_h + FLOAT_ABS_TOLERANCE
        and abs(eb_recycle_error_kmol_h) <= options.eb_recycle_tolerance_kmol_h
        and abs(h2o_recycle_error_kmol_h) <= options.h2o_recycle_tolerance_kmol_h
    )


def read_sm_product_kmol_h(record: PlantRunRecord) -> float:
    """PlantRunRecord から SM product の total 流量を読む。"""
    sm_product = record.streams.get("sm_product")
    if sm_product is None:
        raise ValueError("sm_product stream is missing")

    value = sm_product.total_molar_flow_kmol_h
    if value is None or not is_valid_flow(value):
        raise ValueError(f"sm_product total flow is invalid: {value}")
    return value


def next_secant_feed_value(runs: list[FeedTuningRun], options: FeedTuningOptions) -> float:
    """直近2点から次の fresh hydrocarbon feed を予測する。"""
    previous = runs[-2]
    current = runs[-1]
    sm_delta = current.sm_product_kmol_h - previous.sm_product_kmol_h

    if abs(sm_delta) < 1e-9:
        predicted = current.fresh_feed.hydrocarbon_kmol_h
    else:
        predicted = current.fresh_feed.hydrocarbon_kmol_h + (
            (options.target_sm_kmol_h - current.sm_product_kmol_h)
            * (current.fresh_feed.hydrocarbon_kmol_h - previous.fresh_feed.hydrocarbon_kmol_h)
            / sm_delta
        )

    return limited_feed_step(
        current_feed_kmol_h=current.fresh_feed.hydrocarbon_kmol_h,
        predicted_feed_kmol_h=predicted,
        max_step_fraction=options.max_feed_step_fraction,
    )


def limited_feed_step(
    current_feed_kmol_h: float,
    predicted_feed_kmol_h: float,
    max_step_fraction: float,
) -> float:
    """secant 予測値が飛びすぎないように制限する。"""
    if max_step_fraction <= 0.0:
        raise ValueError("max_step_fraction must be positive")

    lower = current_feed_kmol_h * (1.0 - max_step_fraction)
    upper = current_feed_kmol_h * (1.0 + max_step_fraction)
    return max(lower, min(upper, max(predicted_feed_kmol_h, 1e-9)))


def format_feed_tuning_result(result: FeedTuningResult) -> str:
    """FeedTuningResult を人間向けに整形する。"""
    status = "converged" if result.converged else "not converged"
    final = result.runs[-1]
    lines = [
        "Feed Tuning Summary",
        f"status: {status}",
        f"target SM: {result.target_sm_kmol_h:.3f} kmol/h",
        f"final run: {final.run_index}",
        f"final fresh hydrocarbon feed: {final.fresh_feed.hydrocarbon_kmol_h:.3f} kmol/h",
        f"final fresh steam feed: {final.fresh_feed.steam_kmol_h:.3f} kmol/h",
        f"final recycle EB: {final.input_eb_recycle_kmol_h:.3f} kmol/h",
        f"final recycle H2O: {final.input_h2o_recycle_kmol_h:.3f} kmol/h",
        f"final reactor EB: {final.reactor_feed.eb:.3f} kmol/h",
        f"final reactor H2O: {final.reactor_feed.steam:.3f} kmol/h",
        f"final SM product: {final.sm_product_kmol_h:.3f} kmol/h",
        f"final SM margin: {final.sm_error_kmol_h:+.3f} kmol/h",
        "",
        format_cumulative_run_tables(
            result.runs,
            FeedTuningOptions(
                target_sm_kmol_h=result.target_sm_kmol_h,
                sm_tolerance_kmol_h=result.sm_tolerance_kmol_h,
                eb_recycle_tolerance_kmol_h=result.eb_recycle_tolerance_kmol_h,
                h2o_recycle_tolerance_kmol_h=result.h2o_recycle_tolerance_kmol_h,
            ),
        ),
        "",
        format_final_plant_summary_section(final.plant_record),
    ]
    return "\n".join(lines)


def format_cumulative_run_tables(runs: tuple[FeedTuningRun, ...], options: FeedTuningOptions) -> str:
    """累積 run 表を feed/SM と recycle 自己一致に分けて返す。"""
    lines = [
        "[Feed and SM]",
        f"{'run':>3} {'freshEB':>9} {'freshH2O':>9} {'recEB':>9} {'recH2O':>9} "
        f"{'reactorEB':>10} {'reactorH2O':>10} {'SM':>9} {'margin':>9} {'conv':>5}",
    ]
    for run in runs:
        lines.append(
            f"{run.run_index:>3} "
            f"{run.fresh_feed.hydrocarbon_kmol_h * options.feed_policy.eb_mol_fraction:>9.3f} "
            f"{run.fresh_feed.steam_kmol_h:>9.3f} "
            f"{run.input_eb_recycle_kmol_h:>9.3f} "
            f"{run.input_h2o_recycle_kmol_h:>9.3f} "
            f"{run.reactor_feed.eb:>10.3f} "
            f"{run.reactor_feed.steam:>10.3f} "
            f"{run.sm_product_kmol_h:>9.3f} "
            f"{run.sm_error_kmol_h:>+9.3f} "
            f"{'yes' if run.converged else 'no':>5}"
        )

    lines.extend(
        [
            "",
            "[Recycle Consistency]",
            f"{'run':>3} {'comp':>4} {'input':>10} {'output':>10} {'error':>10} {'tol':>8}",
        ]
    )
    for run in runs:
        lines.append(
            f"{run.run_index:>3} {'EB':>4} "
            f"{run.input_eb_recycle_kmol_h:>10.3f} "
            f"{run.output_eb_recycle_kmol_h:>10.3f} "
            f"{run.eb_recycle_error_kmol_h:>+10.3f} "
            f"{options.eb_recycle_tolerance_kmol_h:>8.3f}"
        )
        lines.append(
            f"{run.run_index:>3} {'H2O':>4} "
            f"{run.input_h2o_recycle_kmol_h:>10.3f} "
            f"{run.output_h2o_recycle_kmol_h:>10.3f} "
            f"{run.h2o_recycle_error_kmol_h:>+10.3f} "
            f"{options.h2o_recycle_tolerance_kmol_h:>8.3f}"
        )
    return "\n".join(lines)


def parse_feed_tuning_args() -> argparse.Namespace:
    """feed tuning CLI の引数を読む。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-sm-kmol-h", type=float, default=DEFAULT_TARGET_SM_KMOL_H)
    parser.add_argument("--max-runs", type=int, default=FeedTuningOptions().max_runs)
    parser.add_argument("--min-runs", type=int, default=FeedTuningOptions().min_runs)
    parser.add_argument("--sm-tolerance-kmol-h", type=float, default=FeedTuningOptions().sm_tolerance_kmol_h)
    parser.add_argument(
        "--eb-recycle-tolerance-kmol-h",
        type=float,
        default=FeedTuningOptions().eb_recycle_tolerance_kmol_h,
    )
    parser.add_argument(
        "--h2o-recycle-tolerance-kmol-h",
        type=float,
        default=FeedTuningOptions().h2o_recycle_tolerance_kmol_h,
    )
    parser.add_argument("--max-feed-step-fraction", type=float, default=FeedTuningOptions().max_feed_step_fraction)
    parser.add_argument("--case-path", type=Path, default=DEFAULT_HYSYS_CASE_PATH)
    parser.add_argument(
        "--reactor-model",
        choices=("radial", "pfr"),
        default="radial",
        help="使用する反応器モデル。既定は radial",
    )
    return parser.parse_args()


def tune_fresh_feed_fast_main() -> None:
    """CLI から高速 feed 調整を実行する。"""
    configure_logging()
    args = parse_feed_tuning_args()
    options = FeedTuningOptions(
        target_sm_kmol_h=args.target_sm_kmol_h,
        max_runs=args.max_runs,
        min_runs=args.min_runs,
        sm_tolerance_kmol_h=args.sm_tolerance_kmol_h,
        eb_recycle_tolerance_kmol_h=args.eb_recycle_tolerance_kmol_h,
        h2o_recycle_tolerance_kmol_h=args.h2o_recycle_tolerance_kmol_h,
        max_feed_step_fraction=args.max_feed_step_fraction,
    )
    result = tune_fresh_feed_fast(
        options=options,
        base_reactor_case=default_reactor_case_for_model(args.reactor_model),
        plant_runner=run_plant_once_for_reactor_case(
            case_path=args.case_path,
            hysys_visible=False,
            reactor_model=args.reactor_model,
        ),
        reactor_model=args.reactor_model,
    )
    print(format_feed_tuning_result(result))
