"""全体プラント年収支を目的関数にする Optuna runner v2。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import logging
from logging.handlers import RotatingFileHandler
import multiprocessing as mp
from multiprocessing.queues import Queue
import queue
from pathlib import Path
from typing import Callable, Literal, cast

import optuna
from optuna.samplers import TPESampler

from process_sim.cli import ReactorModelName
from process_sim.optimization.models import ParameterRange
from process_sim.optimization.reactor.parameters import (
    AxialParetoCandidate,
    AxialParetoParameterConfig,
    RadialReactorCandidate,
    RadialReactorParameterConfig,
    THREE_STAGE_AXIAL_PARETO_PARAMETER_CONFIG,
    THREE_STAGE_WHOLE_PLANT_V2_RADIAL_REACTOR_PARAMETER_CONFIG,
    TWO_STAGE_AXIAL_PARETO_PARAMETER_CONFIG,
    TWO_STAGE_WHOLE_PLANT_V2_RADIAL_REACTOR_PARAMETER_CONFIG,
)
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
from process_sim.reactor.cases.styrene_default import (
    DEFAULT_STYRENE_REACTOR_CASE,
    ReactorCase,
)
from process_sim.reactor.cases.styrene_radial_default import (
    DEFAULT_STYRENE_RADIAL_REACTOR_CASE,
    RadialReactorCase,
)
from process_sim.reactor.core.models import ReactorResult


logger = logging.getLogger(__name__)

ReactorType = Literal["radial", "axial"]
Candidate = RadialReactorCandidate | AxialParetoCandidate
Config = RadialReactorParameterConfig | AxialParetoParameterConfig
TrialAttrValue = str | int | float | bool | None

STORAGE_PATH = Path("data") / "optuna" / "whole_plant_optuna_v2.db"
LOG_DIR = Path("logs")
LOG_PATH = LOG_DIR / "whole_plant_optuna_v2.log"
DETAIL_LOG_PATH = LOG_DIR / "whole_plant_optuna_v2_detail.log"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5
SEED = 42
N_STARTUP_TRIALS = 15

TARGET_EFFECTIVE_TRIALS_BY_STUDY: dict[str, int] = {
    "radial_2stage_whole_plant_profit_v2": 50,
    "radial_3stage_whole_plant_profit_v2": 100,
    "axial_2stage_whole_plant_profit_v2": 0,
    "axial_3stage_whole_plant_profit_v2": 0,
}

TWO_STAGE_RADIAL_WHOLE_PLANT_V2_CONFIG = (
    TWO_STAGE_WHOLE_PLANT_V2_RADIAL_REACTOR_PARAMETER_CONFIG
)
THREE_STAGE_RADIAL_WHOLE_PLANT_V2_CONFIG = (
    THREE_STAGE_WHOLE_PLANT_V2_RADIAL_REACTOR_PARAMETER_CONFIG
)
TWO_STAGE_AXIAL_WHOLE_PLANT_CONFIG = replace(
    TWO_STAGE_AXIAL_PARETO_PARAMETER_CONFIG,
    inlet_pressure_kpa_abs=ParameterRange(lower=80.0, upper=300.0),
)
THREE_STAGE_AXIAL_WHOLE_PLANT_CONFIG = replace(
    THREE_STAGE_AXIAL_PARETO_PARAMETER_CONFIG,
    inlet_pressure_kpa_abs=ParameterRange(lower=100.0, upper=300.0),
)


@dataclass(frozen=True)
class StudyConfig:
    """全体最適化 v2 の study 設定。"""

    study_name: str
    reactor_type: ReactorType
    reactor_model: ReactorModelName
    parameter_config: Config


@dataclass(frozen=True)
class TrialWorkerSuccess:
    """trial worker の正常終了結果。"""

    objective_value: float
    user_attrs: dict[str, TrialAttrValue]


def empty_trial_attrs() -> dict[str, TrialAttrValue]:
    """空の trial 属性 dict を返す。"""
    return {}


@dataclass(frozen=True)
class TrialWorkerFailure:
    """trial worker の異常終了結果。"""

    reason: str
    user_attrs: dict[str, TrialAttrValue] = field(default_factory=empty_trial_attrs)


TrialWorkerResult = TrialWorkerSuccess | TrialWorkerFailure


STUDY_CONFIGS: tuple[StudyConfig, ...] = (
    StudyConfig(
        study_name="radial_2stage_whole_plant_profit_v2",
        reactor_type="radial",
        reactor_model="radial",
        parameter_config=TWO_STAGE_RADIAL_WHOLE_PLANT_V2_CONFIG,
    ),
    StudyConfig(
        study_name="radial_3stage_whole_plant_profit_v2",
        reactor_type="radial",
        reactor_model="radial",
        parameter_config=THREE_STAGE_RADIAL_WHOLE_PLANT_V2_CONFIG,
    ),
    StudyConfig(
        study_name="axial_2stage_whole_plant_profit_v2",
        reactor_type="axial",
        reactor_model="pfr",
        parameter_config=TWO_STAGE_AXIAL_WHOLE_PLANT_CONFIG,
    ),
    StudyConfig(
        study_name="axial_3stage_whole_plant_profit_v2",
        reactor_type="axial",
        reactor_model="pfr",
        parameter_config=THREE_STAGE_AXIAL_WHOLE_PLANT_CONFIG,
    ),
)


def tune_whole_plant_optuna_v2_main() -> None:
    """全体プラント年収支の Optuna 探索を累積目標まで進める。"""
    configure_logging()
    configure_file_logging()
    run_hysys_prewarm_with_timeout(
        case_path=DEFAULT_HYSYS_CASE_PATH,
        timeout_seconds=DEFAULT_HYSYS_PREWARM_TIMEOUT_SECONDS,
    )
    storage_url = prepare_storage_url()
    for config in STUDY_CONFIGS:
        study = create_or_load_study(
            study_name=config.study_name, storage_url=storage_url
        )
        run_study(
            study=study,
            config=config,
            target_trial_count=TARGET_EFFECTIVE_TRIALS_BY_STUDY[config.study_name],
        )


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
        logger.info("[prewarm started] case_path=%s mode=default_radial_plant_run", case_path)
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
    logger.info("[prewarm finished] case_path=%s mode=default_radial_plant_run", case_path)
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


def run_study(
    study: optuna.Study, config: StudyConfig, target_trial_count: int
) -> None:
    """1つの study を指定した累積 trial 数まで進める。"""
    stored_trial_count_before = len(study.trials)
    effective_trial_count_before = effective_trial_count(study)
    added_trial_count = max(target_trial_count - effective_trial_count_before, 0)
    logger.info(
        "[start] study=%s reactor=%s stage_count=%s add_trials=%s effective_trials=%s "
        "stored_trials=%s target_trials=%s",
        study.study_name,
        config.reactor_type,
        config.parameter_config.stage_count,
        added_trial_count,
        effective_trial_count_before,
        stored_trial_count_before,
        target_trial_count,
    )
    study.optimize(
        lambda trial: objective(trial=trial, config=config),
        n_trials=added_trial_count,
    )
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


def objective(trial: optuna.Trial, config: StudyConfig) -> float:
    """Trial 条件で plant を収束させ、全体年収支を返す。"""
    candidate = suggest_candidate(
        trial=trial,
        reactor_type=config.reactor_type,
        config=config.parameter_config,
    )
    save_candidate_attrs(
        trial=trial, reactor_type=config.reactor_type, candidate=candidate
    )
    reactor_case = reactor_case_from_candidate(
        reactor_type=config.reactor_type, candidate=candidate
    )
    feed_tuning_options = FeedTuningOptions(
        initial_guess_policy=InitialRecycleGuessPolicy(
            steam_to_eb_ratio=candidate.steam_to_eb_ratio,
        ),
    )
    logger.info(
        "[trial started] study=%s trial=%s %s",
        config.study_name,
        trial.number,
        format_candidate(candidate),
    )

    result = run_process_with_timeout(
        target=_trial_worker_entry,
        args=(
            config.reactor_type,
            config.reactor_model,
            candidate,
            reactor_case,
            feed_tuning_options,
        ),
        timeout_seconds=DEFAULT_WHOLE_PLANT_TRIAL_TIMEOUT_SECONDS,
    )
    if isinstance(result, TrialWorkerFailure):
        reason = result.reason
        trial.set_user_attr("prune_reason", reason)
        logger.info(
            "[pruned] study=%s trial=%s %s reason=%s attrs=%s",
            config.study_name,
            trial.number,
            format_candidate(candidate),
            reason,
            format_key_result_attrs(result.user_attrs),
        )
        raise optuna.TrialPruned(reason)

    save_user_attrs(trial=trial, attrs=result.user_attrs)
    logger.info(
        "[finished] study=%s trial=%s objective=%.6e %s %s",
        config.study_name,
        trial.number,
        result.objective_value,
        format_candidate(candidate),
        format_key_result_attrs(result.user_attrs),
    )
    return result.objective_value


def _trial_worker_entry(
    result_queue: Queue[TrialWorkerResult],
    reactor_type: ReactorType,
    reactor_model: ReactorModelName,
    candidate: Candidate,
    reactor_case: ReactorCaseLike,
    feed_tuning_options: FeedTuningOptions,
) -> None:
    """trial worker process の入口。"""
    configure_worker_detail_logging()
    logger.info(
        "[trial worker started] reactor=%s %s",
        reactor_type,
        format_candidate(candidate),
    )
    try:
        result = evaluate_candidate_in_worker(
            reactor_type=reactor_type,
            reactor_model=reactor_model,
            candidate=candidate,
            reactor_case=reactor_case,
            feed_tuning_options=feed_tuning_options,
        )
    except Exception as exc:
        logger.exception(
            "[trial worker failed] reactor=%s %s",
            reactor_type,
            format_candidate(candidate),
        )
        result_queue.put(TrialWorkerFailure(reason=str(exc)))
        return
    logger.info(
        "[trial worker finished] reactor=%s objective=%.6e %s %s",
        reactor_type,
        result.objective_value,
        format_candidate(candidate),
        format_key_result_attrs(result.user_attrs),
    )
    result_queue.put(result)


def evaluate_candidate_in_worker(
    reactor_type: ReactorType,
    reactor_model: ReactorModelName,
    candidate: Candidate,
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
            build_inlet_control_plan(
                convergence_result=convergence_result,
                base_reactor_case=reactor_case,
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
        validate_reactor_result(result=precheck_result, reactor_type=self.reactor_type)
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


def suggest_candidate(
    trial: optuna.Trial, reactor_type: ReactorType, config: Config
) -> Candidate:
    """探索空間から反応器候補を生成する。"""
    if reactor_type == "radial" and isinstance(config, RadialReactorParameterConfig):
        return RadialReactorCandidate(
            stage_inlet_temperatures_c=tuple(
                suggest_float(trial, f"stage_{index}_temperature_c", parameter_range)
                for index, parameter_range in enumerate(
                    config.stage_inlet_temperatures_c, start=1
                )
            ),
            inlet_pressure_kpa_abs=suggest_float(
                trial,
                "inlet_pressure_kpa_abs",
                config.inlet_pressure_kpa_abs,
            ),
            steam_to_eb_ratio=suggest_float(
                trial, "steam_to_eb_ratio", config.steam_to_eb_ratio
            ),
            bed_thicknesses_m=tuple(
                suggest_float(trial, f"stage_{index}_bed_thickness_m", parameter_range)
                for index, parameter_range in enumerate(
                    config.bed_thicknesses_m, start=1
                )
            ),
        )
    if reactor_type == "axial" and isinstance(config, AxialParetoParameterConfig):
        return AxialParetoCandidate(
            stage_inlet_temperatures_c=tuple(
                suggest_float(trial, f"stage_{index}_temperature_c", parameter_range)
                for index, parameter_range in enumerate(
                    config.stage_inlet_temperatures_c, start=1
                )
            ),
            inlet_pressure_kpa_abs=suggest_float(
                trial,
                "inlet_pressure_kpa_abs",
                config.inlet_pressure_kpa_abs,
            ),
            steam_to_eb_ratio=suggest_float(
                trial, "steam_to_eb_ratio", config.steam_to_eb_ratio
            ),
            stage_ld_ratios=tuple(
                suggest_float(trial, f"stage_{index}_ld_ratio", parameter_range)
                for index, parameter_range in enumerate(config.stage_ld_ratios, start=1)
            ),
        )
    raise TypeError("reactor_type and parameter config do not match")


def suggest_float(
    trial: optuna.Trial, name: str, parameter_range: ParameterRange
) -> float:
    """ParameterRange を Optuna の suggest_float に変換する。"""
    return trial.suggest_float(name, parameter_range.lower, parameter_range.upper)


def reactor_case_from_candidate(
    reactor_type: ReactorType, candidate: Candidate
) -> ReactorCaseLike:
    """候補条件から plant convergence 用の反応器 case を作る。"""
    if reactor_type == "radial" and isinstance(candidate, RadialReactorCandidate):
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
            feed=DEFAULT_STYRENE_RADIAL_REACTOR_CASE.feed, conditions=conditions
        )
    if reactor_type == "axial" and isinstance(candidate, AxialParetoCandidate):
        conditions = replace(
            DEFAULT_STYRENE_REACTOR_CASE.conditions,
            pressure_kpa=candidate.inlet_pressure_kpa_abs,
            stage_inlet_temperatures_c=candidate.stage_inlet_temperatures_c,
            inlet_superficial_velocity_m_per_s=2.0,
            stage_ld_ratios=candidate.stage_ld_ratios,
        )
        return ReactorCase(
            feed=DEFAULT_STYRENE_REACTOR_CASE.feed, conditions=conditions
        )
    raise TypeError("reactor_type and candidate do not match")


def validate_reactor_result(result: ReactorResult, reactor_type: ReactorType) -> None:
    """全体最適化 trial で採用する反応器結果か確認する。"""
    constraints = (
        ("pressure_positive_ok", result.log.pressure_positive_ok),
        ("atom_balance_ok", result.log.atom_balance_ok),
        ("ergun_range_ok", result.log.ergun_range_ok),
        ("outlet_pressure_ok", result.log.outlet_pressure_ok),
    )
    for name, value in constraints:
        if value is False:
            raise ValueError(f"{name} is false")
    if reactor_type == "axial":
        if result.log.length_ok is False:
            raise ValueError("length_ok is false")
        if result.log.velocity_range_ok is False:
            raise ValueError("velocity_range_ok is false")
    if result.outlet.stream.styrene - result.log.stage_logs[0].inlet.styrene <= 0.0:
        raise ValueError("styrene production is not positive")


def save_candidate_attrs(
    trial: optuna.Trial, reactor_type: ReactorType, candidate: Candidate
) -> None:
    """候補条件を trial 属性へ保存する。"""
    trial.set_user_attr("reactor_type", reactor_type)
    trial.set_user_attr("stage_count", candidate.stage_count)
    trial.set_user_attr("inlet_pressure_kpa_abs", candidate.inlet_pressure_kpa_abs)
    trial.set_user_attr("steam_to_eb_ratio", candidate.steam_to_eb_ratio)
    for index, temperature_c in enumerate(
        candidate.stage_inlet_temperatures_c, start=1
    ):
        trial.set_user_attr(f"stage_{index}_temperature_c", temperature_c)
    if isinstance(candidate, RadialReactorCandidate):
        for index, bed_thickness_m in enumerate(candidate.bed_thicknesses_m, start=1):
            trial.set_user_attr(f"stage_{index}_bed_thickness_m", bed_thickness_m)
    else:
        for index, ld_ratio in enumerate(candidate.stage_ld_ratios, start=1):
            trial.set_user_attr(f"stage_{index}_ld_ratio", ld_ratio)


def result_attrs(
    convergence_result: PlantConvergenceResult,
    cost_result: WholePlantCostResult,
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
    )
    parts: list[str] = []
    for key in keys:
        value = attrs.get(key)
        if isinstance(value, float):
            parts.append(f"{key}={value:.6g}")
        elif value is not None:
            parts.append(f"{key}={value}")
    return " ".join(parts) if parts else "n/a"


def format_candidate(candidate: Candidate) -> str:
    """候補条件をログ用文字列にする。"""
    temperatures = ", ".join(
        f"{value:.2f}" for value in candidate.stage_inlet_temperatures_c
    )
    if isinstance(candidate, RadialReactorCandidate):
        thicknesses = ", ".join(f"{value:.3f}" for value in candidate.bed_thicknesses_m)
        return (
            f"reactor=radial stage_count={candidate.stage_count} T=[{temperatures}] degC "
            f"P={candidate.inlet_pressure_kpa_abs:.3f} kPa abs S/EB={candidate.steam_to_eb_ratio:.3f} "
            f"thickness=[{thicknesses}] m"
        )
    ld_ratios = ", ".join(f"{value:.3f}" for value in candidate.stage_ld_ratios)
    return (
        f"reactor=axial stage_count={candidate.stage_count} T=[{temperatures}] degC "
        f"P={candidate.inlet_pressure_kpa_abs:.3f} kPa abs S/EB={candidate.steam_to_eb_ratio:.3f} "
        f"L/D=[{ld_ratios}]"
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
    tune_whole_plant_optuna_v2_main()
