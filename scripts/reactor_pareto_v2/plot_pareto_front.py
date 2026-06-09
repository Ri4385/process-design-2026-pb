"""Pareto v2 の全 trial と Pareto front を描画する。"""

from __future__ import annotations

from pathlib import Path

import japanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator, MaxNLocator
import optuna
from pydantic import BaseModel


STORAGE_PATH = Path("data") / "optuna" / "reactor_pareto_v2_optuna.db"
MEDIA_DIR = Path("scripts") / "reactor_pareto_v2" / "media"
STUDY_NAMES: tuple[tuple[str, str, str], ...] = (
    ("radial_2stage_selectivity_conversion_v2", "radial", "radial 2段"),
    ("radial_3stage_selectivity_conversion_v2", "radial", "radial 3段"),
    ("axial_2stage_selectivity_conversion_v2", "axial", "axial 2段"),
    ("axial_3stage_selectivity_conversion_v2", "axial", "axial 3段"),
)
GLOBAL_FRONT_X_MIN_PERCENT = 40.0
GLOBAL_FRONT_Y_MIN_PERCENT = 91.0
GLOBAL_ALL_TRIALS_Y_MIN_PERCENT = 72.0
AXIS_LABEL_FONT_SIZE = 20
TICK_LABEL_FONT_SIZE = 20
LEGEND_FONT_SIZE = 20


class ParetoPoint(BaseModel):
    """描画に使う完了 trial の目的値。"""

    eb_conversion: float
    styrene_selectivity: float
    reactor_type: str
    label: str


def plot_pareto_front_main() -> None:
    """指定された8種類の図を生成する。"""
    storage_url = f"sqlite:///{STORAGE_PATH.as_posix()}"
    studies = tuple(
        (reactor_type, label, optuna.load_study(study_name=study_name, storage=storage_url))
        for study_name, reactor_type, label in STUDY_NAMES
    )
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    radial_studies = select_studies(studies=studies, reactor_type="radial")
    axial_studies = select_studies(studies=studies, reactor_type="axial")
    plot_stage_fronts(studies=radial_studies, output_path=MEDIA_DIR / "radial_stage_pareto_front.png")
    plot_reactor_global_fronts(studies=studies, output_path=MEDIA_DIR / "radial_axial_global_pareto_front.png")
    plot_reactor_global_all_trials(studies=studies, output_path=MEDIA_DIR / "radial_axial_global_all_trials.png")
    plot_stage_fronts(studies=axial_studies, output_path=MEDIA_DIR / "axial_stage_pareto_front.png")
    plot_stage_fronts(studies=studies, output_path=MEDIA_DIR / "all_stage_pareto_front.png")
    plot_all_trials(studies=radial_studies, output_path=MEDIA_DIR / "radial_all_trials.png")
    plot_all_trials(studies=axial_studies, output_path=MEDIA_DIR / "axial_all_trials.png")
    plot_all_trials(studies=studies, output_path=MEDIA_DIR / "all_trials.png")


def select_studies(
    studies: tuple[tuple[str, str, optuna.Study], ...],
    reactor_type: str,
) -> tuple[tuple[str, str, optuna.Study], ...]:
    """指定した反応器種別の study だけを返す。"""
    return tuple(study for study in studies if study[0] == reactor_type)


def plot_all_trials(
    studies: tuple[tuple[str, str, optuna.Study], ...],
    output_path: Path,
) -> None:
    """全完了 trial の散布図を保存する。"""
    fig, ax = plt.subplots(figsize=(8, 6))
    for reactor_type, label, study in studies:
        points = points_from_study(study=study, reactor_type=reactor_type, label=label)
        ax.scatter(
            [point.eb_conversion * 100.0 for point in points],
            [point.styrene_selectivity * 100.0 for point in points],
            alpha=0.65,
            label=label,
        )
    configure_axes(ax=ax)
    save_figure(fig=fig, output_path=output_path)


def plot_stage_fronts(
    studies: tuple[tuple[str, str, optuna.Study], ...],
    output_path: Path,
) -> None:
    """study ごとの Pareto front を保存する。"""
    fig, ax = plt.subplots(figsize=(8, 6))
    for reactor_type, label, study in studies:
        points = global_pareto_front(points_from_study(study=study, reactor_type=reactor_type, label=label))
        ordered_points = tuple(sorted(points, key=lambda point: point.eb_conversion))
        ax.plot(
            [point.eb_conversion * 100.0 for point in ordered_points],
            [point.styrene_selectivity * 100.0 for point in ordered_points],
            marker="o",
            label=label,
        )
    configure_axes(ax=ax)
    save_figure(fig=fig, output_path=output_path)


def plot_reactor_global_fronts(
    studies: tuple[tuple[str, str, optuna.Study], ...],
    output_path: Path,
) -> None:
    """radial と axial の global Pareto front を保存する。"""
    fig, ax = plt.subplots(figsize=(8, 6))
    for reactor_type in ("radial", "axial"):
        reactor_studies = select_studies(studies=studies, reactor_type=reactor_type)
        points = tuple(
            point
            for _, label, study in reactor_studies
            for point in points_from_study(study=study, reactor_type=reactor_type, label=label)
        )
        ordered_points = tuple(sorted(global_pareto_front(points), key=lambda point: point.eb_conversion))
        ax.plot(
            [point.eb_conversion * 100.0 for point in ordered_points],
            [point.styrene_selectivity * 100.0 for point in ordered_points],
            marker="o",
            label=f"{reactor_type}",
        )
    configure_axes(
        ax=ax,
        x_min_percent=GLOBAL_FRONT_X_MIN_PERCENT,
        y_min_percent=GLOBAL_FRONT_Y_MIN_PERCENT,
    )
    save_figure(fig=fig, output_path=output_path)


def plot_reactor_global_all_trials(
    studies: tuple[tuple[str, str, optuna.Study], ...],
    output_path: Path,
) -> None:
    """radial と axial の全完了 trial を反応器種別ごとにまとめて保存する。"""
    fig, ax = plt.subplots(figsize=(8, 6))
    for reactor_type in ("radial", "axial"):
        reactor_studies = select_studies(studies=studies, reactor_type=reactor_type)
        points = tuple(
            point
            for _, label, study in reactor_studies
            for point in points_from_study(study=study, reactor_type=reactor_type, label=label)
        )
        ax.scatter(
            [point.eb_conversion * 100.0 for point in points],
            [point.styrene_selectivity * 100.0 for point in points],
            alpha=0.65,
            label=f"{reactor_type} global all trials",
        )
    configure_axes(ax=ax, y_min_percent=GLOBAL_ALL_TRIALS_Y_MIN_PERCENT)
    save_figure(fig=fig, output_path=output_path)


def points_from_study(study: optuna.Study, reactor_type: str, label: str) -> tuple[ParetoPoint, ...]:
    """study の完了 trial を描画用モデルへ変換する。"""
    return tuple(
        point_from_trial(trial=trial, reactor_type=reactor_type, label=label)
        for trial in study.trials
        if trial.state is optuna.trial.TrialState.COMPLETE
    )


def point_from_trial(trial: optuna.trial.FrozenTrial, reactor_type: str, label: str) -> ParetoPoint:
    """trial の目的値を描画用モデルへ変換する。"""
    if trial.values is None or len(trial.values) != 2:
        raise ValueError(f"trial {trial.number} does not have two objective values")
    return ParetoPoint(
        styrene_selectivity=trial.values[0],
        eb_conversion=trial.values[1],
        reactor_type=reactor_type,
        label=label,
    )


def global_pareto_front(points: tuple[ParetoPoint, ...]) -> tuple[ParetoPoint, ...]:
    """入力点の非支配点を返す。"""
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


def configure_axes(
    ax: plt.Axes,
    x_min_percent: float | None = None,
    y_min_percent: float | None = None,
) -> None:
    """散布図の共通表示を設定する。"""
    ax.set_xlabel("EB 単通反応率 [%]")
    ax.set_ylabel("SM 選択率 [%]")
    if x_min_percent is not None:
        ax.set_xlim(left=x_min_percent)
    if y_min_percent is not None:
        ax.set_ylim(bottom=y_min_percent)
    ax.grid(False)
    ax.xaxis.label.set_size(AXIS_LABEL_FONT_SIZE)
    ax.yaxis.label.set_size(AXIS_LABEL_FONT_SIZE)
    ax.tick_params(
        axis="both",
        which="major",
        direction="in",
        top=True,
        right=True,
        length=6,
        width=1.0,
        labelsize=TICK_LABEL_FONT_SIZE,
    )
    ax.tick_params(axis="both", which="minor", direction="in", top=True, right=True, length=3, width=0.8)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.legend(frameon=False, fontsize=LEGEND_FONT_SIZE)


def save_figure(fig: plt.Figure, output_path: Path) -> None:
    """図を保存して閉じる。"""
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    plot_pareto_front_main()
