"""反応器の温度・圧力 profile を PNG として出力する。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import japanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt

from process_sim.cli import (
    ReactorModelName,
    apply_input_overrides,
    case_from_payload,
    default_case_payload,
    radial_case_from_payload,
)
from process_sim.plant.summary import format_pfr_reactor_report, format_radial_reactor_report
from process_sim.reactor.core.models import ReactorProfilePoint, ReactorResult, ReactorStageLog
from process_sim.reactor.core.stream import ReactorFeed
from process_sim.reactor.types.staged_adiabatic_pfr import StagedAdiabaticPfrModel
from process_sim.reactor.types.staged_adiabatic_radial import StagedAdiabaticRadialFlowModel


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = Path(__file__).resolve().parent / "media"
TEMPERATURE_OUTPUT_PATH = OUTPUT_DIR / "temperature_profile.png"
PRESSURE_OUTPUT_PATH = OUTPUT_DIR / "pressure_profile.png"


@dataclass(frozen=True)
class ProfileSeries:
    """描画用に整理した profile データ。"""

    reactor_model: ReactorModelName
    positions_m: list[float]
    temperatures_c: list[float]
    pressure_positions_m: list[float]
    pressures_kpa: list[float]
    stage_boundaries_m: list[float]


@dataclass(frozen=True)
class ReactorRunOutput:
    """反応器実行結果とログ表示に必要な feed。"""

    feed: ReactorFeed
    result: ReactorResult


def parse_args() -> argparse.Namespace:
    """CLI 引数を読む。"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reactor-model",
        choices=("radial", "pfr"),
        default="radial",
        help="使用する反応器モデル。既定は radial",
    )
    parser.add_argument(
        "--input-json",
        type=Path,
        default=None,
        help="入力値を上書きする JSON ファイルパス",
    )
    return parser.parse_args()


def run_reactor_case(reactor_model: ReactorModelName, input_json: Path | None) -> ReactorRunOutput:
    """指定された反応器ケースを実行する。"""
    payload = default_case_payload(reactor_model)
    payload = apply_input_overrides(payload, input_json)
    payload["reactor_model"] = reactor_model

    if reactor_model == "radial":
        radial_case = radial_case_from_payload(payload)
        result = StagedAdiabaticRadialFlowModel().run(
            feed=radial_case.feed,
            conditions=radial_case.conditions,
        )
        return ReactorRunOutput(feed=radial_case.feed, result=result)

    pfr_case = case_from_payload(payload)
    result = StagedAdiabaticPfrModel().run(
        feed=pfr_case.feed,
        conditions=pfr_case.conditions,
    )
    return ReactorRunOutput(feed=pfr_case.feed, result=result)


def format_reactor_report(reactor_model: ReactorModelName, output: ReactorRunOutput) -> str:
    """反応器モデルに応じた詳細ログを返す。"""
    if reactor_model == "radial":
        return format_radial_reactor_report(feed=output.feed, result=output.result)
    return format_pfr_reactor_report(feed=output.feed, result=output.result)


def stage_offsets(stage_logs: tuple[ReactorStageLog, ...]) -> dict[int, float]:
    """stage ごとの累積位置 offset を返す。"""
    offsets: dict[int, float] = {}
    current_offset = 0.0
    for stage_log in stage_logs:
        offsets[stage_log.stage_index] = current_offset
        current_offset += stage_log.stage_length_m
    return offsets


def stage_boundaries(stage_logs: tuple[ReactorStageLog, ...]) -> list[float]:
    """最終出口を除く stage 境界位置を返す。"""
    boundaries: list[float] = []
    current_position = 0.0
    for stage_log in stage_logs[:-1]:
        current_position += stage_log.stage_length_m
        boundaries.append(current_position)
    return boundaries


def profile_position_m(point: ReactorProfilePoint, offsets: dict[int, float]) -> float:
    """stage offset を考慮した profile 位置を返す。"""
    return offsets.get(point.stage_index, 0.0) + point.axial_position_m


def build_profile_series(reactor_model: ReactorModelName, result: ReactorResult) -> ProfileSeries:
    """ReactorResult を描画用データへ変換する。"""
    offsets = stage_offsets(result.log.stage_logs)
    positions_m = [profile_position_m(point, offsets) for point in result.log.profile]
    temperatures_c = [point.temperature_c for point in result.log.profile]

    pressure_points = [point for point in result.log.profile if point.pressure_kpa is not None]
    pressure_positions_m = [profile_position_m(point, offsets) for point in pressure_points]
    pressures_kpa = [cast(float, point.pressure_kpa) for point in pressure_points]

    return ProfileSeries(
        reactor_model=reactor_model,
        positions_m=positions_m,
        temperatures_c=temperatures_c,
        pressure_positions_m=pressure_positions_m,
        pressures_kpa=pressures_kpa,
        stage_boundaries_m=stage_boundaries(result.log.stage_logs),
    )


def configure_axes(ax: plt.Axes, xlabel: str, ylabel: str) -> None:
    """既存比較図と同じ軸スタイルを適用する。"""
    ax.tick_params(
        axis="both",
        which="both",
        direction="in",
        top=True,
        right=True,
    )
    ax.minorticks_on()
    ax.grid(False)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.legend(frameon=False)


def draw_stage_boundaries(ax: plt.Axes, boundaries_m: list[float]) -> None:
    """stage 境界を薄い破線で描く。"""
    for boundary_m in boundaries_m:
        ax.axvline(boundary_m, color="0.65", linestyle="--", linewidth=0.8)


def save_line_plot(
    x_values: list[float],
    y_values: list[float],
    boundaries_m: list[float],
    ylabel: str,
    output_path: Path,
    reactor_model: ReactorModelName,
) -> None:
    """profile の折れ線図を保存する。"""
    fig, ax = plt.subplots(figsize=(5.2, 3.6), dpi=300)
    ax.plot(x_values, y_values, label=reactor_model)
    draw_stage_boundaries(ax, boundaries_m)
    configure_axes(
        ax=ax,
        xlabel="反応器内累積位置 / m",
        ylabel=ylabel,
    )
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def save_profile_figures(series: ProfileSeries) -> None:
    """温度 profile と圧力 profile を保存する。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    save_line_plot(
        x_values=series.positions_m,
        y_values=series.temperatures_c,
        boundaries_m=series.stage_boundaries_m,
        ylabel="温度 / ℃",
        output_path=TEMPERATURE_OUTPUT_PATH,
        reactor_model=series.reactor_model,
    )
    save_line_plot(
        x_values=series.pressure_positions_m,
        y_values=series.pressures_kpa,
        boundaries_m=series.stage_boundaries_m,
        ylabel="圧力 / kPa",
        output_path=PRESSURE_OUTPUT_PATH,
        reactor_model=series.reactor_model,
    )


def main() -> None:
    """反応器 profile 図を作成する。"""
    args = parse_args()
    reactor_model = cast(Literal["radial", "pfr"], args.reactor_model)
    output = run_reactor_case(reactor_model=reactor_model, input_json=args.input_json)
    print(format_reactor_report(reactor_model=reactor_model, output=output))
    series = build_profile_series(reactor_model=reactor_model, result=output.result)
    save_profile_figures(series)
    print(f"Saved: {TEMPERATURE_OUTPUT_PATH.relative_to(REPO_ROOT)}")
    print(f"Saved: {PRESSURE_OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
