"""radial 2段固定条件の sampler 比較結果を図表化する。"""

from __future__ import annotations

import csv
from pathlib import Path

import japanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator, MaxNLocator
import optuna
from pydantic import BaseModel, ConfigDict


STORAGE_PATH = Path("data") / "optuna" / "whole_plant_radial2_fixed_sampler_comparison.db"
MEDIA_DIR = Path("scripts") / "whole_plant_radial2_fixed_sampler_comparison" / "media"
RESULTS_DIR = Path("scripts") / "whole_plant_radial2_fixed_sampler_comparison" / "results"
STUDY_NAMES: tuple[str, ...] = (
    "radial_2stage_fixed_tpe_sampler",
    "radial_2stage_fixed_gp_sampler",
)
TOP_TRIAL_COUNT = 20


class TrialSummary(BaseModel):
    """比較表に使う trial 要約。"""

    model_config = ConfigDict(frozen=True)

    study_name: str
    sampler_kind: str
    trial_number: int
    objective_yen_per_year: float
    params: dict[str, float]
    attrs: dict[str, object]


class StudySummary(BaseModel):
    """sampler study の概要表に使う要約。"""

    model_config = ConfigDict(frozen=True)

    study_name: str
    sampler_kind: str
    stored_trials: int
    complete_trials: int
    pruned_trials: int
    best_trial_number: int | None
    best_objective_yen_per_year: float | None


def main() -> None:
    """sampler 比較結果の図と表を生成する。"""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    studies = load_existing_studies()
    plot_best_objective_history(
        studies=studies,
        output_path=MEDIA_DIR / "best_objective_history.png",
    )
    plot_objective_trials(
        studies=studies,
        output_path=MEDIA_DIR / "objective_trials.png",
    )
    summaries = tuple(
        summary for study in studies for summary in trial_summaries_from_study(study)
    )
    write_top_trials_csv(
        summaries=top_trial_summaries(summaries),
        output_path=RESULTS_DIR / "top_trials.csv",
    )
    write_top_trials_markdown(
        summaries=top_trial_summaries(summaries),
        output_path=RESULTS_DIR / "top_trials.md",
    )
    write_study_summary_csv(
        summaries=tuple(study_summary_from_study(study) for study in studies),
        output_path=RESULTS_DIR / "summary.csv",
    )


def load_existing_studies() -> tuple[optuna.Study, ...]:
    """存在する study を読み込む。"""
    if not STORAGE_PATH.exists():
        raise FileNotFoundError(f"Optuna storage is missing: {STORAGE_PATH}")
    storage_url = f"sqlite:///{STORAGE_PATH.as_posix()}"
    studies: list[optuna.Study] = []
    for study_name in STUDY_NAMES:
        try:
            studies.append(optuna.load_study(study_name=study_name, storage=storage_url))
        except KeyError:
            continue
    return tuple(studies)


def complete_trials(study: optuna.Study) -> tuple[optuna.trial.FrozenTrial, ...]:
    """完了 trial だけを返す。"""
    return tuple(
        trial
        for trial in study.trials
        if trial.state is optuna.trial.TrialState.COMPLETE
    )


def pruned_trials(study: optuna.Study) -> tuple[optuna.trial.FrozenTrial, ...]:
    """prune 済み trial だけを返す。"""
    return tuple(
        trial
        for trial in study.trials
        if trial.state is optuna.trial.TrialState.PRUNED
    )


def plot_best_objective_history(
    studies: tuple[optuna.Study, ...],
    output_path: Path,
) -> None:
    """study ごとの best objective 推移を保存する。"""
    fig, ax = plt.subplots(figsize=(8, 6))
    plotted = False
    for study in studies:
        trial_numbers: list[int] = []
        best_values: list[float] = []
        best_value: float | None = None
        for trial in sorted(complete_trials(study), key=lambda item: item.number):
            if trial.value is None:
                continue
            best_value = trial.value if best_value is None else max(best_value, trial.value)
            trial_numbers.append(trial.number)
            best_values.append(best_value)
        if trial_numbers:
            ax.plot(trial_numbers, best_values, marker="o", label=study.study_name)
            plotted = True
    configure_axes(ax=ax, xlabel="trial number", ylabel="best annual profit [yen/year]")
    if plotted:
        ax.legend(frameon=False, fontsize=9)
    save_figure(fig=fig, output_path=output_path)


def plot_objective_trials(
    studies: tuple[optuna.Study, ...],
    output_path: Path,
) -> None:
    """study ごとの objective 散布図を保存する。"""
    fig, ax = plt.subplots(figsize=(8, 6))
    plotted = False
    for study in studies:
        values = [
            (trial.number, trial.value)
            for trial in complete_trials(study)
            if trial.value is not None
        ]
        if not values:
            continue
        ax.scatter(
            [trial_number for trial_number, _ in values],
            [value for _, value in values],
            alpha=0.75,
            label=study.study_name,
        )
        plotted = True
    configure_axes(ax=ax, xlabel="trial number", ylabel="annual profit [yen/year]")
    if plotted:
        ax.legend(frameon=False, fontsize=9)
    save_figure(fig=fig, output_path=output_path)


def trial_summaries_from_study(study: optuna.Study) -> tuple[TrialSummary, ...]:
    """study の完了 trial を表用 summary へ変換する。"""
    summaries: list[TrialSummary] = []
    for trial in complete_trials(study):
        if trial.value is None:
            continue
        sampler_kind = str(trial.user_attrs.get("sampler_kind", ""))
        summaries.append(
            TrialSummary(
                study_name=study.study_name,
                sampler_kind=sampler_kind,
                trial_number=trial.number,
                objective_yen_per_year=trial.value,
                params={key: float(value) for key, value in trial.params.items()},
                attrs=dict(trial.user_attrs),
            )
        )
    return tuple(summaries)


def top_trial_summaries(
    summaries: tuple[TrialSummary, ...],
) -> list[TrialSummary]:
    """全 study 横断の上位 trial を返す。"""
    return sorted(
        summaries,
        key=lambda item: item.objective_yen_per_year,
        reverse=True,
    )[:TOP_TRIAL_COUNT]


def study_summary_from_study(study: optuna.Study) -> StudySummary:
    """study の概要 summary を作る。"""
    complete = complete_trials(study)
    best_trial = best_trial_or_none(complete)
    sampler_kind = ""
    for trial in study.trials:
        value = trial.user_attrs.get("sampler_kind")
        if isinstance(value, str):
            sampler_kind = value
            break
    return StudySummary(
        study_name=study.study_name,
        sampler_kind=sampler_kind,
        stored_trials=len(study.trials),
        complete_trials=len(complete),
        pruned_trials=len(pruned_trials(study)),
        best_trial_number=None if best_trial is None else best_trial.number,
        best_objective_yen_per_year=None if best_trial is None else best_trial.value,
    )


def best_trial_or_none(
    trials: tuple[optuna.trial.FrozenTrial, ...],
) -> optuna.trial.FrozenTrial | None:
    """完了 trial の中から最大 objective の trial を返す。"""
    valued_trials = tuple(trial for trial in trials if trial.value is not None)
    if not valued_trials:
        return None
    return max(valued_trials, key=lambda item: item.value or float("-inf"))


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


def write_study_summary_csv(
    summaries: tuple[StudySummary, ...],
    output_path: Path,
) -> None:
    """study 別の概要 CSV を保存する。"""
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "study_name",
                "sampler_kind",
                "stored_trials",
                "complete_trials",
                "pruned_trials",
                "best_trial_number",
                "best_objective_yen_per_year",
            ],
        )
        writer.writeheader()
        for summary in summaries:
            writer.writerow(
                {
                    "study_name": summary.study_name,
                    "sampler_kind": summary.sampler_kind,
                    "stored_trials": summary.stored_trials,
                    "complete_trials": summary.complete_trials,
                    "pruned_trials": summary.pruned_trials,
                    "best_trial_number": summary.best_trial_number or "",
                    "best_objective_yen_per_year": format_optional_float(
                        summary.best_objective_yen_per_year
                    ),
                }
            )


def top_trial_columns() -> list[str]:
    """上位 trial 表の列名を返す。"""
    return [
        "rank",
        "study_name",
        "sampler_kind",
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
        "study_name": summary.study_name,
        "sampler_kind": summary.sampler_kind,
        "trial_number": summary.trial_number,
        "annual_profit_yen_per_year": format_float(summary.objective_yen_per_year),
        "stage_1_temperature_c": format_param(summary, "stage_1_temperature_c"),
        "stage_2_temperature_c": format_param(summary, "stage_2_temperature_c"),
        "inlet_pressure_kpa_abs": format_param(summary, "inlet_pressure_kpa_abs"),
        "steam_to_eb_ratio": format_attr(summary, "steam_to_eb_ratio"),
        "stage_1_bed_thickness_m": format_param(summary, "stage_1_bed_thickness_m"),
        "stage_2_bed_thickness_m": format_param(summary, "stage_2_bed_thickness_m"),
        "decanter_1_temperature_c": format_attr(summary, "decanter_1_temperature_c"),
        "sm_column_reflux_ratio": format_attr(summary, "sm_column_reflux_ratio"),
        "eb_conversion": format_attr(summary, "eb_conversion"),
        "styrene_selectivity": format_attr(summary, "styrene_selectivity"),
        "sm_product_kmol_h": format_attr(summary, "sm_product_kmol_h"),
        "fresh_eb_kmol_h": format_attr(summary, "fresh_eb_kmol_h"),
        "fresh_h2o_kmol_h": format_attr(summary, "fresh_h2o_kmol_h"),
        "eb_recycle_kmol_h": format_attr(summary, "eb_recycle_kmol_h"),
        "h2o_recycle_kmol_h": format_attr(summary, "h2o_recycle_kmol_h"),
        "utility_yen_per_year": format_attr(summary, "utility_yen_per_year"),
        "annualized_equipment_yen_per_year": format_attr(
            summary,
            "annualized_equipment_yen_per_year",
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


def format_optional_float(value: float | None) -> str:
    """None を含む float を表用に整形する。"""
    if value is None:
        return ""
    return format_float(value)


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
