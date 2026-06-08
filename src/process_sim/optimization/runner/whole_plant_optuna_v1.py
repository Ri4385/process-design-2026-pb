"""全体プラント年収支を目的関数にする Optuna runner v1。"""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal, cast

import optuna
from optuna.samplers import TPESampler

from process_sim.cli import ReactorModelName
from process_sim.optimization.models import ParameterRange
from process_sim.optimization.reactor.parameters import (
    AxialParetoCandidate,
    AxialParetoParameterConfig,
    RADIAL_INLET_SUPERFICIAL_VELOCITY_M_PER_S,
    RadialReactorCandidate,
    RadialReactorParameterConfig,
    THREE_STAGE_AXIAL_PARETO_PARAMETER_CONFIG,
    THREE_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
    TWO_STAGE_AXIAL_PARETO_PARAMETER_CONFIG,
    TWO_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
)
from process_sim.plant.const import DEFAULT_HYSYS_CASE_PATH, DEFAULT_TARGET_SM_KMOL_H
from process_sim.plant.convergence import PlantConvergenceResult, run_production_target_convergence
from process_sim.plant.cost.evaluation import evaluate_whole_plant_cost
from process_sim.plant.cost.models import WholePlantCostResult
from process_sim.plant.hysys_controls import build_inlet_control_plan
from process_sim.plant.models import PlantRunRecord, PlantStreamRecord
from process_sim.plant.production_target import FeedTuningOptions, InitialRecycleGuessPolicy, ReactorCaseLike
from process_sim.plant.runner import configure_logging
from process_sim.plant.session_runner import OpenHysysPlantRunner, run_reactor_case
from process_sim.reactor.cases.styrene_default import DEFAULT_STYRENE_REACTOR_CASE, ReactorCase
from process_sim.reactor.cases.styrene_radial_default import DEFAULT_STYRENE_RADIAL_REACTOR_CASE, RadialReactorCase
from process_sim.reactor.core.models import ReactorResult


logger = logging.getLogger(__name__)

ReactorType = Literal["radial", "axial"]
Candidate = RadialReactorCandidate | AxialParetoCandidate
Config = RadialReactorParameterConfig | AxialParetoParameterConfig

STORAGE_PATH = Path("data") / "optuna" / "whole_plant_optuna_v1.db"
LOG_DIR = Path("logs")
LOG_PATH = LOG_DIR / "whole_plant_optuna_v1.log"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5
SEED = 42

TARGET_EFFECTIVE_TRIALS_BY_STUDY: dict[str, int] = {
    "radial_2stage_whole_plant_profit_v1": 100,
    "radial_3stage_whole_plant_profit_v1": 100,
    "axial_2stage_whole_plant_profit_v1": 0,
    "axial_3stage_whole_plant_profit_v1": 0,
}

TWO_STAGE_RADIAL_WHOLE_PLANT_CONFIG = replace(
    TWO_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
    inlet_pressure_kpa_abs=ParameterRange(lower=80.0, upper=200.0),
)
THREE_STAGE_RADIAL_WHOLE_PLANT_CONFIG = replace(
    THREE_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
    inlet_pressure_kpa_abs=ParameterRange(lower=100.0, upper=200.0),
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
    """全体最適化 v1 の study 設定。"""

    study_name: str
    reactor_type: ReactorType
    reactor_model: ReactorModelName
    parameter_config: Config


STUDY_CONFIGS: tuple[StudyConfig, ...] = (
    StudyConfig(
        study_name="radial_2stage_whole_plant_profit_v1",
        reactor_type="radial",
        reactor_model="radial",
        parameter_config=TWO_STAGE_RADIAL_WHOLE_PLANT_CONFIG,
    ),
    StudyConfig(
        study_name="radial_3stage_whole_plant_profit_v1",
        reactor_type="radial",
        reactor_model="radial",
        parameter_config=THREE_STAGE_RADIAL_WHOLE_PLANT_CONFIG,
    ),
    StudyConfig(
        study_name="axial_2stage_whole_plant_profit_v1",
        reactor_type="axial",
        reactor_model="pfr",
        parameter_config=TWO_STAGE_AXIAL_WHOLE_PLANT_CONFIG,
    ),
    StudyConfig(
        study_name="axial_3stage_whole_plant_profit_v1",
        reactor_type="axial",
        reactor_model="pfr",
        parameter_config=THREE_STAGE_AXIAL_WHOLE_PLANT_CONFIG,
    ),
)


def tune_whole_plant_optuna_v1_main() -> None:
    """全体プラント年収支の Optuna 探索を累積目標まで進める。"""
    configure_logging()
    configure_file_logging()
    storage_url = prepare_storage_url()
    for config in STUDY_CONFIGS:
        study = create_or_load_study(study_name=config.study_name, storage_url=storage_url)
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
        sampler=TPESampler(seed=SEED),
        storage=storage_url,
        load_if_exists=True,
    )


def effective_trial_count(study: optuna.Study) -> int:
    """完了または prune 済みの trial 数を返す。"""
    return sum(
        trial.state in {optuna.trial.TrialState.COMPLETE, optuna.trial.TrialState.PRUNED}
        for trial in study.trials
    )


def run_study(study: optuna.Study, config: StudyConfig, target_trial_count: int) -> None:
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


def objective(trial: optuna.Trial, config: StudyConfig) -> float:
    """Trial 条件で plant を収束させ、全体年収支を返す。"""
    candidate = suggest_candidate(
        trial=trial,
        reactor_type=config.reactor_type,
        config=config.parameter_config,
    )
    save_candidate_attrs(trial=trial, reactor_type=config.reactor_type, candidate=candidate)
    reactor_case = reactor_case_from_candidate(reactor_type=config.reactor_type, candidate=candidate)
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

    try:
        with OpenHysysPlantRunner(
            case_path=DEFAULT_HYSYS_CASE_PATH,
            reactor_model=config.reactor_model,
            log_reactor_detail=False,
        ) as plant_runner:
            validating_runner = ValidatingPlantRunner(
                plant_runner=plant_runner,
                reactor_model=config.reactor_model,
            )
            convergence_result = run_production_target_convergence(
                target_sm_kmol_h=DEFAULT_TARGET_SM_KMOL_H,
                production_target_runner=validating_runner,
                convergence_runner=validating_runner,
                reactor_model=config.reactor_model,
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
    except Exception as exc:
        reason = str(exc)
        trial.set_user_attr("prune_reason", reason)
        logger.info(
            "[pruned] study=%s trial=%s %s reason=%s",
            config.study_name,
            trial.number,
            format_candidate(candidate),
            reason,
        )
        raise optuna.TrialPruned(reason) from exc

    save_result_attrs(
        trial=trial,
        convergence_result=convergence_result,
        cost_result=cost_result,
    )
    logger.info(
        "[finished] study=%s trial=%s objective=%.6e %s",
        config.study_name,
        trial.number,
        cost_result.annual_profit_yen_per_year,
        format_candidate(candidate),
    )
    return cost_result.annual_profit_yen_per_year


class ValidatingPlantRunner:
    """HYSYS へ渡す前に反応器制約を確認する runner wrapper。"""

    def __init__(
        self,
        plant_runner: OpenHysysPlantRunner,
        reactor_model: ReactorModelName,
    ) -> None:
        self.plant_runner = plant_runner
        self.reactor_model = reactor_model
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
        validate_reactor_result(precheck_result)
        record = self.plant_runner(reactor_case)
        if isinstance(self.plant_runner.last_reactor_result, ReactorResult):
            self.last_reactor_result = self.plant_runner.last_reactor_result
        else:
            self.last_reactor_result = precheck_result
        return record


def suggest_candidate(trial: optuna.Trial, reactor_type: ReactorType, config: Config) -> Candidate:
    """探索空間から反応器候補を生成する。"""
    if reactor_type == "radial" and isinstance(config, RadialReactorParameterConfig):
        return RadialReactorCandidate(
            stage_inlet_temperatures_c=tuple(
                suggest_float(trial, f"stage_{index}_temperature_c", parameter_range)
                for index, parameter_range in enumerate(config.stage_inlet_temperatures_c, start=1)
            ),
            inlet_pressure_kpa_abs=suggest_float(
                trial,
                "inlet_pressure_kpa_abs",
                config.inlet_pressure_kpa_abs,
            ),
            steam_to_eb_ratio=suggest_float(trial, "steam_to_eb_ratio", config.steam_to_eb_ratio),
            bed_thicknesses_m=tuple(
                suggest_float(trial, f"stage_{index}_bed_thickness_m", parameter_range)
                for index, parameter_range in enumerate(config.bed_thicknesses_m, start=1)
            ),
        )
    if reactor_type == "axial" and isinstance(config, AxialParetoParameterConfig):
        return AxialParetoCandidate(
            stage_inlet_temperatures_c=tuple(
                suggest_float(trial, f"stage_{index}_temperature_c", parameter_range)
                for index, parameter_range in enumerate(config.stage_inlet_temperatures_c, start=1)
            ),
            inlet_pressure_kpa_abs=suggest_float(
                trial,
                "inlet_pressure_kpa_abs",
                config.inlet_pressure_kpa_abs,
            ),
            steam_to_eb_ratio=suggest_float(trial, "steam_to_eb_ratio", config.steam_to_eb_ratio),
            stage_ld_ratios=tuple(
                suggest_float(trial, f"stage_{index}_ld_ratio", parameter_range)
                for index, parameter_range in enumerate(config.stage_ld_ratios, start=1)
            ),
        )
    raise TypeError("reactor_type and parameter config do not match")


def suggest_float(trial: optuna.Trial, name: str, parameter_range: ParameterRange) -> float:
    """ParameterRange を Optuna の suggest_float に変換する。"""
    return trial.suggest_float(name, parameter_range.lower, parameter_range.upper)


def reactor_case_from_candidate(reactor_type: ReactorType, candidate: Candidate) -> ReactorCaseLike:
    """候補条件から plant convergence 用の反応器 case を作る。"""
    if reactor_type == "radial" and isinstance(candidate, RadialReactorCandidate):
        conditions = replace(
            DEFAULT_STYRENE_RADIAL_REACTOR_CASE.conditions,
            inlet_pressure_pa=candidate.inlet_pressure_kpa_abs * 1000.0,
            stage_inlet_temperatures_k=tuple(
                temperature_c + 273.15 for temperature_c in candidate.stage_inlet_temperatures_c
            ),
            inlet_superficial_velocity_m_per_s=RADIAL_INLET_SUPERFICIAL_VELOCITY_M_PER_S,
            bed_thicknesses_m=candidate.bed_thicknesses_m,
        )
        return RadialReactorCase(feed=DEFAULT_STYRENE_RADIAL_REACTOR_CASE.feed, conditions=conditions)
    if reactor_type == "axial" and isinstance(candidate, AxialParetoCandidate):
        conditions = replace(
            DEFAULT_STYRENE_REACTOR_CASE.conditions,
            pressure_kpa=candidate.inlet_pressure_kpa_abs,
            stage_inlet_temperatures_c=candidate.stage_inlet_temperatures_c,
            inlet_superficial_velocity_m_per_s=2.0,
            stage_ld_ratios=candidate.stage_ld_ratios,
        )
        return ReactorCase(feed=DEFAULT_STYRENE_REACTOR_CASE.feed, conditions=conditions)
    raise TypeError("reactor_type and candidate do not match")


def validate_reactor_result(result: ReactorResult) -> None:
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
    if result.log.radial_bed_outlet_velocity_ok is False:
        raise ValueError("radial_bed_outlet_velocity_ok is false")
    if result.log.length_ok is False:
        raise ValueError("length_ok is false")
    if result.log.velocity_range_ok is False:
        raise ValueError("velocity_range_ok is false")
    if result.outlet.stream.styrene - result.log.stage_logs[0].inlet.styrene <= 0.0:
        raise ValueError("styrene production is not positive")


def save_candidate_attrs(trial: optuna.Trial, reactor_type: ReactorType, candidate: Candidate) -> None:
    """候補条件を trial 属性へ保存する。"""
    trial.set_user_attr("reactor_type", reactor_type)
    trial.set_user_attr("stage_count", candidate.stage_count)
    trial.set_user_attr("inlet_pressure_kpa_abs", candidate.inlet_pressure_kpa_abs)
    trial.set_user_attr("steam_to_eb_ratio", candidate.steam_to_eb_ratio)
    for index, temperature_c in enumerate(candidate.stage_inlet_temperatures_c, start=1):
        trial.set_user_attr(f"stage_{index}_temperature_c", temperature_c)
    if isinstance(candidate, RadialReactorCandidate):
        for index, bed_thickness_m in enumerate(candidate.bed_thicknesses_m, start=1):
            trial.set_user_attr(f"stage_{index}_bed_thickness_m", bed_thickness_m)
    else:
        for index, ld_ratio in enumerate(candidate.stage_ld_ratios, start=1):
            trial.set_user_attr(f"stage_{index}_ld_ratio", ld_ratio)


def save_result_attrs(
    trial: optuna.Trial,
    convergence_result: PlantConvergenceResult,
    cost_result: WholePlantCostResult,
) -> None:
    """収束結果とコスト評価結果を trial 属性へ保存する。"""
    final = convergence_result.final_iteration
    reactor_result = final.reactor_result
    if reactor_result is None:
        raise ValueError("final reactor_result is missing")
    trial.set_user_attr("annual_profit_yen_per_year", cost_result.annual_profit_yen_per_year)
    trial.set_user_attr("revenue_yen_per_year", cost_result.revenue.total_yen_per_year)
    trial.set_user_attr("raw_material_yen_per_year", cost_result.raw_material.total_yen_per_year)
    trial.set_user_attr("annualized_equipment_yen_per_year", cost_result.capital.annualized_equipment_yen_per_year)
    trial.set_user_attr("utility_yen_per_year", cost_result.utility.total_yen_per_year)
    trial.set_user_attr("fixed_operating_yen_per_year", cost_result.fixed_operating.total_yen_per_year)
    trial.set_user_attr("heat_recovery_duty_kw", cost_result.capital.heat_recovery.recovered_duty_kw)
    trial.set_user_attr("eb_conversion", reactor_result.eb_conversion)
    trial.set_user_attr("styrene_selectivity", reactor_result.styrene_selectivity)
    trial.set_user_attr("outlet_pressure_kpa", reactor_result.outlet.pressure_kpa)
    trial.set_user_attr("total_catalyst_volume_m3", reactor_result.log.total_catalyst_volume_m3)
    trial.set_user_attr("total_catalyst_mass_kg", reactor_result.log.total_catalyst_mass_kg)
    trial.set_user_attr("reactor_pressure_drop_kpa", reactor_result.log.reactor_pressure_drop_kpa)
    trial.set_user_attr("total_pressure_drop_kpa", reactor_result.log.total_pressure_drop_kpa)
    trial.set_user_attr("sm_product_kmol_h", final.sm_product_kmol_h)
    trial.set_user_attr("fresh_eb_kmol_h", convergence_result.feed_plan.steady_fresh_feed.hydrocarbon_kmol_h)
    trial.set_user_attr("fresh_h2o_kmol_h", convergence_result.feed_plan.steady_fresh_feed.steam_kmol_h)
    trial.set_user_attr("eb_recycle_kmol_h", final.output_eb_recycle_kmol_h)
    trial.set_user_attr("h2o_recycle_kmol_h", final.output_h2o_recycle_kmol_h)
    trial.set_user_attr("offgas_total_kmol_h", stream_total(final.plant_record.streams.get("off_gas")))


def stream_total(stream: PlantStreamRecord | None) -> float:
    """stream の total molar flow を返す。欠損時は 0 とする。"""
    if stream is None or stream.total_molar_flow_kmol_h is None:
        return 0.0
    return stream.total_molar_flow_kmol_h


def format_candidate(candidate: Candidate) -> str:
    """候補条件をログ用文字列にする。"""
    temperatures = ", ".join(f"{value:.2f}" for value in candidate.stage_inlet_temperatures_c)
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
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(handler)


if __name__ == "__main__":
    tune_whole_plant_optuna_v1_main()
