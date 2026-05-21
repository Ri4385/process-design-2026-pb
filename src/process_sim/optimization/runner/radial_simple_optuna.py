"""radial 反応器の簡易利益 Optuna tuning。"""

from __future__ import annotations

from dataclasses import replace
import logging

import optuna
from optuna.samplers import TPESampler

from process_sim.optimization.models import ParameterRange
from process_sim.optimization.reactor.parameters import (
    RADIAL_INLET_SUPERFICIAL_VELOCITY_M_PER_S,
    RadialReactorCandidate,
    RadialReactorParameterConfig,
    THREE_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
    TWO_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
)
from process_sim.plant.economics import SimpleProfitBreakdown, simple_reactor_profit_breakdown
from process_sim.plant.summary import format_radial_reactor_report
from process_sim.reactor.cases.styrene_radial_default import (
    DEFAULT_STYRENE_RADIAL_REACTOR_CASE,
    RadialReactorCase,
)
from process_sim.reactor.core.models import ReactorResult
from process_sim.reactor.core.stream import ReactorFeed
from process_sim.reactor.types.staged_adiabatic_radial import StagedAdiabaticRadialFlowModel


logger = logging.getLogger(__name__)

N_TRIALS = 30
SEED = 42

STUDY_CONFIGS: tuple[tuple[str, RadialReactorParameterConfig], ...] = (
    ("radial_2stage_simple_profit", TWO_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG),
    ("radial_3stage_simple_profit", THREE_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG),
)


def tune_radial_simple_profit_main() -> None:
    """2段と3段の radial 簡易利益 tuning を実行する。"""
    configure_logging()
    best_summaries: list[tuple[str, optuna.trial.FrozenTrial]] = []
    for study_name, config in STUDY_CONFIGS:
        study = run_study(study_name=study_name, config=config)
        best_trial = best_trial_or_none(study)
        if best_trial is not None:
            best_summaries.append((study_name, best_trial))

    logger.info("[best trials]")
    for study_name, trial in best_summaries:
        logger.info(
            "%s trial=%s objective=%.6e params=%s",
            study_name,
            trial.number,
            trial.value if trial.value is not None else float("nan"),
            trial.params,
        )


def run_study(study_name: str, config: RadialReactorParameterConfig) -> optuna.Study:
    """1つの段数に対応する study を実行する。"""
    study = optuna.create_study(
        study_name=study_name,
        direction="maximize",
        sampler=TPESampler(seed=SEED),
    )
    logger.info("study started: %s stage_count=%s n_trials=%s", study_name, config.stage_count, N_TRIALS)
    study.optimize(
        lambda trial: objective(
            trial=trial,
            config=config,
            study_name=study_name,
        ),
        n_trials=N_TRIALS,
    )
    logger.info("study finished: %s", study_name)
    return study


def best_trial_or_none(study: optuna.Study) -> optuna.trial.FrozenTrial | None:
    """完了 trial がない場合は None を返す。"""
    try:
        return study.best_trial
    except ValueError:
        return None


def objective(
    trial: optuna.Trial,
    config: RadialReactorParameterConfig,
    study_name: str,
) -> float:
    """Optuna trial から radial 反応器を評価し、簡易利益を返す。"""
    candidate = suggest_candidate(trial=trial, config=config)
    logger.info("trial started: number=%s %s", trial.number, format_candidate(candidate))

    reactor_case: RadialReactorCase | None = None
    result: ReactorResult | None = None
    try:
        reactor_case = reactor_case_from_candidate(candidate)
        result = StagedAdiabaticRadialFlowModel().run(
            feed=reactor_case.feed,
            conditions=reactor_case.conditions,
        )
        validate_result(result)
    except Exception as exc:
        logger.info("trial pruned: number=%s reason=%s", trial.number, exc)
        if reactor_case is not None and result is not None:
            print_reactor_report(study_name=study_name, trial_number=trial.number, feed=reactor_case.feed, result=result)
        raise optuna.TrialPruned(str(exc)) from exc

    breakdown = simple_reactor_profit_breakdown(feed=reactor_case.feed, result=result)
    log_trial_result(trial_number=trial.number, result=result, breakdown=breakdown)
    print_reactor_report(study_name=study_name, trial_number=trial.number, feed=reactor_case.feed, result=result)
    trial.set_user_attr("revenue_yen_per_year", breakdown.revenue_yen_per_year)
    trial.set_user_attr("feed_cost_yen_per_year", breakdown.feed_cost_yen_per_year)
    trial.set_user_attr("reactor_annual_cost_yen_per_year", breakdown.reactor_annual_cost_yen_per_year)
    trial.set_user_attr("eb_conversion", result.eb_conversion)
    trial.set_user_attr("styrene_selectivity", result.styrene_selectivity)
    trial.set_user_attr("outlet_pressure_kpa", result.outlet.pressure_kpa)
    return breakdown.objective_yen_per_year


def suggest_candidate(trial: optuna.Trial, config: RadialReactorParameterConfig) -> RadialReactorCandidate:
    """探索空間から radial 反応器候補を生成する。"""
    stage_temperatures_c = tuple(
        suggest_float(trial, f"stage_{index}_temperature_c", parameter_range)
        for index, parameter_range in enumerate(config.stage_inlet_temperatures_c, start=1)
    )
    bed_thicknesses_m = tuple(
        suggest_float(trial, f"stage_{index}_bed_thickness_m", parameter_range)
        for index, parameter_range in enumerate(config.bed_thicknesses_m, start=1)
    )
    return RadialReactorCandidate(
        stage_inlet_temperatures_c=stage_temperatures_c,
        inlet_pressure_kpa_abs=suggest_float(trial, "inlet_pressure_kpa_abs", config.inlet_pressure_kpa_abs),
        steam_to_eb_ratio=suggest_float(trial, "steam_to_eb_ratio", config.steam_to_eb_ratio),
        bed_thicknesses_m=bed_thicknesses_m,
    )


def suggest_float(trial: optuna.Trial, name: str, parameter_range: ParameterRange) -> float:
    """ParameterRange を Optuna の suggest_float に変換する。"""
    return trial.suggest_float(name, parameter_range.lower, parameter_range.upper)


def reactor_case_from_candidate(candidate: RadialReactorCandidate) -> RadialReactorCase:
    """候補条件から radial 反応器ケースを作る。"""
    base_case = DEFAULT_STYRENE_RADIAL_REACTOR_CASE
    feed = replace(
        base_case.feed,
        steam=base_case.feed.eb * candidate.steam_to_eb_ratio,
    )
    conditions = replace(
        base_case.conditions,
        inlet_pressure_pa=candidate.inlet_pressure_kpa_abs * 1000.0,
        stage_inlet_temperatures_k=tuple(
            temperature_c + 273.15 for temperature_c in candidate.stage_inlet_temperatures_c
        ),
        inlet_superficial_velocity_m_per_s=RADIAL_INLET_SUPERFICIAL_VELOCITY_M_PER_S,
        bed_thicknesses_m=candidate.bed_thicknesses_m,
    )
    return RadialReactorCase(feed=feed, conditions=conditions)


def validate_result(result: ReactorResult) -> None:
    """Optuna 探索で採用する反応器結果か確認する。"""
    if result.log.pressure_positive_ok is False:
        raise ValueError("pressure_positive_ok is false")
    if result.log.atom_balance_ok is False:
        raise ValueError("atom_balance_ok is false")
    if result.log.ergun_range_ok is False:
        raise ValueError("ergun_range_ok is false")
    if result.log.outlet_pressure_ok is False:
        raise ValueError("outlet_pressure_ok is false")
    styrene_net_kmol_h = result.outlet.stream.styrene - result.log.stage_logs[0].inlet.styrene
    if styrene_net_kmol_h <= 0.0:
        raise ValueError("styrene production is not positive")


def format_candidate(candidate: RadialReactorCandidate) -> str:
    """候補条件をログ用文字列にする。"""
    temperatures = ", ".join(f"{value:.2f}" for value in candidate.stage_inlet_temperatures_c)
    thicknesses = ", ".join(f"{value:.3f}" for value in candidate.bed_thicknesses_m)
    return (
        f"stage_count={candidate.stage_count} "
        f"T=[{temperatures}] degC "
        f"P={candidate.inlet_pressure_kpa_abs:.3f} kPa abs "
        f"S/EB={candidate.steam_to_eb_ratio:.3f} "
        f"thickness=[{thicknesses}] m"
    )


def log_trial_result(trial_number: int, result: ReactorResult, breakdown: SimpleProfitBreakdown) -> None:
    """trial 結果を学習途中で読める粒度でログに出す。"""
    first_stage = result.log.stage_logs[0]
    inner_diameter_m = 2.0 * (first_stage.inner_radius_m or 0.0)
    logger.info(
        "trial finished: number=%s objective=%.6e revenue=%.6e feed_cost=%.6e "
        "reactor_cost=%.6e EB_conv=%.4f SM_sel=%.4f outlet_P=%.3f kPa "
        "inner_D=%.3f m catalyst_volume=%.3f m3 constraints="
        "pressure_positive:%s atom_balance:%s ergun:%s outlet_pressure:%s",
        trial_number,
        breakdown.objective_yen_per_year,
        breakdown.revenue_yen_per_year,
        breakdown.feed_cost_yen_per_year,
        breakdown.reactor_annual_cost_yen_per_year,
        result.eb_conversion,
        result.styrene_selectivity,
        result.outlet.pressure_kpa,
        inner_diameter_m,
        result.log.total_catalyst_volume_m3 or 0.0,
        result.log.pressure_positive_ok,
        result.log.atom_balance_ok,
        result.log.ergun_range_ok,
        result.log.outlet_pressure_ok,
    )


def print_reactor_report(study_name: str, trial_number: int, feed: ReactorFeed, result: ReactorResult) -> None:
    """trial ごとの反応器詳細ログを標準出力へ出す。"""
    print()
    print("============================================", flush=True)
    print(f"[Reactor Log] study={study_name} trial={trial_number}", flush=True)
    print(format_radial_reactor_report(feed=feed, result=result), flush=True)


def configure_logging() -> None:
    """Optuna runner のログ設定を行う。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


if __name__ == "__main__":
    tune_radial_simple_profit_main()
