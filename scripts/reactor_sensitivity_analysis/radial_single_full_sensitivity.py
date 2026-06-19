"""1基ラジアル反応器の主要条件感度解析図を作成する。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import japanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator, MaxNLocator
from pydantic import BaseModel, Field

from process_sim.reactor.cases.styrene_default import DEFAULT_STYRENE_FEED
from process_sim.reactor.core.pressure_drop import ErgunParameters
from process_sim.reactor.core.radial_geometry import RadialBedGeometry
from process_sim.reactor.core.stream import ReactorFeed
from process_sim.reactor.types.radial_adiabatic import RadialAdiabaticReactor


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "media"

ATM_PRESSURE_PA = 101_300.0
BASE_TEMPERATURE_C = 600.0
BASE_PRESSURE_ATM = 1.0
BASE_STEAM_TO_EB_RATIO = 7.0
BASE_BED_THICKNESS_M = 0.6

TEMPERATURE_MIN_C = 550.0
TEMPERATURE_MAX_C = 650.0
TEMPERATURE_DIVISIONS = 20
PRESSURE_MIN_ATM = 0.9
PRESSURE_MAX_ATM = 2.0
PRESSURE_DIVISIONS = 22
STEAM_TO_EB_MIN = 5.0
STEAM_TO_EB_MAX = 11.0
STEAM_TO_EB_DIVISIONS = 20
BED_THICKNESS_MIN_M = 0.5
BED_THICKNESS_MAX_M = 1.0
BED_THICKNESS_DIVISIONS = 20

SEGMENTS = 12_000
PROFILE_POINTS = 12

INNER_RADIUS_M = 1.0
BED_HEIGHT_M = 6.0

ERGUN_PARAMETERS = ErgunParameters(
    pellet_diameter_m=0.003,
    bed_void_fraction=0.4312,
    catalyst_bulk_density_kg_m3=1422.0,
    ergun_a=1.75,
    ergun_b=150.0,
    gas_viscosity_pa_s=4.0e-5,
)

FIGURE_SIZE = (6.4, 4.2)
FIGURE_DPI = 300
AXIS_LABEL_FONT_SIZE = 15
TICK_LABEL_FONT_SIZE = 13
LEGEND_FONT_SIZE = 12
LINE_WIDTH = 2.4


class SensitivityCase(BaseModel):
    """1基ラジアル反応器の計算条件。"""

    temperature_c: float = BASE_TEMPERATURE_C
    pressure_atm: float = BASE_PRESSURE_ATM
    steam_to_eb_ratio: float = BASE_STEAM_TO_EB_RATIO
    bed_thickness_m: float = BASE_BED_THICKNESS_M


class SweepPoint(BaseModel):
    """感度解析の1点分の結果。"""

    x_value: float
    eb_single_pass_reaction: float
    styrene_selectivity: float


class SweepDefinition(BaseModel):
    """感度解析の定義。"""

    key: str
    x_label: str
    output_path: Path
    x_min: float
    x_max: float
    values: list[float]


class SweepSeries(BaseModel):
    """描画用の感度解析系列。"""

    definition: SweepDefinition
    points: list[SweepPoint] = Field(default_factory=list)


def inclusive_grid(start: float, stop: float, divisions: int) -> list[float]:
    """両端を含む等間隔グリッドを返す。"""
    if divisions <= 0:
        raise ValueError("divisions must be positive")
    step = (stop - start) / float(divisions)
    return [start + step * index for index in range(divisions + 1)]


def feed_from_steam_to_eb_ratio(steam_to_eb_ratio: float) -> ReactorFeed:
    """基準 feed の steam/EB 比だけを差し替えた feed を返す。"""
    return ReactorFeed(
        eb=DEFAULT_STYRENE_FEED.eb,
        steam=DEFAULT_STYRENE_FEED.eb * steam_to_eb_ratio,
        styrene=DEFAULT_STYRENE_FEED.styrene,
        hydrogen=DEFAULT_STYRENE_FEED.hydrogen,
        benzene=DEFAULT_STYRENE_FEED.benzene,
        toluene=DEFAULT_STYRENE_FEED.toluene,
        co2=DEFAULT_STYRENE_FEED.co2,
        ethylene=DEFAULT_STYRENE_FEED.ethylene,
        methane=DEFAULT_STYRENE_FEED.methane,
        co=DEFAULT_STYRENE_FEED.co,
    )


def build_geometry(bed_thickness_m: float) -> RadialBedGeometry:
    """指定した触媒層厚みのラジアル反応器 geometry を返す。"""
    return RadialBedGeometry(
        inner_radius_m=INNER_RADIUS_M,
        bed_height_m=BED_HEIGHT_M,
        bed_thickness_m=bed_thickness_m,
        catalyst_bulk_density_kg_m3=ERGUN_PARAMETERS.catalyst_bulk_density_kg_m3,
    )


def run_single_radial_case(case: SensitivityCase) -> SweepPoint:
    """1基ラジアル反応器を1条件で計算する。"""
    feed = feed_from_steam_to_eb_ratio(
        steam_to_eb_ratio=case.steam_to_eb_ratio,
    )
    result = RadialAdiabaticReactor().run(
        inlet=feed,
        feed=feed,
        stage_index=1,
        inlet_temperature_k=case.temperature_c + 273.15,
        inlet_pressure_pa=case.pressure_atm * ATM_PRESSURE_PA,
        geometry=build_geometry(bed_thickness_m=case.bed_thickness_m),
        ergun_parameters=ERGUN_PARAMETERS,
        segments=SEGMENTS,
        profile_points=PROFILE_POINTS,
    )
    return SweepPoint(
        x_value=0.0,
        eb_single_pass_reaction=result.stage_log.eb_conversion,
        styrene_selectivity=result.stage_log.styrene_selectivity,
    )


def sweep_case_factory(key: str) -> Callable[[float], SensitivityCase]:
    """sweep 対象の値から計算条件を作る関数を返す。"""
    factories: dict[str, Callable[[float], SensitivityCase]] = {
        "temperature": lambda value: SensitivityCase(temperature_c=value),
        "pressure": lambda value: SensitivityCase(pressure_atm=value),
        "steam_to_eb": lambda value: SensitivityCase(steam_to_eb_ratio=value),
        "bed_thickness": lambda value: SensitivityCase(bed_thickness_m=value),
    }
    return factories[key]


def build_sweep_definitions() -> list[SweepDefinition]:
    """実行する感度解析の定義一覧を返す。"""
    return [
        SweepDefinition(
            key="temperature",
            x_label="入口温度 [℃]",
            output_path=OUTPUT_DIR
            / "radial_single_temperature_vs_reaction_selectivity.png",
            x_min=TEMPERATURE_MIN_C,
            x_max=TEMPERATURE_MAX_C,
            values=inclusive_grid(
                start=TEMPERATURE_MIN_C,
                stop=TEMPERATURE_MAX_C,
                divisions=TEMPERATURE_DIVISIONS,
            ),
        ),
        SweepDefinition(
            key="pressure",
            x_label="入口圧力 [atm]",
            output_path=OUTPUT_DIR / "radial_single_pressure_vs_reaction_selectivity.png",
            x_min=PRESSURE_MIN_ATM,
            x_max=PRESSURE_MAX_ATM,
            values=inclusive_grid(
                start=PRESSURE_MIN_ATM,
                stop=PRESSURE_MAX_ATM,
                divisions=PRESSURE_DIVISIONS,
            ),
        ),
        SweepDefinition(
            key="steam_to_eb",
            x_label="Steam/EB 比 [-]",
            output_path=OUTPUT_DIR
            / "radial_single_steam_to_eb_vs_reaction_selectivity.png",
            x_min=STEAM_TO_EB_MIN,
            x_max=STEAM_TO_EB_MAX,
            values=inclusive_grid(
                start=STEAM_TO_EB_MIN,
                stop=STEAM_TO_EB_MAX,
                divisions=STEAM_TO_EB_DIVISIONS,
            ),
        ),
        SweepDefinition(
            key="bed_thickness",
            x_label="触媒層厚み [m]",
            output_path=OUTPUT_DIR
            / "radial_single_bed_thickness_vs_reaction_selectivity.png",
            x_min=BED_THICKNESS_MIN_M,
            x_max=BED_THICKNESS_MAX_M,
            values=inclusive_grid(
                start=BED_THICKNESS_MIN_M,
                stop=BED_THICKNESS_MAX_M,
                divisions=BED_THICKNESS_DIVISIONS,
            ),
        ),
    ]


def run_sweep(definition: SweepDefinition) -> SweepSeries:
    """1つの操作変数について感度解析を行う。"""
    build_case = sweep_case_factory(key=definition.key)
    points: list[SweepPoint] = []
    total_count = len(definition.values)
    for index, x_value in enumerate(definition.values, start=1):
        case = build_case(x_value)
        print(
            f"[{definition.key}] {index}/{total_count} "
            f"x={x_value:.6g}, "
            f"T={case.temperature_c:.3f} C, "
            f"P={case.pressure_atm:.3f} atm, "
            f"S/EB={case.steam_to_eb_ratio:.3f}, "
            f"delta={case.bed_thickness_m:.3f} m"
        )
        point = run_single_radial_case(case=case)
        points.append(point.model_copy(update={"x_value": x_value}))
        print(
            f"[{definition.key}] {index}/{total_count} done "
            f"X_EB={point.eb_single_pass_reaction:.4f}, "
            f"S_SM={point.styrene_selectivity:.4f}"
        )
    return SweepSeries(definition=definition, points=points)


def configure_axes(
    ax: plt.Axes,
    right_ax: plt.Axes,
    definition: SweepDefinition,
) -> None:
    """比較しやすい固定軸の図体裁を適用する。"""
    ax.set_xlabel(definition.x_label)
    ax.set_ylabel("EB単通反応率 [%]")
    right_ax.set_ylabel("SM選択率 [%]")
    ax.xaxis.label.set_size(AXIS_LABEL_FONT_SIZE)
    ax.yaxis.label.set_size(AXIS_LABEL_FONT_SIZE)
    right_ax.yaxis.label.set_size(AXIS_LABEL_FONT_SIZE)
    ax.tick_params(
        axis="both",
        which="major",
        direction="in",
        top=True,
        right=False,
        length=6,
        width=1.0,
        labelsize=TICK_LABEL_FONT_SIZE,
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
        labelsize=TICK_LABEL_FONT_SIZE,
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
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    right_ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    right_ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.set_xlim(definition.x_min, definition.x_max)
    ax.set_ylim(0.0, 100.0)
    right_ax.set_ylim(80.0, 100.0)
    ax.grid(False)
    right_ax.grid(False)


def save_sensitivity_plot(series: SweepSeries) -> None:
    """感度解析結果を PNG として保存する。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    x_values = [point.x_value for point in series.points]
    reactions_percent = [
        point.eb_single_pass_reaction * 100.0 for point in series.points
    ]
    selectivities_percent = [
        point.styrene_selectivity * 100.0 for point in series.points
    ]

    fig, ax = plt.subplots(figsize=FIGURE_SIZE, dpi=FIGURE_DPI)
    right_ax = ax.twinx()
    reaction_line = ax.plot(
        x_values,
        reactions_percent,
        color="tab:blue",
        linestyle="-",
        linewidth=LINE_WIDTH,
        label="EB単通反応率",
    )
    selectivity_line = right_ax.plot(
        x_values,
        selectivities_percent,
        color="tab:orange",
        linestyle="-",
        linewidth=LINE_WIDTH,
        label="SM選択率",
    )
    configure_axes(ax=ax, right_ax=right_ax, definition=series.definition)
    lines = reaction_line + selectivity_line
    labels = [line.get_label() for line in lines]
    ax.legend(lines, labels, frameon=False, fontsize=LEGEND_FONT_SIZE, loc="lower right")
    fig.tight_layout()
    fig.savefig(series.definition.output_path, bbox_inches="tight")
    plt.close(fig)


def print_summary(series: SweepSeries) -> None:
    """sweep 結果の簡易 summary を標準出力へ出す。"""
    print(series.definition.output_path.relative_to(REPO_ROOT))
    for point in series.points:
        print(
            f"  x={point.x_value:.6g}, "
            f"X_EB={point.eb_single_pass_reaction:.4f}, "
            f"S_SM={point.styrene_selectivity:.4f}"
        )


def main() -> None:
    """1基ラジアル反応器の主要条件感度解析図を作成する。"""
    for definition in build_sweep_definitions():
        series = run_sweep(definition=definition)
        save_sensitivity_plot(series=series)
        print_summary(series=series)


if __name__ == "__main__":
    main()
