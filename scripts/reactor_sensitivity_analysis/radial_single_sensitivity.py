"""1基ラジアル反応器の温度・圧力感度解析図を作成する。"""

from __future__ import annotations

from pathlib import Path

import japanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator, MaxNLocator
from pydantic import BaseModel, Field

from process_sim.reactor.cases.styrene_default import DEFAULT_STYRENE_FEED
from process_sim.reactor.core.pressure_drop import ErgunParameters
from process_sim.reactor.core.radial_geometry import RadialBedGeometry
from process_sim.reactor.types.radial_adiabatic import RadialAdiabaticReactor


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "media"
TEMPERATURE_OUTPUT_PATH = OUTPUT_DIR / "temperature_vs_conversion_selectivity.png"
PRESSURE_OUTPUT_PATH = OUTPUT_DIR / "pressure_vs_conversion_selectivity.png"

ATM_PRESSURE_PA = 101_325.0
BASE_TEMPERATURE_C = 600.0
BASE_PRESSURE_ATM = 1.0
TEMPERATURE_MIN_C = 550.0
TEMPERATURE_MAX_C = 650.0
TEMPERATURE_DIVISIONS = 20
PRESSURE_MIN_ATM = 0.5
PRESSURE_MAX_ATM = 1.5
PRESSURE_DIVISIONS = 20
SEGMENTS = 12_000
PROFILE_POINTS = 12

DEFAULT_GEOMETRY = RadialBedGeometry(
    inner_radius_m=1.0,
    bed_height_m=5.0,
    bed_thickness_m=0.90,
    catalyst_bulk_density_kg_m3=1422.0,
)
DEFAULT_ERGUN_PARAMETERS = ErgunParameters(
    pellet_diameter_m=0.003,
    bed_void_fraction=0.4312,
    catalyst_bulk_density_kg_m3=1422.0,
    ergun_a=1.75,
    ergun_b=150.0,
    gas_viscosity_pa_s=4.0e-5,
)


class SweepPoint(BaseModel):
    """感度解析の1点分の結果。"""

    x_value: float
    eb_conversion: float
    styrene_selectivity: float


class SweepSeries(BaseModel):
    """描画用の感度解析系列。"""

    x_label: str
    output_path: Path
    points: list[SweepPoint] = Field(default_factory=list)


def inclusive_grid(start: float, stop: float, divisions: int) -> list[float]:
    """両端を含む等間隔グリッドを返す。"""
    if divisions <= 0:
        raise ValueError("divisions must be positive")
    step = (stop - start) / float(divisions)
    return [start + step * index for index in range(divisions + 1)]


def run_single_radial_case(
    temperature_c: float,
    pressure_atm: float,
    segments: int,
    profile_points: int,
) -> tuple[float, float]:
    """1基ラジアル反応器を1条件で計算する。"""
    result = RadialAdiabaticReactor().run(
        inlet=DEFAULT_STYRENE_FEED,
        feed=DEFAULT_STYRENE_FEED,
        stage_index=1,
        inlet_temperature_k=temperature_c + 273.15,
        inlet_pressure_pa=pressure_atm * ATM_PRESSURE_PA,
        geometry=DEFAULT_GEOMETRY,
        ergun_parameters=DEFAULT_ERGUN_PARAMETERS,
        segments=segments,
        profile_points=profile_points,
    )
    return result.stage_log.eb_conversion, result.stage_log.styrene_selectivity


def temperature_sweep() -> SweepSeries:
    """圧力を固定して温度感度解析を行う。"""
    temperatures_c = inclusive_grid(
        start=TEMPERATURE_MIN_C,
        stop=TEMPERATURE_MAX_C,
        divisions=TEMPERATURE_DIVISIONS,
    )
    total_count = len(temperatures_c)
    points: list[SweepPoint] = []
    for index, temperature_c in enumerate(temperatures_c, start=1):
        print(
            f"[temperature] {index}/{total_count} "
            f"T={temperature_c:.3f} C, P={BASE_PRESSURE_ATM:.3f} atm"
        )
        eb_conversion, styrene_selectivity = run_single_radial_case(
            temperature_c=temperature_c,
            pressure_atm=BASE_PRESSURE_ATM,
            segments=SEGMENTS,
            profile_points=PROFILE_POINTS,
        )
        print(
            f"[temperature] {index}/{total_count} done "
            f"X_EB={eb_conversion:.4f}, S_SM={styrene_selectivity:.4f}"
        )
        points.append(
            SweepPoint(
                x_value=temperature_c,
                eb_conversion=eb_conversion,
                styrene_selectivity=styrene_selectivity,
            )
        )
    return SweepSeries(
        x_label="入口温度 / ℃",
        output_path=TEMPERATURE_OUTPUT_PATH,
        points=points,
    )


def pressure_sweep() -> SweepSeries:
    """温度を固定して圧力感度解析を行う。"""
    pressures_atm = inclusive_grid(
        start=PRESSURE_MIN_ATM,
        stop=PRESSURE_MAX_ATM,
        divisions=PRESSURE_DIVISIONS,
    )
    total_count = len(pressures_atm)
    points: list[SweepPoint] = []
    for index, pressure_atm in enumerate(pressures_atm, start=1):
        print(
            f"[pressure] {index}/{total_count} "
            f"T={BASE_TEMPERATURE_C:.3f} C, P={pressure_atm:.3f} atm"
        )
        eb_conversion, styrene_selectivity = run_single_radial_case(
            temperature_c=BASE_TEMPERATURE_C,
            pressure_atm=pressure_atm,
            segments=SEGMENTS,
            profile_points=PROFILE_POINTS,
        )
        print(
            f"[pressure] {index}/{total_count} done "
            f"X_EB={eb_conversion:.4f}, S_SM={styrene_selectivity:.4f}"
        )
        points.append(
            SweepPoint(
                x_value=pressure_atm,
                eb_conversion=eb_conversion,
                styrene_selectivity=styrene_selectivity,
            )
        )
    return SweepSeries(
        x_label="入口圧力 / atm",
        output_path=PRESSURE_OUTPUT_PATH,
        points=points,
    )


def configure_axes(ax: plt.Axes, right_ax: plt.Axes, x_label: str) -> None:
    """既存の比較図に合わせた軸スタイルを適用する。"""
    ax.tick_params(
        axis="both",
        which="major",
        direction="in",
        top=True,
        right=False,
        length=6,
        width=1.0,
    )
    ax.tick_params(
        axis="both",
        which="minor",
        direction="in",
        top=True,
        right=False,
        length=3,
        width=0.8,
    )
    right_ax.tick_params(
        axis="y",
        which="major",
        direction="in",
        left=False,
        right=True,
        length=6,
        width=1.0,
    )
    right_ax.tick_params(
        axis="y",
        which="minor",
        direction="in",
        left=False,
        right=True,
        length=3,
        width=0.8,
    )
    right_ax.tick_params(axis="x", which="both", bottom=False, top=False)

    ax.grid(False)
    right_ax.grid(False)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    right_ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
    right_ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.set_xlabel(x_label)
    ax.set_ylabel("EB単通転化率 / %")
    right_ax.set_ylabel("SM選択率 / %")


def save_sensitivity_plot(series: SweepSeries) -> None:
    """感度解析結果を PNG として保存する。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    x_values = [point.x_value for point in series.points]
    conversions_percent = [point.eb_conversion * 100.0 for point in series.points]
    selectivities_percent = [point.styrene_selectivity * 100.0 for point in series.points]

    fig, ax = plt.subplots(figsize=(5.2, 3.6), dpi=300)
    right_ax = ax.twinx()
    conversion_line = ax.plot(
        x_values,
        conversions_percent,
        linestyle="-",
        label="EB単通転化率",
    )
    selectivity_line = right_ax.plot(
        x_values,
        selectivities_percent,
        linestyle="-",
        color="tab:orange",
        label="SM選択率",
    )

    configure_axes(ax=ax, right_ax=right_ax, x_label=series.x_label)
    lines = conversion_line + selectivity_line
    labels = [line.get_label() for line in lines]
    ax.legend(
        lines,
        labels,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.16),
        ncol=2,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.92))
    fig.savefig(series.output_path, bbox_inches="tight")
    plt.close(fig)


def print_summary(series: SweepSeries) -> None:
    """sweep 結果の簡易 summary を標準出力へ出す。"""
    print(series.output_path.relative_to(REPO_ROOT))
    for point in series.points:
        print(
            f"  x={point.x_value:.3f}, "
            f"X_EB={point.eb_conversion:.4f}, "
            f"S_SM={point.styrene_selectivity:.4f}"
        )


def main() -> None:
    """温度・圧力感度解析図を作成する。"""
    series_list = [temperature_sweep(), pressure_sweep()]
    for series in series_list:
        save_sensitivity_plot(series)
        print_summary(series)


if __name__ == "__main__":
    main()
