"""ラジアル反応器の選択率・単通反応率 Pareto front 探索。"""

from __future__ import annotations

from dataclasses import replace
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import optuna
from optuna.samplers import NSGAIISampler

from process_sim.optimization.models import ParameterRange
from process_sim.optimization.reactor.parameters import (
    RadialReactorCandidate,
    RadialReactorParameterConfig,
    THREE_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
    TWO_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
)
from process_sim.optimization.runner.radial_simple_optuna import (
    format_candidate,
    reactor_case_from_candidate,
    suggest_candidate,
    validate_result,
)
from process_sim.reactor.core.models import ReactorResult
from process_sim.reactor.types.staged_adiabatic_radial import StagedAdiabaticRadialFlowModel


logger = logging.getLogger(__name__)

TARGET_EFFECTIVE_TRIALS_BY_STAGE_COUNT: dict[int, int] = {
    2: 1300,
    3: 1600,
}
POPULATION_SIZE = 50
SEED: int | None = None
LOG_DIR = Path("logs")
LOG_PATH = LOG_DIR / "radial_pareto_optuna.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5
STORAGE_PATH = Path("data") / "optuna" / "radial_pareto_optuna.db"

TWO_STAGE_PARETO_CONFIG = replace(
    TWO_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
    inlet_pressure_kpa_abs=ParameterRange(lower=70.0, upper=200.0),
)
THREE_STAGE_PARETO_CONFIG = replace(
    THREE_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
    inlet_pressure_kpa_abs=ParameterRange(lower=90.0, upper=200.0),
)
STUDY_CONFIGS: tuple[tuple[str, RadialReactorParameterConfig], ...] = (
    ("radial_2stage_selectivity_conversion", TWO_STAGE_PARETO_CONFIG),
    ("radial_3stage_selectivity_conversion", THREE_STAGE_PARETO_CONFIG),
)


def tune_radial_pareto_main() -> None:
    """2段と3段の Pareto front 探索を段数ごとの累積目標まで進める。"""
    configure_logging()
    storage_url = prepare_storage_url()
    studies = tuple(
        (
            create_or_load_study(study_name=study_name, storage_url=storage_url),
            config,
        )
        for study_name, config in STUDY_CONFIGS
    )
    for study, config in studies:
        run_study(
            study=study,
            config=config,
            target_trial_count=TARGET_EFFECTIVE_TRIALS_BY_STAGE_COUNT[config.stage_count],
        )


def prepare_storage_url() -> str:
    """SQLite storage の親ディレクトリを作り、接続 URL を返す。"""
    STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{STORAGE_PATH.as_posix()}"


def create_or_load_study(
    study_name: str,
    storage_url: str,
) -> optuna.Study:
    """1つの段数に対応する study を作成または読み込む。"""
    return optuna.create_study(
        study_name=study_name,
        directions=("maximize", "maximize"),
        sampler=NSGAIISampler(
            population_size=POPULATION_SIZE,
            seed=SEED,
        ),
        storage=storage_url,
        load_if_exists=True,
    )


def effective_trial_count(study: optuna.Study) -> int:
    """完了または prune 済みの trial 数を返す。"""
    return sum(
        trial.state in {optuna.trial.TrialState.COMPLETE, optuna.trial.TrialState.PRUNED}
        for trial in study.trials
    )


def run_study(
    study: optuna.Study,
    config: RadialReactorParameterConfig,
    target_trial_count: int,
) -> None:
    """1つの study を指定した累積 trial 数まで進める。"""
    stored_trial_count_before = len(study.trials)
    effective_trial_count_before = effective_trial_count(study)
    added_trial_count = max(target_trial_count - effective_trial_count_before, 0)
    logger.info(
        "[start] study=%s stage_count=%s add_trials=%s effective_trials=%s stored_trials=%s target_trials=%s",
        study.study_name,
        config.stage_count,
        added_trial_count,
        effective_trial_count_before,
        stored_trial_count_before,
        target_trial_count,
    )
    study.optimize(
        lambda trial: objective(
            trial=trial,
            config=config,
            study_name=study.study_name,
        ),
        n_trials=added_trial_count,
    )
    added_trials = study.trials[stored_trial_count_before:]
    complete_count = sum(trial.state is optuna.trial.TrialState.COMPLETE for trial in added_trials)
    pruned_count = sum(trial.state is optuna.trial.TrialState.PRUNED for trial in added_trials)
    logger.info(
        "[done] study=%s completed=%s pruned=%s effective_trials=%s stored_trials=%s",
        study.study_name,
        complete_count,
        pruned_count,
        effective_trial_count(study),
        len(study.trials),
    )


def objective(
    trial: optuna.Trial,
    config: RadialReactorParameterConfig,
    study_name: str,
) -> tuple[float, float]:
    """反応器を評価し、SM 選択率と EB 単通反応率を返す。"""
    candidate = suggest_candidate(trial=trial, config=config)
    trial.set_user_attr("stage_count", candidate.stage_count)
    try:
        reactor_case = reactor_case_from_candidate(candidate)
        result = StagedAdiabaticRadialFlowModel().run(
            feed=reactor_case.feed,
            conditions=reactor_case.conditions,
        )
        save_result_attrs(trial=trial, candidate=candidate, result=result)
        validate_result(result)
    except Exception as exc:
        reason = str(exc)
        trial.set_user_attr("prune_reason", reason)
        logger.info(
            "[pruned] study=%s trial=%s %s reason=%s",
            study_name,
            trial.number,
            format_candidate(candidate),
            reason,
        )
        raise optuna.TrialPruned(reason) from exc

    logger.info(
        "[finished] study=%s trial=%s SM_sel=%.6f EB_conv=%.6f "
        "outlet_P=%.3f kPa catalyst_volume=%.3f m3 %s",
        study_name,
        trial.number,
        result.styrene_selectivity,
        result.eb_conversion,
        result.outlet.pressure_kpa,
        result.log.total_catalyst_volume_m3 or 0.0,
        format_candidate(candidate),
    )
    return result.styrene_selectivity, result.eb_conversion


def save_result_attrs(
    trial: optuna.Trial,
    candidate: RadialReactorCandidate,
    result: ReactorResult,
) -> None:
    """完了 trial の要約値を SQLite storage に保存する。"""
    trial.set_user_attr("stage_count", candidate.stage_count)
    trial.set_user_attr("eb_conversion", result.eb_conversion)
    trial.set_user_attr("styrene_selectivity", result.styrene_selectivity)
    trial.set_user_attr("outlet_pressure_kpa", result.outlet.pressure_kpa)
    trial.set_user_attr("total_catalyst_volume_m3", result.log.total_catalyst_volume_m3)
    trial.set_user_attr("pressure_positive_ok", result.log.pressure_positive_ok)
    trial.set_user_attr("atom_balance_ok", result.log.atom_balance_ok)
    trial.set_user_attr("ergun_range_ok", result.log.ergun_range_ok)
    trial.set_user_attr("outlet_pressure_ok", result.log.outlet_pressure_ok)


def configure_logging() -> None:
    """標準エラーとローテーション付きファイルログを設定する。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(handler)


if __name__ == "__main__":
    tune_radial_pareto_main()
