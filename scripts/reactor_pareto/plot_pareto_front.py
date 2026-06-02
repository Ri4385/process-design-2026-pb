"""SQLite storage に保存した Pareto front 探索結果を描画する。"""

from __future__ import annotations

from pathlib import Path

import japanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator, MaxNLocator
import optuna
from pydantic import BaseModel


STORAGE_PATH = Path("data") / "optuna" / "radial_pareto_optuna.db"
MEDIA_DIR = Path("scripts") / "reactor_pareto" / "media"
ALL_TRIALS_PATH = MEDIA_DIR / "radial_all_trials.png"
STAGE_PARETO_FRONT_PATH = MEDIA_DIR / "radial_stage_pareto_front.png"
GLOBAL_PARETO_FRONT_PATH = MEDIA_DIR / "radial_global_pareto_front.png"
STUDY_NAMES: tuple[tuple[str, str], ...] = (
    ("radial_2stage_selectivity_conversion", "2段"),
    ("radial_3stage_selectivity_conversion", "3段"),
)


class ParetoPoint(BaseModel):
    """描画に使う完了 trial の目的値。"""

    eb_conversion: float
    styrene_selectivity: float
    label: str


def plot_pareto_front_main() -> None:
    """全 trial と Pareto front の図を作成する。"""
    storage_url = f"sqlite:///{STORAGE_PATH.as_posix()}"
    studies = tuple(
        (
            label,
            optuna.load_study(study_name=study_name, storage=storage_url),
        )
        for study_name, label in STUDY_NAMES
    )
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    plot_all_trials(studies)
    plot_stage_pareto_trials(studies)
    plot_global_pareto_trials(studies)


def plot_all_trials(studies: tuple[tuple[str, optuna.Study], ...]) -> None:
    """全完了 trial の散布図を保存する。"""
    fig, ax = plt.subplots(figsize=(8, 6))
    for label, study in studies:
        points = tuple(point_from_trial(trial=trial, label=label) for trial in completed_trials(study))
        ax.scatter(
            [point.eb_conversion * 100.0 for point in points],
            [point.styrene_selectivity * 100.0 for point in points],
            alpha=0.65,
            label=label,
        )
    configure_axes(ax=ax)
    fig.tight_layout()
    fig.savefig(ALL_TRIALS_PATH, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_stage_pareto_trials(studies: tuple[tuple[str, optuna.Study], ...]) -> None:
    """段数ごとの Pareto front を保存する。"""
    fig, ax = plt.subplots(figsize=(8, 6))
    for label, study in studies:
        points = tuple(point_from_trial(trial=trial, label=label) for trial in completed_trials(study))
        pareto_points = global_pareto_front(points)
        ordered_points = tuple(sorted(pareto_points, key=lambda point: point.eb_conversion))
        ax.plot(
            [point.eb_conversion * 100.0 for point in ordered_points],
            [point.styrene_selectivity * 100.0 for point in ordered_points],
            marker="o",
            label=label,
        )
    configure_axes(ax=ax)
    fig.tight_layout()
    fig.savefig(STAGE_PARETO_FRONT_PATH, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_global_pareto_trials(studies: tuple[tuple[str, optuna.Study], ...]) -> None:
    """2段と3段を合わせた global Pareto front を保存する。"""
    fig, ax = plt.subplots(figsize=(8, 6))
    all_points = tuple(
        point_from_trial(trial=trial, label=label)
        for label, study in studies
        for trial in completed_trials(study)
    )
    pareto_points = global_pareto_front(all_points)
    ordered_points = tuple(sorted(pareto_points, key=lambda point: point.eb_conversion))
    ax.plot(
        [point.eb_conversion * 100.0 for point in ordered_points],
        [point.styrene_selectivity * 100.0 for point in ordered_points],
        color="0.6",
        linewidth=1.0,
        zorder=1,
    )
    for label, _ in studies:
        points = tuple(point for point in ordered_points if point.label == label)
        ax.scatter(
            [point.eb_conversion * 100.0 for point in points],
            [point.styrene_selectivity * 100.0 for point in points],
            marker="o",
            label=label,
            zorder=2,
        )
    configure_axes(ax=ax)
    fig.tight_layout()
    fig.savefig(GLOBAL_PARETO_FRONT_PATH, dpi=200, bbox_inches="tight")
    plt.close(fig)


def completed_trials(study: optuna.Study) -> tuple[optuna.trial.FrozenTrial, ...]:
    """完了 trial だけを返す。"""
    return tuple(
        trial
        for trial in study.trials
        if trial.state is optuna.trial.TrialState.COMPLETE
    )


def global_pareto_front(points: tuple[ParetoPoint, ...]) -> tuple[ParetoPoint, ...]:
    """2段と3段を合わせた非支配点を返す。"""
    return tuple(
        point
        for point in points
        if not any(dominates(other=other, point=point) for other in points)
    )


def dominates(other: ParetoPoint, point: ParetoPoint) -> bool:
    """other が point を支配する場合は True を返す。"""
    return (
        other.eb_conversion >= point.eb_conversion
        and other.styrene_selectivity >= point.styrene_selectivity
        and (
            other.eb_conversion > point.eb_conversion
            or other.styrene_selectivity > point.styrene_selectivity
        )
    )


def point_from_trial(trial: optuna.trial.FrozenTrial, label: str) -> ParetoPoint:
    """trial の目的値を描画用モデルへ変換する。"""
    if trial.values is None or len(trial.values) != 2:
        raise ValueError(f"trial {trial.number} does not have two objective values")
    return ParetoPoint(
        styrene_selectivity=trial.values[0],
        eb_conversion=trial.values[1],
        label=label,
    )


def configure_axes(ax: plt.Axes) -> None:
    """散布図の共通表示を設定する。"""
    ax.set_xlabel("EB 単通反応率 [%]")
    ax.set_ylabel("SM 選択率 [%]")
    ax.grid(False)
    ax.tick_params(
        axis="both",
        which="major",
        direction="in",
        top=True,
        right=True,
        bottom=True,
        left=True,
        length=6,
        width=1.0,
    )
    ax.tick_params(
        axis="both",
        which="minor",
        direction="in",
        top=True,
        right=True,
        bottom=True,
        left=True,
        length=3,
        width=0.8,
    )
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.legend(frameon=False)


if __name__ == "__main__":
    plot_pareto_front_main()
