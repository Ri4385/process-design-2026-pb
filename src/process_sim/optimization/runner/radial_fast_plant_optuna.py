"""radial 反応器条件を plant 収束後の経済収支で Optuna tuning する。"""

from __future__ import annotations

from dataclasses import replace
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import optuna
from optuna.samplers import TPESampler

from process_sim.optimization.reactor.parameters import (
    RADIAL_INLET_SUPERFICIAL_VELOCITY_M_PER_S,
    RadialReactorCandidate,
    RadialReactorParameterConfig,
    THREE_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
    TWO_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
)
from process_sim.optimization.runner.radial_simple_optuna import (
    best_trial_or_none,
    format_candidate,
    suggest_candidate,
    validate_result,
)
from process_sim.plant.const import DEFAULT_HYSYS_CASE_PATH, DEFAULT_TARGET_SM_KMOL_H
from process_sim.plant.convergence import format_plant_convergence_result, run_production_target_convergence
from process_sim.plant.economics import (
    PlantReactorEconomicBreakdown,
    format_plant_reactor_economic_breakdown,
    plant_reactor_economic_breakdown,
)
from process_sim.plant.models import PlantRunRecord
from process_sim.plant.production_target import FeedTuningOptions, InitialRecycleGuessPolicy, ReactorCaseLike
from process_sim.plant.runner import configure_logging
from process_sim.plant.session_runner import OpenHysysPlantRunner
from process_sim.reactor.cases.styrene_radial_default import (
    DEFAULT_STYRENE_RADIAL_REACTOR_CASE,
    RadialReactorCase,
)
from process_sim.reactor.core.models import ReactorResult
from process_sim.reactor.types.staged_adiabatic_radial import StagedAdiabaticRadialFlowModel


logger = logging.getLogger(__name__)
param_logger = logging.getLogger(f"{__name__}.params")

N_TRIALS =30
SEED = 42
LOG_DIR = Path("logs")
DETAIL_LOG_PATH = LOG_DIR / "radial_fast_plant_optuna_detail.log"
PARAM_LOG_PATH = LOG_DIR / "radial_fast_plant_optuna_params.log"
DETAIL_LOG_MAX_BYTES = 20 * 1024 * 1024
DETAIL_LOG_BACKUP_COUNT = 5
PARAM_LOG_MAX_BYTES = 5 * 1024 * 1024
PARAM_LOG_BACKUP_COUNT = 5

STUDY_CONFIGS: tuple[tuple[str, RadialReactorParameterConfig], ...] = (
    ("radial_2stage_fast_plant_profit", TWO_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG),
    ("radial_3stage_fast_plant_profit", THREE_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG),
)


def tune_radial_fast_plant_profit_main() -> None:
    """Plant 経済収支 tuning を実行する。"""
    configure_logging()
    configure_file_logging()
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


def run_study(
    study_name: str,
    config: RadialReactorParameterConfig,
) -> optuna.Study:
    """1つの段数に対応する plant 経済収支 study を実行する。"""
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


def objective(
    trial: optuna.Trial,
    config: RadialReactorParameterConfig,
    study_name: str,
) -> float:
    """Trial 条件で plant を収束させ、反応器費込みの経済収支を返す。"""
    candidate = suggest_candidate(trial=trial, config=config)
    logger.info("trial started: study=%s number=%s %s", study_name, trial.number, format_candidate(candidate))
    log_param_trial_started(study_name=study_name, trial_number=trial.number, candidate=candidate)
    reactor_case = plant_reactor_case_from_candidate(candidate)
    feed_tuning_options = FeedTuningOptions(
        initial_guess_policy=InitialRecycleGuessPolicy(
            steam_to_eb_ratio=candidate.steam_to_eb_ratio,
        ),
    )

    try:
        with OpenHysysPlantRunner(
            case_path=DEFAULT_HYSYS_CASE_PATH,
            reactor_model="radial",
            log_reactor_detail=True,
        ) as plant_runner:
            validated_plant_runner = ValidatingRadialPlantRunner(plant_runner=plant_runner)
            convergence_result = run_production_target_convergence(
                target_sm_kmol_h=DEFAULT_TARGET_SM_KMOL_H,
                production_target_runner=validated_plant_runner,
                convergence_runner=validated_plant_runner,
                reactor_model="radial",
                base_reactor_case=reactor_case,
                feed_tuning_options=feed_tuning_options,
            )
        logger.info("\n%s", format_plant_convergence_result(convergence_result))
        if not convergence_result.converged:
            raise ValueError("plant convergence is not converged")

        final_reactor_case = replace(
            reactor_case,
            feed=convergence_result.final_iteration.reactor_feed,
        )
        final_reactor_result = run_radial_reactor(final_reactor_case)
        validate_result(final_reactor_result)
        breakdown = plant_reactor_economic_breakdown(
            plant_record=convergence_result.final_iteration.plant_record,
            steady_fresh_feed=convergence_result.feed_plan.steady_fresh_feed,
            reactor_result=final_reactor_result,
        )
    except Exception as exc:
        logger.info("trial pruned: study=%s number=%s reason=%s", study_name, trial.number, exc)
        log_param_trial_pruned(study_name=study_name, trial_number=trial.number, candidate=candidate, reason=str(exc))
        raise optuna.TrialPruned(str(exc)) from exc

    log_trial_result(
        study_name=study_name,
        trial_number=trial.number,
        result=final_reactor_result,
        breakdown=breakdown,
    )
    trial.set_user_attr("product_revenue_yen_per_year", breakdown.product_revenue_yen_per_year)
    trial.set_user_attr("fresh_feed_cost_yen_per_year", breakdown.fresh_feed_cost_yen_per_year)
    trial.set_user_attr("reactor_annual_cost_yen_per_year", breakdown.reactor_annual_cost_yen_per_year)
    trial.set_user_attr("eb_conversion", final_reactor_result.eb_conversion)
    trial.set_user_attr("styrene_selectivity", final_reactor_result.styrene_selectivity)
    trial.set_user_attr("outlet_pressure_kpa", final_reactor_result.outlet.pressure_kpa)
    log_param_trial_finished(
        study_name=study_name,
        trial_number=trial.number,
        candidate=candidate,
        result=final_reactor_result,
        breakdown=breakdown,
    )
    return breakdown.objective_yen_per_year


def configure_file_logging() -> None:
    """詳細ログと探索 param ログをローテーション付きで設定する。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    detail_handler = RotatingFileHandler(
        DETAIL_LOG_PATH,
        maxBytes=DETAIL_LOG_MAX_BYTES,
        backupCount=DETAIL_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    detail_handler.setLevel(logging.INFO)
    detail_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(detail_handler)

    param_handler = RotatingFileHandler(
        PARAM_LOG_PATH,
        maxBytes=PARAM_LOG_MAX_BYTES,
        backupCount=PARAM_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    param_handler.setLevel(logging.INFO)
    param_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    param_logger.setLevel(logging.INFO)
    param_logger.propagate = False
    param_logger.addHandler(param_handler)


def log_param_trial_started(
    study_name: str,
    trial_number: int,
    candidate: RadialReactorCandidate,
) -> None:
    """探索条件だけを param ログへ出す。"""
    param_logger.info(
        "started study=%s trial=%s %s",
        study_name,
        trial_number,
        format_candidate(candidate),
    )


def log_param_trial_pruned(
    study_name: str,
    trial_number: int,
    candidate: RadialReactorCandidate,
    reason: str,
) -> None:
    """Prune された探索条件だけを param ログへ出す。"""
    param_logger.info(
        "pruned study=%s trial=%s %s reason=%s",
        study_name,
        trial_number,
        format_candidate(candidate),
        reason,
    )


def log_param_trial_finished(
    study_name: str,
    trial_number: int,
    candidate: RadialReactorCandidate,
    result: ReactorResult,
    breakdown: PlantReactorEconomicBreakdown,
) -> None:
    """完了した探索条件と主要結果だけを param ログへ出す。"""
    param_logger.info(
        "finished study=%s trial=%s objective=%.6e EB_conv=%.4f SM_sel=%.4f outlet_P=%.3f kPa %s",
        study_name,
        trial_number,
        breakdown.objective_yen_per_year,
        result.eb_conversion,
        result.styrene_selectivity,
        result.outlet.pressure_kpa,
        format_candidate(candidate),
    )


class ValidatingRadialPlantRunner:
    """HYSYS へ渡す前に radial 反応器制約を確認する runner wrapper。"""

    def __init__(self, plant_runner: OpenHysysPlantRunner) -> None:
        self.plant_runner = plant_runner

    def __call__(self, reactor_case: ReactorCaseLike) -> PlantRunRecord:
        """反応器制約が NG の場合は HYSYS を呼ばずに停止する。"""
        if not isinstance(reactor_case, RadialReactorCase):
            raise TypeError("ValidatingRadialPlantRunner requires RadialReactorCase")
        reactor_result = run_radial_reactor(reactor_case)
        validate_result(reactor_result)
        return self.plant_runner(reactor_case)


def plant_reactor_case_from_candidate(candidate: RadialReactorCandidate) -> RadialReactorCase:
    """候補条件から plant feed tuning 用の radial 反応器 case を作る。"""
    base_case = DEFAULT_STYRENE_RADIAL_REACTOR_CASE
    conditions = replace(
        base_case.conditions,
        inlet_pressure_pa=candidate.inlet_pressure_kpa_abs * 1000.0,
        stage_inlet_temperatures_k=tuple(
            temperature_c + 273.15 for temperature_c in candidate.stage_inlet_temperatures_c
        ),
        inlet_superficial_velocity_m_per_s=RADIAL_INLET_SUPERFICIAL_VELOCITY_M_PER_S,
        bed_thicknesses_m=candidate.bed_thicknesses_m,
    )
    return RadialReactorCase(feed=base_case.feed, conditions=conditions)


def run_radial_reactor(reactor_case: RadialReactorCase) -> ReactorResult:
    """指定 case の radial 反応器を計算する。"""
    return StagedAdiabaticRadialFlowModel().run(
        feed=reactor_case.feed,
        conditions=reactor_case.conditions,
    )


def log_trial_result(
    study_name: str,
    trial_number: int,
    result: ReactorResult,
    breakdown: PlantReactorEconomicBreakdown,
) -> None:
    """trial 結果を Optuna ログへ出す。"""
    logger.info(
        "trial finished: study=%s number=%s objective=%.6e revenue=%.6e "
        "fresh_feed_cost=%.6e reactor_cost=%.6e EB_conv=%.4f SM_sel=%.4f outlet_P=%.3f kPa",
        study_name,
        trial_number,
        breakdown.objective_yen_per_year,
        breakdown.product_revenue_yen_per_year,
        breakdown.fresh_feed_cost_yen_per_year,
        breakdown.reactor_annual_cost_yen_per_year,
        result.eb_conversion,
        result.styrene_selectivity,
        result.outlet.pressure_kpa,
    )
    logger.info("\n%s", format_plant_reactor_economic_breakdown(breakdown))


if __name__ == "__main__":
    tune_radial_fast_plant_profit_main()
