"""指定した EB 単通反応率以上で SM 選択率が最大の Pareto v2 条件を表示する。"""

from __future__ import annotations

from pathlib import Path

import optuna
from pydantic import BaseModel


STORAGE_PATH = Path("data") / "optuna" / "reactor_pareto_v2_optuna.db"
MIN_EB_CONVERSION = 0.55
STUDY_NAMES: tuple[tuple[str, str, str], ...] = (
    ("radial_2stage_selectivity_conversion_v2", "radial", "radial 2段"),
    ("radial_3stage_selectivity_conversion_v2", "radial", "radial 3段"),
    ("axial_2stage_selectivity_conversion_v2", "axial", "axial 2段"),
    ("axial_3stage_selectivity_conversion_v2", "axial", "axial 3段"),
)


class SelectedCondition(BaseModel):
    """指定した単通反応率以上で選択率が最大の trial。"""

    study_name: str
    reactor_type: str
    label: str
    trial_number: int
    eb_conversion: float
    styrene_selectivity: float
    outlet_pressure_kpa: float | None
    total_catalyst_volume_m3: float | None
    params: dict[str, float]
    dimensions: dict[str, float]


def select_best_condition_main() -> None:
    """study ごと、反応器種別ごと、および全体の最良条件を表示する。"""
    storage_url = f"sqlite:///{STORAGE_PATH.as_posix()}"
    selected_conditions = tuple(
        condition
        for study_name, reactor_type, label in STUDY_NAMES
        if (
            condition := select_best_condition(
                study=optuna.load_study(study_name=study_name, storage=storage_url),
                reactor_type=reactor_type,
                label=label,
            )
        )
        is not None
    )
    print(f"minimum EB single-pass conversion: {MIN_EB_CONVERSION * 100.0:.2f} %")
    print()
    for condition in selected_conditions:
        print_condition(header=f"[{condition.label} best]", condition=condition)
    for reactor_type in ("radial", "axial"):
        matching = tuple(condition for condition in selected_conditions if condition.reactor_type == reactor_type)
        if matching:
            print_condition(header=f"[{reactor_type} overall best]", condition=max(matching, key=selection_key))
    if selected_conditions:
        print_condition(header="[overall best]", condition=max(selected_conditions, key=selection_key))
    else:
        print("条件を満たす完了 trial はありません。")


def select_best_condition(
    study: optuna.Study,
    reactor_type: str,
    label: str,
) -> SelectedCondition | None:
    """指定した study から条件を満たす最良 trial を返す。"""
    candidates = tuple(
        condition_from_trial(study_name=study.study_name, reactor_type=reactor_type, label=label, trial=trial)
        for trial in study.trials
        if trial.state is optuna.trial.TrialState.COMPLETE
        and trial.values is not None
        and len(trial.values) == 2
        and trial.values[1] >= MIN_EB_CONVERSION
    )
    if not candidates:
        return None
    return max(candidates, key=selection_key)


def condition_from_trial(
    study_name: str,
    reactor_type: str,
    label: str,
    trial: optuna.trial.FrozenTrial,
) -> SelectedCondition:
    """完了 trial を表示用モデルへ変換する。"""
    if trial.values is None or len(trial.values) != 2:
        raise ValueError(f"trial {trial.number} does not have two objective values")
    return SelectedCondition(
        study_name=study_name,
        reactor_type=reactor_type,
        label=label,
        trial_number=trial.number,
        styrene_selectivity=trial.values[0],
        eb_conversion=trial.values[1],
        outlet_pressure_kpa=optional_float_attr(trial=trial, key="outlet_pressure_kpa"),
        total_catalyst_volume_m3=optional_float_attr(trial=trial, key="total_catalyst_volume_m3"),
        params={key: float(value) for key, value in trial.params.items()},
        dimensions={
            key: float(value)
            for key, value in trial.user_attrs.items()
            if key.startswith("stage_") and isinstance(value, (float, int))
        },
    )


def optional_float_attr(trial: optuna.trial.FrozenTrial, key: str) -> float | None:
    """trial の user attr を float として返す。"""
    value = trial.user_attrs.get(key)
    if value is None:
        return None
    return float(value)


def selection_key(condition: SelectedCondition) -> tuple[float, float, int]:
    """選択率、単通反応率、trial 番号の順で比較する。"""
    return condition.styrene_selectivity, condition.eb_conversion, -condition.trial_number


def print_condition(header: str, condition: SelectedCondition) -> None:
    """選択した条件を標準出力へ表示する。"""
    print(header)
    print(f"study                    : {condition.study_name}")
    print(f"trial                    : {condition.trial_number}")
    print(f"EB single-pass conversion: {condition.eb_conversion * 100.0:.4f} %")
    print(f"SM selectivity           : {condition.styrene_selectivity * 100.0:.4f} %")
    print(f"outlet pressure          : {format_optional(condition.outlet_pressure_kpa, '.3f')} kPa abs")
    print(f"total catalyst volume    : {format_optional(condition.total_catalyst_volume_m3, '.3f')} m3")
    print("params:")
    for key, value in condition.params.items():
        print(f"  {key}: {value:.6f}")
    print("dimensions:")
    for key, value in condition.dimensions.items():
        print(f"  {key}: {value:.6f}")
    print()


def format_optional(value: float | None, format_spec: str) -> str:
    """None を含む値を表示用文字列へ変換する。"""
    if value is None:
        return "N/A"
    return format(value, format_spec)


if __name__ == "__main__":
    select_best_condition_main()
