"""全体最適化 v1 の Optuna storage から図と表を生成する。"""

from __future__ import annotations

import csv
from pathlib import Path

import japanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator, MaxNLocator
import optuna
from optuna.importance import get_param_importances
from pydantic import BaseModel, ConfigDict


STORAGE_PATH = Path("data") / "optuna" / "whole_plant_optuna_v1.db"
MEDIA_DIR = Path("scripts") / "whole_plant_optuna_v1" / "media"
RESULTS_DIR = Path("scripts") / "whole_plant_optuna_v1" / "results"
STUDY_NAMES: tuple[str, ...] = (
    "radial_2stage_whole_plant_profit_v1",
    "radial_3stage_whole_plant_profit_v1",
    "axial_2stage_whole_plant_profit_v1",
    "axial_3stage_whole_plant_profit_v1",
)
TOP_TRIAL_COUNT = 10


class TrialSummary(BaseModel):
    """上位 trial 表と描画に使う trial 要約。"""

    model_config = ConfigDict(frozen=True)

    study_name: str
    trial_number: int
    objective_yen_per_year: float
    stage_count: int | None
    reactor_type: str
    params: dict[str, float]
    attrs: dict[str, object]


def plot_whole_plant_optuna_v1_main() -> None:
    """全体最適化 v1 の保存済み study から図と表を生成する。"""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    studies = load_existing_studies()
    plot_best_objective_history(studies=studies, output_path=MEDIA_DIR / "best_objective_history.png")
    plot_objective_trials(studies=studies, output_path=MEDIA_DIR / "objective_trials.png")
    plot_parameter_importances(studies=studies, output_path=MEDIA_DIR / "parameter_importance.png")
    plot_slice_figures(studies=studies)
    write_top_trials(studies=studies)


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
    return tuple(trial for trial in study.trials if trial.state is optuna.trial.TrialState.COMPLETE)


def plot_best_objective_history(studies: tuple[optuna.Study, ...], output_path: Path) -> None:
    """各 study の best objective 推移を保存する。"""
    fig, ax = plt.subplots(figsize=(8, 6))
    plotted = False
    for study in studies:
        trials = complete_trials(study)
        if not trials:
            continue
        trial_numbers: list[int] = []
        best_values: list[float] = []
        best_value: float | None = None
        for trial in sorted(trials, key=lambda item: item.number):
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


def plot_objective_trials(studies: tuple[optuna.Study, ...], output_path: Path) -> None:
    """各 trial の objective 散布図を保存する。"""
    fig, ax = plt.subplots(figsize=(8, 6))
    plotted = False
    for study in studies:
        trials = complete_trials(study)
        values = [(trial.number, trial.value) for trial in trials if trial.value is not None]
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


def plot_parameter_importances(studies: tuple[optuna.Study, ...], output_path: Path) -> None:
    """study ごとの parameter importance を保存する。"""
    valid_items: list[tuple[str, dict[str, float]]] = []
    for study in studies:
        if len(complete_trials(study)) < 2:
            continue
        try:
            importances = get_param_importances(study)
        except Exception:
            continue
        if importances:
            valid_items.append((study.study_name, importances))

    if not valid_items:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "not enough completed trials", ha="center", va="center")
        ax.axis("off")
        save_figure(fig=fig, output_path=output_path)
        return

    fig, axes = plt.subplots(len(valid_items), 1, figsize=(9, 3.2 * len(valid_items)))
    axes_list = [axes] if len(valid_items) == 1 else list(axes)
    for ax, (study_name, importances) in zip(axes_list, valid_items, strict=True):
        items = tuple(reversed(tuple(importances.items())))
        ax.barh([name for name, _ in items], [value for _, value in items])
        ax.set_title(study_name)
        ax.set_xlabel("importance")
        ax.grid(False)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_slice_figures(studies: tuple[optuna.Study, ...]) -> None:
    """Optuna visualization の slice plot を study ごとに保存する。"""
    from optuna.visualization.matplotlib import plot_slice

    for study in studies:
        if len(complete_trials(study)) < 2:
            continue
        try:
            plot_slice(study)
        except Exception:
            continue
        fig = plt.gcf()
        output_path = MEDIA_DIR / f"objective_slice_plot_{study.study_name}.png"
        fig.savefig(output_path, dpi=200, bbox_inches="tight")
        plt.close(fig)


def write_top_trials(studies: tuple[optuna.Study, ...]) -> None:
    """上位 trial の CSV と Markdown を保存する。"""
    summaries = sorted(
        (
            summary
            for study in studies
            for summary in summaries_from_study(study)
        ),
        key=lambda item: item.objective_yen_per_year,
        reverse=True,
    )[:TOP_TRIAL_COUNT]
    write_top_trials_csv(summaries=summaries, output_path=RESULTS_DIR / "top_trials.csv")
    write_top_trials_markdown(summaries=summaries, output_path=RESULTS_DIR / "top_trials.md")


def summaries_from_study(study: optuna.Study) -> tuple[TrialSummary, ...]:
    """study の完了 trial を表用 summary へ変換する。"""
    summaries: list[TrialSummary] = []
    for trial in complete_trials(study):
        if trial.value is None:
            continue
        summaries.append(
            TrialSummary(
                study_name=study.study_name,
                trial_number=trial.number,
                objective_yen_per_year=trial.value,
                stage_count=int_attr(trial.user_attrs.get("stage_count")),
                reactor_type=str(trial.user_attrs.get("reactor_type", "")),
                params={key: float(value) for key, value in trial.params.items()},
                attrs=dict(trial.user_attrs),
            )
        )
    return tuple(summaries)


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
        "study_name",
        "trial_number",
        "annual_profit_yen_per_year",
        "reactor_type",
        "stage_count",
        "stage_temperatures_c",
        "inlet_pressure_kpa_abs",
        "steam_to_eb_ratio",
        "bed_thicknesses_m",
        "ld_ratios",
        "eb_conversion",
        "styrene_selectivity",
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
        "trial_number": summary.trial_number,
        "annual_profit_yen_per_year": format_float(summary.objective_yen_per_year),
        "reactor_type": summary.reactor_type,
        "stage_count": summary.stage_count or "",
        "stage_temperatures_c": join_stage_values(summary.attrs, "temperature_c"),
        "inlet_pressure_kpa_abs": format_attr(summary.attrs, "inlet_pressure_kpa_abs"),
        "steam_to_eb_ratio": format_attr(summary.attrs, "steam_to_eb_ratio"),
        "bed_thicknesses_m": join_stage_values(summary.attrs, "bed_thickness_m"),
        "ld_ratios": join_stage_values(summary.attrs, "ld_ratio"),
        "eb_conversion": format_attr(summary.attrs, "eb_conversion"),
        "styrene_selectivity": format_attr(summary.attrs, "styrene_selectivity"),
        "fresh_eb_kmol_h": format_attr(summary.attrs, "fresh_eb_kmol_h"),
        "fresh_h2o_kmol_h": format_attr(summary.attrs, "fresh_h2o_kmol_h"),
        "eb_recycle_kmol_h": format_attr(summary.attrs, "eb_recycle_kmol_h"),
        "h2o_recycle_kmol_h": format_attr(summary.attrs, "h2o_recycle_kmol_h"),
        "utility_yen_per_year": format_attr(summary.attrs, "utility_yen_per_year"),
        "annualized_equipment_yen_per_year": format_attr(summary.attrs, "annualized_equipment_yen_per_year"),
    }


def join_stage_values(attrs: dict[str, object], suffix: str) -> str:
    """stage_N_suffix の値を順に結合する。"""
    values: list[str] = []
    for index in range(1, 5):
        key = f"stage_{index}_{suffix}"
        if key in attrs:
            values.append(format_value(attrs[key]))
    return ";".join(values)


def int_attr(value: object) -> int | None:
    """object を int へ変換する。"""
    if value is None:
        return None
    return int(value)


def format_attr(attrs: dict[str, object], key: str) -> str:
    """attrs の数値を表用に整形する。"""
    return format_value(attrs.get(key))


def format_value(value: object) -> str:
    """表用の値表現を返す。"""
    if value is None:
        return ""
    if isinstance(value, float):
        return format_float(value)
    return str(value)


def format_float(value: float) -> str:
    """表用の浮動小数点表現を返す。"""
    return f"{value:.6g}"


def configure_axes(ax: plt.Axes, xlabel: str, ylabel: str) -> None:
    """探索結果図の共通軸設定を行う。"""
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(False)
    ax.tick_params(axis="both", which="major", direction="in", top=True, right=True, length=6, width=1.0)
    ax.tick_params(axis="both", which="minor", direction="in", top=True, right=True, length=3, width=0.8)
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
    plot_whole_plant_optuna_v1_main()
