"""radial 2段だけを固定分離条件で探索する最終 Optuna runner。"""

from __future__ import annotations

from dataclasses import replace
import logging
from logging.handlers import RotatingFileHandler
import multiprocessing as mp
from multiprocessing.queues import Queue
from pathlib import Path
import queue
from typing import Callable, Literal, cast

import optuna
from optuna.samplers import TPESampler
from pydantic import BaseModel, ConfigDict, Field

from process_sim.cli import ReactorModelName
from process_sim.optimization.models import ParameterRange
from process_sim.optimization.reactor.parameters import (
    RadialReactorCandidate,
    RadialReactorParameterConfig,
    TWO_STAGE_WHOLE_PLANT_V2_RADIAL_REACTOR_PARAMETER_CONFIG,
)
from process_sim.optimization.separator.hysys_controls import (
    build_separator_control_plan,
    merge_hysys_control_plans,
)
from process_sim.optimization.separator.parameters import SeparatorOperatingCandidate
from process_sim.plant.const import (
    DEFAULT_HYSYS_CASE_PATH,
    DEFAULT_HYSYS_PREWARM_TIMEOUT_SECONDS,
    DEFAULT_TARGET_SM_KMOL_H,
    DEFAULT_WHOLE_PLANT_TRIAL_TIMEOUT_SECONDS,
)
from process_sim.plant.convergence import (
    PlantConvergenceResult,
    run_production_target_convergence,
)
from process_sim.plant.cost.evaluation import evaluate_whole_plant_cost
from process_sim.plant.cost.models import WholePlantCostResult
from process_sim.plant.hysys_controls import build_inlet_control_plan
from process_sim.plant.models import PlantRunRecord, PlantStreamRecord
from process_sim.plant.production_target import (
    FeedTuningOptions,
    InitialRecycleGuessPolicy,
    ReactorCaseLike,
    read_sm_product_kmol_h,
)
from process_sim.plant.runner import configure_logging
from process_sim.plant.session_runner import OpenHysysPlantRunner, run_reactor_case
from process_sim.reactor.cases.styrene_radial_default import (
    DEFAULT_STYRENE_RADIAL_REACTOR_CASE,
    RadialReactorCase,
)
from process_sim.reactor.core.models import ReactorResult


logger = logging.getLogger(__name__)

ReactorType = Literal["radial"]
TrialAttrValue = str | int | float | bool | None

STUDY_NAME = "radial_2stage_fixed_final_profit"
STORAGE_PATH = Path("data") / "optuna" / "whole_plant_radial2_fixed_final.db"
LOG_DIR = Path("logs")
LOG_PATH = LOG_DIR / "whole_plant_radial2_fixed_final.log"
DETAIL_LOG_PATH = LOG_DIR / "whole_plant_radial2_fixed_final_detail.log"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5
SEED = 42
N_STARTUP_TRIALS = 100
TARGET_EFFECTIVE_TRIALS = 300

FIXED_STEAM_TO_EB_RATIO = 5.0
FIXED_DECANTER_1_TEMPERATURE_C = 55.0
FIXED_SM_COLUMN_REFLUX_RATIO = 6.312

TWO_STAGE_RADIAL_FIXED_FINAL_BED_THICKNESS_RANGE_M = ParameterRange(
    lower=0.6,
    upper=1.0,
)

TWO_STAGE_RADIAL_FIXED_FINAL_PRESSURE_RANGE_KPA_ABS = ParameterRange(
    lower=80.0,
    upper=120.0,
)

TWO_STAGE_RADIAL_FIXED_FINAL_CONFIG = replace(
    TWO_STAGE_WHOLE_PLANT_V2_RADIAL_REACTOR_PARAMETER_CONFIG,
    inlet_pressure_kpa_abs=TWO_STAGE_RADIAL_FIXED_FINAL_PRESSURE_RANGE_KPA_ABS,
    bed_thicknesses_m=(
        TWO_STAGE_RADIAL_FIXED_FINAL_BED_THICKNESS_RANGE_M,
        TWO_STAGE_RADIAL_FIXED_FINAL_BED_THICKNESS_RANGE_M,
    ),
)

FIXED_SEPARATOR_CANDIDATE = SeparatorOperatingCandidate(
    decanter_1_temperature_c=FIXED_DECANTER_1_TEMPERATURE_C,
    sm_column_reflux_ratio=FIXED_SM_COLUMN_REFLUX_RATIO,
)


class TrialWorkerSuccess(BaseModel):
    """trial worker の正常終了結果。"""

    model_config = ConfigDict(frozen=True)

    objective_value: float
    user_attrs: dict[str, TrialAttrValue]


class TrialWorkerFailure(BaseModel):
    """trial worker の異常終了結果。"""

    model_config = ConfigDict(frozen=True)

    reason: str
    user_attrs: dict[str, TrialAttrValue] = Field(default_factory=dict)


TrialWorkerResult = TrialWorkerSuccess | TrialWorkerFailure


def tune_whole_plant_radial2_fixed_final_main() -> None:
    """radial 2段の固定分離条件探索を累積目標 trial 数まで進める。"""
    configure_logging()
    configure_file_logging()
    run_hysys_prewarm_with_timeout(
        case_path=DEFAULT_HYSYS_CASE_PATH,
        timeout_seconds=DEFAULT_HYSYS_PREWARM_TIMEOUT_SECONDS,
    )
    study = create_or_load_study(
        study_name=STUDY_NAME,
        storage_url=prepare_storage_url(),
    )
    run_study(study=study, target_trial_count=TARGET_EFFECTIVE_TRIALS)


def prepare_storage_url() -> str:
    """SQLite storage の親 directory を作り、接続 URL を返す。"""
    STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{STORAGE_PATH.as_posix()}"


def create_or_load_study(study_name: str, storage_url: str) -> optuna.Study:
    """単目的 maximize study を作成または読み込む。"""
    return optuna.create_study(
        study_name=study_name,
        direction="maximize",
        sampler=TPESampler(seed=SEED, n_startup_trials=N_STARTUP_TRIALS),
        storage=storage_url,
        load_if_exists=True,
    )


def effective_trial_count(study: optuna.Study) -> int:
    """完了または prune 済みの trial 数を返す。"""
    return sum(
        trial.state
        in {optuna.trial.TrialState.COMPLETE, optuna.trial.TrialState.PRUNED}
        for trial in study.trials
    )


def run_hysys_prewarm_with_timeout(case_path: Path, timeout_seconds: float) -> None:
    """HYSYS 初回起動を trial 外で済ませる。"""
    result = run_process_with_timeout(
        target=_prewarm_worker_entry,
        args=(case_path,),
        timeout_seconds=timeout_seconds,
    )
    if isinstance(result, TrialWorkerFailure):
        raise RuntimeError(f"HYSYS prewarm failed: {result.reason}")
    logger.info(
        "[prewarm finished] case_path=%s timeout=%.1f",
        case_path,
        timeout_seconds,
    )


def _prewarm_worker_entry(
    result_queue: Queue[TrialWorkerResult],
    case_path: Path,
) -> None:
    """prewarm worker process の入口。"""
    configure_worker_detail_logging()
    try:
        logger.info("[prewarm started] case_path=%s mode=radial_2stage", case_path)
        with OpenHysysPlantRunner(
            case_path=case_path,
            reactor_model="radial",
            log_reactor_detail=True,
        ) as plant_runner:
            plant_runner(DEFAULT_STYRENE_RADIAL_REACTOR_CASE)
    except Exception as exc:
        logger.exception("[prewarm failed] case_path=%s", case_path)
        result_queue.put(TrialWorkerFailure(reason=str(exc)))
        return
    logger.info("[prewarm finished] case_path=%s mode=radial_2stage", case_path)
    result_queue.put(TrialWorkerSuccess(objective_value=0.0, user_attrs={}))


def run_process_with_timeout(
    target: Callable[..., object],
    args: tuple[object, ...],
    timeout_seconds: float,
) -> TrialWorkerResult:
    """target を別 process で実行し、timeout したら失敗結果を返す。"""
    context = mp.get_context("spawn")
    result_queue: Queue[TrialWorkerResult] = context.Queue(maxsize=1)
    process = context.Process(
        target=target,
        args=(result_queue, *args),
    )
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join()
        return TrialWorkerFailure(
            reason=f"global timeout exceeded: {timeout_seconds:.1f} s"
        )

    try:
        result = result_queue.get_nowait()
    except queue.Empty:
        return TrialWorkerFailure(
            reason=f"worker exited without result: exitcode={process.exitcode}"
        )
    return result


def run_study(study: optuna.Study, target_trial_count: int) -> None:
    """radial 2段 study を指定した累積 trial 数まで進める。"""
    stored_trial_count_before = len(study.trials)
    effective_trial_count_before = effective_trial_count(study)
    added_trial_count = max(target_trial_count - effective_trial_count_before, 0)
    logger.info(
        "[start] study=%s reactor=radial stage_count=2 add_trials=%s "
        "effective_trials=%s stored_trials=%s target_trials=%s n_startup_trials=%s "
        "fixed_s_eb=%.3f fixed_decanter1_t=%.2f fixed_sm_reflux=%.4f",
        study.study_name,
        added_trial_count,
        effective_trial_count_before,
        stored_trial_count_before,
        target_trial_count,
        N_STARTUP_TRIALS,
        FIXED_STEAM_TO_EB_RATIO,
        FIXED_DECANTER_1_TEMPERATURE_C,
        FIXED_SM_COLUMN_REFLUX_RATIO,
    )
    study.optimize(objective, n_trials=added_trial_count)
    added_trials = study.trials[stored_trial_count_before:]
    complete_count = sum(
        trial.state is optuna.trial.TrialState.COMPLETE for trial in added_trials
    )
    pruned_count = sum(
        trial.state is optuna.trial.TrialState.PRUNED for trial in added_trials
    )
    logger.info(
        "[done] study=%s completed=%s pruned=%s effective_trials=%s stored_trials=%s",
        study.study_name,
        complete_count,
        pruned_count,
        effective_trial_count(study),
        len(study.trials),
    )


def objective(trial: optuna.Trial) -> float:
    """Trial 条件で radial 2段 plant を収束させ、全体年収支を返す。"""
    candidate = suggest_radial2_candidate(
        trial=trial,
        config=TWO_STAGE_RADIAL_FIXED_FINAL_CONFIG,
    )
    separator_candidate = FIXED_SEPARATOR_CANDIDATE
    save_candidate_attrs(trial=trial, candidate=candidate)
    save_separator_candidate_attrs(trial=trial, candidate=separator_candidate)
    save_fixed_condition_attrs(trial=trial)
    reactor_case = reactor_case_from_candidate(candidate=candidate)
    feed_tuning_options = FeedTuningOptions(
        initial_guess_policy=InitialRecycleGuessPolicy(
            steam_to_eb_ratio=FIXED_STEAM_TO_EB_RATIO,
        ),
    )
    logger.info(
        "[trial started] study=%s trial=%s %s %s",
        STUDY_NAME,
        trial.number,
        format_candidate(candidate),
        format_separator_candidate(separator_candidate),
    )

    result = run_process_with_timeout(
        target=_trial_worker_entry,
        args=(
            "radial",
            "radial",
            candidate,
            separator_candidate,
            reactor_case,
            feed_tuning_options,
        ),
        timeout_seconds=DEFAULT_WHOLE_PLANT_TRIAL_TIMEOUT_SECONDS,
    )
    if isinstance(result, TrialWorkerFailure):
        reason = result.reason
        trial.set_user_attr("prune_reason", reason)
        logger.info(
            "[pruned] study=%s trial=%s %s %s reason=%s attrs=%s",
            STUDY_NAME,
            trial.number,
            format_candidate(candidate),
            format_separator_candidate(separator_candidate),
            reason,
            format_key_result_attrs(result.user_attrs),
        )
        raise optuna.TrialPruned(reason)

    save_result_attrs(trial=trial, result=result)
    logger.info(
        "[finished] study=%s trial=%s objective=%.6e %s %s %s",
        STUDY_NAME,
        trial.number,
        result.objective_value,
        format_candidate(candidate),
        format_separator_candidate(separator_candidate),
        format_key_result_attrs(result.user_attrs),
    )
    return result.objective_value


def _trial_worker_entry(
    result_queue: Queue[TrialWorkerResult],
    reactor_type: ReactorType,
    reactor_model: ReactorModelName,
    candidate: RadialReactorCandidate,
    separator_candidate: SeparatorOperatingCandidate,
    reactor_case: ReactorCaseLike,
    feed_tuning_options: FeedTuningOptions,
) -> None:
    """trial worker process の入口。"""
    configure_worker_detail_logging()
    logger.info(
        "[trial worker started] reactor=%s %s %s",
        reactor_type,
        format_candidate(candidate),
        format_separator_candidate(separator_candidate),
    )
    try:
        result = evaluate_candidate_in_worker(
            reactor_type=reactor_type,
            reactor_model=reactor_model,
            candidate=candidate,
            separator_candidate=separator_candidate,
            reactor_case=reactor_case,
            feed_tuning_options=feed_tuning_options,
        )
    except Exception as exc:
        logger.exception(
            "[trial worker failed] reactor=%s %s %s",
            reactor_type,
            format_candidate(candidate),
            format_separator_candidate(separator_candidate),
        )
        result_queue.put(TrialWorkerFailure(reason=str(exc)))
        return
    logger.info(
        "[trial worker finished] reactor=%s objective=%.6e %s %s %s",
        reactor_type,
        result.objective_value,
        format_candidate(candidate),
        format_separator_candidate(separator_candidate),
        format_key_result_attrs(result.user_attrs),
    )
    result_queue.put(result)


def evaluate_candidate_in_worker(
    reactor_type: ReactorType,
    reactor_model: ReactorModelName,
    candidate: RadialReactorCandidate,
    separator_candidate: SeparatorOperatingCandidate,
    reactor_case: ReactorCaseLike,
    feed_tuning_options: FeedTuningOptions,
) -> TrialWorkerSuccess:
    """worker process 内で plant convergence と cost 評価を実行する。"""
    with OpenHysysPlantRunner(
        case_path=DEFAULT_HYSYS_CASE_PATH,
        reactor_model=reactor_model,
        log_reactor_detail=True,
    ) as plant_runner:
        validating_runner = ValidatingPlantRunner(
            plant_runner=plant_runner,
            reactor_model=reactor_model,
            reactor_type=reactor_type,
        )
        convergence_result = run_production_target_convergence(
            target_sm_kmol_h=DEFAULT_TARGET_SM_KMOL_H,
            production_target_runner=validating_runner,
            convergence_runner=validating_runner,
            reactor_model=reactor_model,
            base_reactor_case=reactor_case,
            feed_tuning_options=feed_tuning_options,
        )
        if not convergence_result.converged:
            raise ValueError("plant convergence is not converged")
        plant_runner.apply_post_convergence_controls(
            merge_hysys_control_plans(
                build_inlet_control_plan(
                    convergence_result=convergence_result,
                    base_reactor_case=reactor_case,
                ),
                build_separator_control_plan(separator_candidate),
            )
        )
        equipment = plant_runner.read_process_equipment()
    cost_result = evaluate_whole_plant_cost(
        convergence_result=convergence_result,
        equipment=equipment,
    )
    return TrialWorkerSuccess(
        objective_value=cost_result.annual_profit_yen_per_year,
        user_attrs=result_attrs(
            convergence_result=convergence_result,
            cost_result=cost_result,
            separator_candidate=separator_candidate,
        ),
    )


class ValidatingPlantRunner:
    """HYSYS へ渡す前に反応器制約を確認する runner wrapper。"""

    def __init__(
        self,
        plant_runner: OpenHysysPlantRunner,
        reactor_model: ReactorModelName,
        reactor_type: ReactorType,
    ) -> None:
        self.plant_runner = plant_runner
        self.reactor_model: ReactorModelName = reactor_model
        self.reactor_type: ReactorType = reactor_type
        self.last_reactor_result: ReactorResult | None = None

    def __call__(self, reactor_case: ReactorCaseLike) -> PlantRunRecord:
        """反応器制約が NG の場合は HYSYS を呼ばずに停止する。"""
        precheck_result = cast(
            ReactorResult,
            run_reactor_case(
                reactor_case=reactor_case,
                reactor_model=self.reactor_model,
            ),
        )
        logger.info(
            "[reactor precheck] model=%s eb_conversion=%.6f styrene_selectivity=%.6f "
            "outlet_pressure_kpa=%.3f total_catalyst_volume_m3=%.3f",
            self.reactor_model,
            precheck_result.eb_conversion,
            precheck_result.styrene_selectivity,
            precheck_result.outlet.pressure_kpa,
            precheck_result.log.total_catalyst_volume_m3,
        )
        validate_reactor_result(result=precheck_result)
        record = self.plant_runner(reactor_case)
        if isinstance(self.plant_runner.last_reactor_result, ReactorResult):
            self.last_reactor_result = self.plant_runner.last_reactor_result
        else:
            self.last_reactor_result = precheck_result
        logger.info(
            "[plant run result] model=%s eb_conversion=%.6f styrene_selectivity=%.6f "
            "outlet_pressure_kpa=%.3f sm_product_kmol_h=%s",
            self.reactor_model,
            self.last_reactor_result.eb_conversion,
            self.last_reactor_result.styrene_selectivity,
            self.last_reactor_result.outlet.pressure_kpa,
            format_optional_log_float(read_sm_product_from_record(record)),
        )
        return record


def suggest_radial2_candidate(
    trial: optuna.Trial,
    config: RadialReactorParameterConfig,
) -> RadialReactorCandidate:
    """固定 S/EB 条件で radial 2段候補を生成する。"""
    stage_1_temperature_range = config.stage_inlet_temperatures_c[0]
    stage_2_temperature_range = config.stage_inlet_temperatures_c[1]
    stage_1_temperature_c = suggest_float(
        trial,
        "stage_1_temperature_c",
        ParameterRange(
            lower=stage_1_temperature_range.lower,
            upper=min(stage_1_temperature_range.upper, stage_2_temperature_range.upper),
        ),
    )
    stage_2_temperature_c = suggest_float(
        trial,
        "stage_2_temperature_c",
        ParameterRange(
            lower=max(
                stage_2_temperature_range.lower,
                stage_1_temperature_c,
            ),
            upper=stage_2_temperature_range.upper,
        ),
    )
    return RadialReactorCandidate(
        stage_inlet_temperatures_c=(stage_1_temperature_c, stage_2_temperature_c),
        inlet_pressure_kpa_abs=suggest_float(
            trial,
            "inlet_pressure_kpa_abs",
            config.inlet_pressure_kpa_abs,
        ),
        steam_to_eb_ratio=FIXED_STEAM_TO_EB_RATIO,
        bed_thicknesses_m=tuple(
            suggest_float(trial, f"stage_{index}_bed_thickness_m", parameter_range)
            for index, parameter_range in enumerate(
                config.bed_thicknesses_m,
                start=1,
            )
        ),
    )


def suggest_float(
    trial: optuna.Trial,
    name: str,
    parameter_range: ParameterRange,
) -> float:
    """ParameterRange を Optuna の suggest_float に変換する。"""
    return trial.suggest_float(name, parameter_range.lower, parameter_range.upper)


def reactor_case_from_candidate(candidate: RadialReactorCandidate) -> ReactorCaseLike:
    """候補条件から plant convergence 用の radial 反応器 case を作る。"""
    conditions = replace(
        DEFAULT_STYRENE_RADIAL_REACTOR_CASE.conditions,
        inlet_pressure_pa=candidate.inlet_pressure_kpa_abs * 1000.0,
        stage_inlet_temperatures_k=tuple(
            temperature_c + 273.15
            for temperature_c in candidate.stage_inlet_temperatures_c
        ),
        bed_thicknesses_m=candidate.bed_thicknesses_m,
    )
    return RadialReactorCase(
        feed=DEFAULT_STYRENE_RADIAL_REACTOR_CASE.feed,
        conditions=conditions,
    )


def validate_reactor_result(result: ReactorResult) -> None:
    """全体最適化 trial で採用する radial 反応器結果か確認する。"""
    constraints = (
        ("pressure_positive_ok", result.log.pressure_positive_ok),
        ("atom_balance_ok", result.log.atom_balance_ok),
        ("ergun_range_ok", result.log.ergun_range_ok),
        ("outlet_pressure_ok", result.log.outlet_pressure_ok),
    )
    for name, value in constraints:
        if value is False:
            raise ValueError(f"{name} is false")
    if result.outlet.stream.styrene - result.log.stage_logs[0].inlet.styrene <= 0.0:
        raise ValueError("styrene production is not positive")


def save_candidate_attrs(
    trial: optuna.Trial,
    candidate: RadialReactorCandidate,
) -> None:
    """候補条件を trial 属性へ保存する。"""
    trial.set_user_attr("reactor_type", "radial")
    trial.set_user_attr("stage_count", candidate.stage_count)
    trial.set_user_attr("inlet_pressure_kpa_abs", candidate.inlet_pressure_kpa_abs)
    trial.set_user_attr("steam_to_eb_ratio", candidate.steam_to_eb_ratio)
    for index, temperature_c in enumerate(
        candidate.stage_inlet_temperatures_c,
        start=1,
    ):
        trial.set_user_attr(f"stage_{index}_temperature_c", temperature_c)
    for index, bed_thickness_m in enumerate(candidate.bed_thicknesses_m, start=1):
        trial.set_user_attr(f"stage_{index}_bed_thickness_m", bed_thickness_m)


def save_separator_candidate_attrs(
    trial: optuna.Trial,
    candidate: SeparatorOperatingCandidate,
) -> None:
    """分離器操作候補を trial 属性へ保存する。"""
    trial.set_user_attr("decanter_1_temperature_c", candidate.decanter_1_temperature_c)
    trial.set_user_attr("sm_column_reflux_ratio", candidate.sm_column_reflux_ratio)


def save_fixed_condition_attrs(trial: optuna.Trial) -> None:
    """固定条件であることを trial 属性へ明示する。"""
    trial.set_user_attr("fixed_steam_to_eb_ratio", FIXED_STEAM_TO_EB_RATIO)
    trial.set_user_attr(
        "fixed_decanter_1_temperature_c",
        FIXED_DECANTER_1_TEMPERATURE_C,
    )
    trial.set_user_attr(
        "fixed_sm_column_reflux_ratio",
        FIXED_SM_COLUMN_REFLUX_RATIO,
    )


def result_attrs(
    convergence_result: PlantConvergenceResult,
    cost_result: WholePlantCostResult,
    separator_candidate: SeparatorOperatingCandidate,
) -> dict[str, TrialAttrValue]:
    """収束結果とコスト評価結果から trial 属性を作る。"""
    final = convergence_result.final_iteration
    reactor_result = final.reactor_result
    if reactor_result is None:
        raise ValueError("final reactor_result is missing")
    attrs: dict[str, TrialAttrValue] = {
        "annual_profit_yen_per_year": cost_result.annual_profit_yen_per_year,
        "revenue_yen_per_year": cost_result.revenue.total_yen_per_year,
        "raw_material_yen_per_year": cost_result.raw_material.total_yen_per_year,
        "annualized_equipment_yen_per_year": cost_result.capital.annualized_equipment_yen_per_year,
        "utility_yen_per_year": cost_result.utility.total_yen_per_year,
        "fixed_operating_yen_per_year": cost_result.fixed_operating.total_yen_per_year,
        "heat_recovery_duty_kw": cost_result.capital.heat_recovery.recovered_duty_kw,
        "eb_conversion": reactor_result.eb_conversion,
        "styrene_selectivity": reactor_result.styrene_selectivity,
        "outlet_pressure_kpa": reactor_result.outlet.pressure_kpa,
        "total_catalyst_volume_m3": reactor_result.log.total_catalyst_volume_m3,
        "total_catalyst_mass_kg": reactor_result.log.total_catalyst_mass_kg,
        "reactor_pressure_drop_kpa": reactor_result.log.reactor_pressure_drop_kpa,
        "total_pressure_drop_kpa": reactor_result.log.total_pressure_drop_kpa,
        "sm_product_kmol_h": final.sm_product_kmol_h,
        "fresh_eb_kmol_h": convergence_result.feed_plan.steady_fresh_feed.hydrocarbon_kmol_h,
        "fresh_h2o_kmol_h": convergence_result.feed_plan.steady_fresh_feed.steam_kmol_h,
        "eb_recycle_kmol_h": final.output_eb_recycle_kmol_h,
        "h2o_recycle_kmol_h": final.output_h2o_recycle_kmol_h,
        "offgas_total_kmol_h": stream_total(final.plant_record.streams.get("off_gas")),
        "decanter_1_temperature_c": separator_candidate.decanter_1_temperature_c,
        "sm_column_reflux_ratio": separator_candidate.sm_column_reflux_ratio,
        "fixed_steam_to_eb_ratio": FIXED_STEAM_TO_EB_RATIO,
        "fixed_decanter_1_temperature_c": FIXED_DECANTER_1_TEMPERATURE_C,
        "fixed_sm_column_reflux_ratio": FIXED_SM_COLUMN_REFLUX_RATIO,
    }
    for stage_log in reactor_result.log.stage_logs:
        prefix = f"stage_{stage_log.stage_index}"
        attrs[f"{prefix}_bed_height_m"] = stage_log.bed_height_m
        attrs[f"{prefix}_inlet_velocity_m_per_s"] = (
            stage_log.inlet_superficial_velocity_m_per_s
        )
        attrs[f"{prefix}_outlet_velocity_m_per_s"] = (
            stage_log.outlet_superficial_velocity_m_per_s
        )
        attrs[f"{prefix}_outer_radius_m"] = stage_log.outer_radius_m
    return attrs


def save_result_attrs(
    trial: optuna.Trial,
    result: TrialWorkerSuccess,
) -> None:
    """worker 結果を trial 属性へ保存する。"""
    save_user_attrs(trial=trial, attrs=result.user_attrs)


def save_user_attrs(trial: optuna.Trial, attrs: dict[str, TrialAttrValue]) -> None:
    """user_attrs を Optuna trial へ保存する。"""
    for key, value in attrs.items():
        trial.set_user_attr(key, value)


def stream_total(stream: PlantStreamRecord | None) -> float:
    """stream の total molar flow を返す。欠損時は 0 とする。"""
    if stream is None or stream.total_molar_flow_kmol_h is None:
        return 0.0
    return stream.total_molar_flow_kmol_h


def read_sm_product_from_record(record: PlantRunRecord) -> float | None:
    """ログ用に SM product 流量を安全に読む。"""
    try:
        return read_sm_product_kmol_h(record)
    except Exception:
        return None


def format_optional_log_float(value: float | None) -> str:
    """ログ用に None を含む数値を整形する。"""
    if value is None:
        return "n/a"
    return f"{value:.6f}"


def format_key_result_attrs(attrs: dict[str, TrialAttrValue]) -> str:
    """簡易ログへ残す主要結果属性を整形する。"""
    if not attrs:
        return "n/a"
    keys = (
        "eb_conversion",
        "styrene_selectivity",
        "sm_product_kmol_h",
        "annual_profit_yen_per_year",
        "fresh_eb_kmol_h",
        "fresh_h2o_kmol_h",
        "eb_recycle_kmol_h",
        "h2o_recycle_kmol_h",
        "heat_recovery_duty_kw",
        "decanter_1_temperature_c",
        "sm_column_reflux_ratio",
    )
    parts: list[str] = []
    for key in keys:
        value = attrs.get(key)
        if isinstance(value, float):
            parts.append(f"{key}={value:.6g}")
        elif value is not None:
            parts.append(f"{key}={value}")
    return " ".join(parts) if parts else "n/a"


def format_candidate(candidate: RadialReactorCandidate) -> str:
    """候補条件をログ用文字列にする。"""
    temperatures = ", ".join(
        f"{value:.2f}" for value in candidate.stage_inlet_temperatures_c
    )
    thicknesses = ", ".join(f"{value:.3f}" for value in candidate.bed_thicknesses_m)
    return (
        f"reactor=radial stage_count={candidate.stage_count} T=[{temperatures}] degC "
        f"P={candidate.inlet_pressure_kpa_abs:.3f} kPa abs "
        f"S/EB={candidate.steam_to_eb_ratio:.3f} thickness=[{thicknesses}] m"
    )


def format_separator_candidate(candidate: SeparatorOperatingCandidate) -> str:
    """分離器操作候補をログ用文字列にする。"""
    return (
        f"separator T_decanter1={candidate.decanter_1_temperature_c:.2f} degC "
        f"R_SM={candidate.sm_column_reflux_ratio:.4f}"
    )


def configure_file_logging() -> None:
    """ローテーション付きファイルログを設定する。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logging.getLogger().addHandler(handler)


def configure_worker_detail_logging() -> None:
    """worker process 用の詳細ログを設定する。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        DETAIL_LOG_PATH,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root_logger.addHandler(handler)


if __name__ == "__main__":
    tune_whole_plant_radial2_fixed_final_main()
