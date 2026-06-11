"""radial 2段固定条件の Optuna 結果を図表化する。"""

from __future__ import annotations

import csv
from pathlib import Path

import japanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator, MaxNLocator
import optuna
from optuna.importance import get_param_importances
from pydantic import BaseModel, ConfigDict


STORAGE_PATH = Path("data") / "optuna" / "whole_plant_radial2_fixed_final.db"
STUDY_NAME = "radial_2stage_fixed_final_profit"
MEDIA_DIR = Path("scripts") / "whole_plant_radial2_fixed_final" / "media"
RESULTS_DIR = Path("scripts") / "whole_plant_radial2_fixed_final" / "results"
TOP_TRIAL_COUNT = 20

FIXED_STEAM_TO_EB_RATIO = 5.0
FIXED_DECANTER_1_TEMPERATURE_C = 55.0
FIXED_SM_COLUMN_REFLUX_RATIO = 6.312


class TrialSummary(BaseModel):
    """表出力に使う radial 2段 trial 要約。"""

    model_config = ConfigDict(frozen=True)

    trial_number: int
    objective_yen_per_year: float
    params: dict[str, float]
    attrs: dict[str, object]


def main() -> None:
    """radial 2段 study から図と表を生成する。"""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    study = load_study()
    plot_best_objective_history(
        study=study,
        output_path=MEDIA_DIR / "best_objective_history.png",
    )
    plot_objective_trials(
        study=study,
        output_path=MEDIA_DIR / "objective_trials.png",
    )
    plot_parameter_importance(
        study=study,
        output_path=MEDIA_DIR / "parameter_importance.png",
    )
    plot_slice(
        study=study,
        output_path=MEDIA_DIR / "objective_slice_plot.png",
    )
    write_top_trials(study=study)


def load_study() -> optuna.Study:
    """Optuna storage から radial 2段 study を読み込む。"""
    if not STORAGE_PATH.exists():
        raise FileNotFoundError(f"Optuna storage is missing: {STORAGE_PATH}")
    return optuna.load_study(
        study_name=STUDY_NAME,
        storage=f"sqlite:///{STORAGE_PATH.as_posix()}",
    )


def complete_trials(study: optuna.Study) -> tuple[optuna.trial.FrozenTrial, ...]:
    """完了 trial だけを返す。"""
    return tuple(
        trial
        for trial in study.trials
        if trial.state is optuna.trial.TrialState.COMPLETE
    )


def plot_best_objective_history(study: optuna.Study, output_path: Path) -> None:
    """best objective 推移を保存する。"""
    trial_numbers: list[int] = []
    best_values: list[float] = []
    best_value: float | None = None
    for trial in sorted(complete_trials(study), key=lambda item: item.number):
        if trial.value is None:
            continue
        best_value = trial.value if best_value is None else max(best_value, trial.value)
        trial_numbers.append(trial.number)
        best_values.append(best_value)

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(trial_numbers, best_values, marker="o")
    configure_axes(ax=ax, xlabel="trial number", ylabel="best annual profit [yen/year]")
    save_figure(fig=fig, output_path=output_path)


def plot_objective_trials(study: optuna.Study, output_path: Path) -> None:
    """各 trial の objective 散布図を保存する。"""
    values = [
        (trial.number, trial.value)
        for trial in complete_trials(study)
        if trial.value is not None
    ]
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(
        [trial_number for trial_number, _ in values],
        [value for _, value in values],
        alpha=0.75,
    )
    configure_axes(ax=ax, xlabel="trial number", ylabel="annual profit [yen/year]")
    save_figure(fig=fig, output_path=output_path)


def plot_parameter_importance(study: optuna.Study, output_path: Path) -> None:
    """parameter importance を保存する。"""
    fig, ax = plt.subplots(figsize=(8, 5))
    if len(complete_trials(study)) < 2:
        ax.text(0.5, 0.5, "not enough completed trials", ha="center", va="center")
        ax.axis("off")
        save_figure(fig=fig, output_path=output_path)
        return

    importances = get_param_importances(study)
    items = tuple(reversed(tuple(importances.items())))
    ax.barh([name for name, _ in items], [value for _, value in items])
    ax.set_xlabel("importance")
    ax.grid(False)
    save_figure(fig=fig, output_path=output_path)


def plot_slice(study: optuna.Study, output_path: Path) -> None:
    """Optuna の slice plot を保存する。"""
    if len(complete_trials(study)) < 2:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "not enough completed trials", ha="center", va="center")
        ax.axis("off")
        save_figure(fig=fig, output_path=output_path)
        return

    from optuna.visualization.matplotlib import plot_slice as optuna_plot_slice

    optuna_plot_slice(study)
    fig = plt.gcf()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def write_top_trials(study: optuna.Study) -> None:
    """上位 trial の CSV と Markdown を保存する。"""
    summaries = sorted(
        summaries_from_study(study),
        key=lambda item: item.objective_yen_per_year,
        reverse=True,
    )[:TOP_TRIAL_COUNT]
    write_top_trials_csv(summaries=summaries, output_path=RESULTS_DIR / "top_trials.csv")
    write_top_trials_markdown(
        summaries=summaries,
        output_path=RESULTS_DIR / "top_trials.md",
    )


def summaries_from_study(study: optuna.Study) -> list[TrialSummary]:
    """完了 trial を summary へ変換する。"""
    summaries: list[TrialSummary] = []
    for trial in complete_trials(study):
        if trial.value is None:
            continue
        summaries.append(
            TrialSummary(
                trial_number=trial.number,
                objective_yen_per_year=trial.value,
                params={key: float(value) for key, value in trial.params.items()},
                attrs=dict(trial.user_attrs),
            )
        )
    return summaries


def write_top_trials_csv(summaries: list[TrialSummary], output_path: Path) -> None:
    """上位 trial の CSV を保存する。"""
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=top_trial_columns())
        writer.writeheader()
        for rank, summary in enumerate(summaries, start=1):
            writer.writerow(top_trial_row(rank=rank, summary=summary))


def write_top_trials_markdown(summaries: list[TrialSummary], output_path: Path) -> None:
    """上位 trial の Markdown 表を保存する。"""
    columns = top_trial_columns()
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for rank, summary in enumerate(summaries, start=1):
        row = top_trial_row(rank=rank, summary=summary)
        lines.append("| " + " | ".join(str(row[column]) for column in columns) + " |")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def top_trial_columns() -> list[str]:
    """上位 trial 表の列名を返す。"""
    return [
        "rank",
        "trial_number",
        "annual_profit_yen_per_year",
        "stage_1_temperature_c",
        "stage_2_temperature_c",
        "inlet_pressure_kpa_abs",
        "steam_to_eb_ratio",
        "stage_1_bed_thickness_m",
        "stage_2_bed_thickness_m",
        "decanter_1_temperature_c",
        "sm_column_reflux_ratio",
        "eb_conversion",
        "styrene_selectivity",
        "sm_product_kmol_h",
        "fresh_eb_kmol_h",
        "fresh_h2o_kmol_h",
        "eb_recycle_kmol_h",
        "h2o_recycle_kmol_h",
        "utility_yen_per_year",
        "annualized_equipment_yen_per_year",
    ]


def top_trial_row(rank: int, summary: TrialSummary) -> dict[str, object]:
    """上位 trial 表の1行を作る。"""
    return {
        "rank": rank,
        "trial_number": summary.trial_number,
        "annual_profit_yen_per_year": format_float(summary.objective_yen_per_year),
        "stage_1_temperature_c": format_param(summary, "stage_1_temperature_c"),
        "stage_2_temperature_c": format_param(summary, "stage_2_temperature_c"),
        "inlet_pressure_kpa_abs": format_param(summary, "inlet_pressure_kpa_abs"),
        "steam_to_eb_ratio": format_fixed_or_attr(
            summary, "steam_to_eb_ratio", FIXED_STEAM_TO_EB_RATIO
        ),
        "stage_1_bed_thickness_m": format_param(summary, "stage_1_bed_thickness_m"),
        "stage_2_bed_thickness_m": format_param(summary, "stage_2_bed_thickness_m"),
        "decanter_1_temperature_c": format_fixed_or_attr(
            summary, "decanter_1_temperature_c", FIXED_DECANTER_1_TEMPERATURE_C
        ),
        "sm_column_reflux_ratio": format_fixed_or_attr(
            summary, "sm_column_reflux_ratio", FIXED_SM_COLUMN_REFLUX_RATIO
        ),
        "eb_conversion": format_attr(summary, "eb_conversion"),
        "styrene_selectivity": format_attr(summary, "styrene_selectivity"),
        "sm_product_kmol_h": format_attr(summary, "sm_product_kmol_h"),
        "fresh_eb_kmol_h": format_attr(summary, "fresh_eb_kmol_h"),
        "fresh_h2o_kmol_h": format_attr(summary, "fresh_h2o_kmol_h"),
        "eb_recycle_kmol_h": format_attr(summary, "eb_recycle_kmol_h"),
        "h2o_recycle_kmol_h": format_attr(summary, "h2o_recycle_kmol_h"),
        "utility_yen_per_year": format_attr(summary, "utility_yen_per_year"),
        "annualized_equipment_yen_per_year": format_attr(
            summary, "annualized_equipment_yen_per_year"
        ),
    }


def format_param(summary: TrialSummary, key: str) -> str:
    """param の値を表用に整形する。"""
    value = summary.params.get(key)
    return "" if value is None else format_float(value)


def format_attr(summary: TrialSummary, key: str) -> str:
    """user_attr の値を表用に整形する。"""
    value = summary.attrs.get(key)
    if value is None:
        return ""
    if isinstance(value, float):
        return format_float(value)
    return str(value)


def format_fixed_or_attr(summary: TrialSummary, key: str, fixed_value: float) -> str:
    """user_attr があればそれを使い、なければ固定値を返す。"""
    value = summary.attrs.get(key)
    if isinstance(value, float):
        return format_float(value)
    return format_float(fixed_value)


def format_float(value: float) -> str:
    """表用の浮動小数点表現を返す。"""
    return f"{value:.6g}"


def configure_axes(ax: plt.Axes, xlabel: str, ylabel: str) -> None:
    """探索結果図の共通軸設定を行う。"""
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(False)
    ax.tick_params(
        axis="both",
        which="major",
        direction="in",
        top=True,
        right=True,
        length=6,
        width=1.0,
    )
    ax.tick_params(
        axis="both",
        which="minor",
        direction="in",
        top=True,
        right=True,
        length=3,
        width=0.8,
    )
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))


def save_figure(fig: plt.Figure, output_path: Path) -> None:
    """図を保存して閉じる。"""
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
