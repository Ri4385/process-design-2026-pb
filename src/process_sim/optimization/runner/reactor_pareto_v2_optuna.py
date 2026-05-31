"""radial・axial 反応器の選択率・単通反応率 Pareto front 探索。"""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal

import optuna
from optuna.samplers import NSGAIISampler

from process_sim.optimization.models import ParameterRange
from process_sim.optimization.reactor.parameters import (
    AxialParetoCandidate,
    AxialParetoParameterConfig,
    RadialReactorCandidate,
    RadialReactorParameterConfig,
    THREE_STAGE_AXIAL_PARETO_PARAMETER_CONFIG,
    THREE_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
    TWO_STAGE_AXIAL_PARETO_PARAMETER_CONFIG,
    TWO_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
)
from process_sim.reactor.core.models import RadialReactorRunConditions, ReactorResult, ReactorRunConditions
from process_sim.reactor.core.stream import ReactorFeed
from process_sim.reactor.types.staged_adiabatic_pfr import StagedAdiabaticPfrModel
from process_sim.reactor.types.staged_adiabatic_radial import StagedAdiabaticRadialFlowModel


logger = logging.getLogger(__name__)

ReactorType = Literal["radial", "axial"]
Candidate = RadialReactorCandidate | AxialParetoCandidate
Config = RadialReactorParameterConfig | AxialParetoParameterConfig

TARGET_EFFECTIVE_TRIALS_BY_REACTOR_AND_STAGE_COUNT: dict[tuple[ReactorType, int], int] = {
    ("radial", 2): 1300,
    ("radial", 3): 1300,
    ("axial", 2): 1300,
    ("axial", 3): 1300,
}
POPULATION_SIZE = 50
SEED: int | None = None
LOG_DIR = Path("logs")
LOG_PATH = LOG_DIR / "reactor_pareto_v2_optuna.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5
STORAGE_PATH = Path("data") / "optuna" / "reactor_pareto_v2_optuna.db"

PELLET_DIAMETER_M = 0.003
BED_VOID_FRACTION = 0.4312
CATALYST_BULK_DENSITY_KG_M3 = 1422.0
ERGUN_A = 1.75
ERGUN_B = 150.0
GAS_VISCOSITY_PA_S = 2.6e-5
INTERSTAGE_REHEATER_PRESSURE_DROP_PA = 20_000.0
SEGMENTS_PER_STAGE = 12_000
PROFILE_POINTS_PER_STAGE = 12
MIN_OUTLET_PRESSURE_KPA_ABS = 60.0

RADIAL_CENTER_CHANNEL_RADIUS_M = 1.0
RADIAL_INLET_SUPERFICIAL_VELOCITY_M_PER_S = 2.0
RADIAL_MIN_BED_OUTLET_VELOCITY_M_PER_S = 1.0

AXIAL_INLET_SUPERFICIAL_VELOCITY_M_PER_S = 2.0
AXIAL_MAX_STAGE_LENGTH_M = 10.0
AXIAL_MIN_SUPERFICIAL_VELOCITY_M_PER_S = 1.0
AXIAL_MAX_SUPERFICIAL_VELOCITY_M_PER_S = 3.0

PARETO_V2_BASE_FEED = ReactorFeed(
    eb=400.0,
    steam=0.0,
    styrene=0.0,
    hydrogen=0.0,
    benzene=2.0,
    toluene=2.0,
    co2=0.0,
    ethylene=0.0,
    methane=0.0,
    co=0.0,
)

TWO_STAGE_RADIAL_PARETO_V2_CONFIG = replace(
    TWO_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
    inlet_pressure_kpa_abs=ParameterRange(lower=80.0, upper=200.0),
)
THREE_STAGE_RADIAL_PARETO_V2_CONFIG = replace(
    THREE_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG,
    inlet_pressure_kpa_abs=ParameterRange(lower=100.0, upper=200.0),
)


@dataclass(frozen=True)
class StudyConfig:
    """1つの Pareto v2 study の設定。"""

    study_name: str
    reactor_type: ReactorType
    parameter_config: Config


STUDY_CONFIGS: tuple[StudyConfig, ...] = (
    StudyConfig(
        study_name="radial_2stage_selectivity_conversion_v2",
        reactor_type="radial",
        parameter_config=TWO_STAGE_RADIAL_PARETO_V2_CONFIG,
    ),
    StudyConfig(
        study_name="radial_3stage_selectivity_conversion_v2",
        reactor_type="radial",
        parameter_config=THREE_STAGE_RADIAL_PARETO_V2_CONFIG,
    ),
    StudyConfig(
        study_name="axial_2stage_selectivity_conversion_v2",
        reactor_type="axial",
        parameter_config=TWO_STAGE_AXIAL_PARETO_PARAMETER_CONFIG,
    ),
    StudyConfig(
        study_name="axial_3stage_selectivity_conversion_v2",
        reactor_type="axial",
        parameter_config=THREE_STAGE_AXIAL_PARETO_PARAMETER_CONFIG,
    ),
)


def tune_reactor_pareto_v2_main() -> None:
    """4 study の Pareto front 探索を累積目標まで進める。"""
    configure_logging()
    storage_url = prepare_storage_url()
    for config in STUDY_CONFIGS:
        study = create_or_load_study(study_name=config.study_name, storage_url=storage_url)
        run_study(
            study=study,
            config=config,
            target_trial_count=TARGET_EFFECTIVE_TRIALS_BY_REACTOR_AND_STAGE_COUNT[
                (config.reactor_type, config.parameter_config.stage_count)
            ],
        )


def prepare_storage_url() -> str:
    """SQLite storage の親ディレクトリを作り、接続 URL を返す。"""
    STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{STORAGE_PATH.as_posix()}"


def create_or_load_study(study_name: str, storage_url: str) -> optuna.Study:
    """1つの study を作成または読み込む。"""
    return optuna.create_study(
        study_name=study_name,
        directions=("maximize", "maximize"),
        sampler=NSGAIISampler(population_size=POPULATION_SIZE, seed=SEED),
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
        "[start] study=%s reactor=%s stage_count=%s add_trials=%s effective_trials=%s stored_trials=%s target_trials=%s",
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


def objective(trial: optuna.Trial, config: StudyConfig) -> tuple[float, float]:
    """反応器を評価し、SM 選択率と EB 単通反応率を返す。"""
    candidate = suggest_candidate(
        trial=trial,
        reactor_type=config.reactor_type,
        config=config.parameter_config,
    )
    trial.set_user_attr("reactor_type", config.reactor_type)
    trial.set_user_attr("stage_count", candidate.stage_count)
    try:
        feed = feed_from_ratio(candidate.steam_to_eb_ratio)
        result = run_candidate(
            reactor_type=config.reactor_type,
            candidate=candidate,
            feed=feed,
        )
        save_result_attrs(trial=trial, reactor_type=config.reactor_type, result=result)
        validate_result(reactor_type=config.reactor_type, result=result)
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

    logger.info(
        "[finished] study=%s trial=%s SM_sel=%.6f EB_conv=%.6f outlet_P=%.3f kPa "
        "catalyst_volume=%.3f m3 %s dimensions=%s",
        config.study_name,
        trial.number,
        result.styrene_selectivity,
        result.eb_conversion,
        result.outlet.pressure_kpa,
        result.log.total_catalyst_volume_m3 or 0.0,
        format_candidate(candidate),
        format_dimensions(result),
    )
    return result.styrene_selectivity, result.eb_conversion


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


def feed_from_ratio(steam_to_eb_ratio: float) -> ReactorFeed:
    """探索専用 feed を Steam/EB 比から作る。"""
    return replace(
        PARETO_V2_BASE_FEED,
        steam=PARETO_V2_BASE_FEED.eb * steam_to_eb_ratio,
    )


def run_candidate(reactor_type: ReactorType, candidate: Candidate, feed: ReactorFeed) -> ReactorResult:
    """候補条件を対応する反応器モデルで計算する。"""
    if reactor_type == "radial" and isinstance(candidate, RadialReactorCandidate):
        conditions = RadialReactorRunConditions(
            inlet_pressure_pa=candidate.inlet_pressure_kpa_abs * 1000.0,
            stage_inlet_temperatures_k=tuple(value + 273.15 for value in candidate.stage_inlet_temperatures_c),
            inlet_superficial_velocity_m_per_s=RADIAL_INLET_SUPERFICIAL_VELOCITY_M_PER_S,
            center_channel_radius_m=RADIAL_CENTER_CHANNEL_RADIUS_M,
            bed_thicknesses_m=candidate.bed_thicknesses_m,
            pellet_diameter_m=PELLET_DIAMETER_M,
            bed_void_fraction=BED_VOID_FRACTION,
            catalyst_bulk_density_kg_m3=CATALYST_BULK_DENSITY_KG_M3,
            ergun_a=ERGUN_A,
            ergun_b=ERGUN_B,
            gas_viscosity_pa_s=GAS_VISCOSITY_PA_S,
            interstage_reheater_pressure_drop_pa=INTERSTAGE_REHEATER_PRESSURE_DROP_PA,
            min_outlet_pressure_kpa_abs=MIN_OUTLET_PRESSURE_KPA_ABS,
            min_bed_outlet_velocity_m_per_s=RADIAL_MIN_BED_OUTLET_VELOCITY_M_PER_S,
            segments_per_stage=SEGMENTS_PER_STAGE,
            profile_points_per_stage=PROFILE_POINTS_PER_STAGE,
        )
        return StagedAdiabaticRadialFlowModel().run(feed=feed, conditions=conditions)
    if reactor_type == "axial" and isinstance(candidate, AxialParetoCandidate):
        conditions = ReactorRunConditions(
            pressure_kpa=candidate.inlet_pressure_kpa_abs,
            stage_inlet_temperatures_c=candidate.stage_inlet_temperatures_c,
            inlet_superficial_velocity_m_per_s=AXIAL_INLET_SUPERFICIAL_VELOCITY_M_PER_S,
            stage_ld_ratios=candidate.stage_ld_ratios,
            pellet_diameter_m=PELLET_DIAMETER_M,
            bed_void_fraction=BED_VOID_FRACTION,
            catalyst_bulk_density_kg_m3=CATALYST_BULK_DENSITY_KG_M3,
            ergun_a=ERGUN_A,
            ergun_b=ERGUN_B,
            gas_viscosity_pa_s=GAS_VISCOSITY_PA_S,
            interstage_reheater_pressure_drop_pa=INTERSTAGE_REHEATER_PRESSURE_DROP_PA,
            min_outlet_pressure_kpa_abs=MIN_OUTLET_PRESSURE_KPA_ABS,
            max_stage_length_m=AXIAL_MAX_STAGE_LENGTH_M,
            min_superficial_velocity_m_per_s=AXIAL_MIN_SUPERFICIAL_VELOCITY_M_PER_S,
            max_superficial_velocity_m_per_s=AXIAL_MAX_SUPERFICIAL_VELOCITY_M_PER_S,
            segments_per_stage=SEGMENTS_PER_STAGE,
            profile_points_per_stage=PROFILE_POINTS_PER_STAGE,
        )
        return StagedAdiabaticPfrModel().run(feed=feed, conditions=conditions)
    raise TypeError("reactor_type and candidate do not match")


def validate_result(reactor_type: ReactorType, result: ReactorResult) -> None:
    """Pareto v2 で採用する反応器結果か確認する。"""
    constraints = (
        ("pressure_positive_ok", result.log.pressure_positive_ok),
        ("atom_balance_ok", result.log.atom_balance_ok),
        ("ergun_range_ok", result.log.ergun_range_ok),
        ("outlet_pressure_ok", result.log.outlet_pressure_ok),
    )
    for name, value in constraints:
        if value is False:
            raise ValueError(f"{name} is false")
    if reactor_type == "radial" and result.log.radial_bed_outlet_velocity_ok is False:
        raise ValueError("radial_bed_outlet_velocity_ok is false")
    if reactor_type == "axial" and result.log.length_ok is False:
        raise ValueError("length_ok is false")
    if reactor_type == "axial" and result.log.velocity_range_ok is False:
        raise ValueError("velocity_range_ok is false")
    styrene_net_kmol_h = result.outlet.stream.styrene - result.log.stage_logs[0].inlet.styrene
    if styrene_net_kmol_h <= 0.0:
        raise ValueError("styrene production is not positive")


def save_result_attrs(trial: optuna.Trial, reactor_type: ReactorType, result: ReactorResult) -> None:
    """目的値、制約、寸法を SQLite storage に保存する。"""
    attrs: dict[str, float | bool | str | None] = {
        "reactor_type": reactor_type,
        "stage_count": len(result.log.stage_logs),
        "eb_conversion": result.eb_conversion,
        "styrene_selectivity": result.styrene_selectivity,
        "outlet_pressure_kpa": result.outlet.pressure_kpa,
        "reactor_pressure_drop_kpa": result.log.reactor_pressure_drop_kpa,
        "reheat_pressure_drop_kpa": result.log.reheat_pressure_drop_kpa,
        "total_pressure_drop_kpa": result.log.total_pressure_drop_kpa,
        "total_catalyst_volume_m3": result.log.total_catalyst_volume_m3,
        "total_catalyst_mass_kg": result.log.total_catalyst_mass_kg,
        "pressure_positive_ok": result.log.pressure_positive_ok,
        "atom_balance_ok": result.log.atom_balance_ok,
        "ergun_range_ok": result.log.ergun_range_ok,
        "outlet_pressure_ok": result.log.outlet_pressure_ok,
        "radial_bed_outlet_velocity_ok": result.log.radial_bed_outlet_velocity_ok,
        "length_ok": result.log.length_ok,
        "velocity_range_ok": result.log.velocity_range_ok,
    }
    for key, value in attrs.items():
        trial.set_user_attr(key, value)
    for stage_log in result.log.stage_logs:
        prefix = f"stage_{stage_log.stage_index}_"
        stage_attrs = {
            "center_channel_radius_m": stage_log.inner_radius_m,
            "bed_thickness_m": stage_log.bed_thickness_m,
            "bed_outer_radius_m": stage_log.outer_radius_m,
            "bed_height_m": stage_log.bed_height_m,
            "ld_ratio": stage_log.ld_ratio,
            "cross_section_area_m2": stage_log.cross_section_area_m2,
            "diameter_m": stage_log.equivalent_diameter_m,
            "length_m": stage_log.stage_length_m,
            "catalyst_volume_m3": stage_log.catalyst_volume_m3,
            "inlet_velocity_m_per_s": stage_log.inlet_superficial_velocity_m_per_s,
            "outlet_velocity_m_per_s": stage_log.outlet_superficial_velocity_m_per_s,
            "min_velocity_m_per_s": stage_log.min_superficial_velocity_m_per_s,
            "max_velocity_m_per_s": stage_log.max_superficial_velocity_m_per_s,
        }
        for key, value in stage_attrs.items():
            if value is not None:
                trial.set_user_attr(f"{prefix}{key}", value)


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


def format_dimensions(result: ReactorResult) -> str:
    """各段寸法をログ用文字列にする。"""
    values: list[str] = []
    for log in result.log.stage_logs:
        if log.outer_radius_m is not None:
            values.append(
                f"stage_{log.stage_index}(D={2.0 * log.outer_radius_m:.3f}m,H={log.bed_height_m or 0.0:.3f}m)"
            )
        elif log.equivalent_diameter_m is not None:
            values.append(
                f"stage_{log.stage_index}(D={log.equivalent_diameter_m:.3f}m,L={log.stage_length_m:.3f}m)"
            )
    return "[" + ", ".join(values) + "]"


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
    tune_reactor_pareto_v2_main()
