"""固定条件で1段 axial/radial 反応器の圧力損失を比較する。"""

from __future__ import annotations

from pathlib import Path
import math

import japanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator, MaxNLocator
from pydantic import BaseModel

from process_sim.constants.universal import UNIVERSAL_CONSTANTS
from process_sim.reactor.core.pressure_drop import ErgunParameters
from process_sim.reactor.core.radial_geometry import RadialBedGeometry
from process_sim.reactor.core.stream import ReactorStream
from process_sim.reactor.types.pfr_adiabatic import PfrAdiabaticReactor
from process_sim.reactor.types.radial_adiabatic import RadialAdiabaticReactor


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "media"
OUTPUT_PATH = OUTPUT_DIR / "pressure_profile_axial_vs_radial_fixed_1stage.png"

INLET_EB_KMOL_H = 400.0
STEAM_TO_EB_RATIO = 5.0
INLET_STREAM = ReactorStream(
    eb=INLET_EB_KMOL_H,
    steam=INLET_EB_KMOL_H * STEAM_TO_EB_RATIO,
)

INLET_TEMPERATURE_C = 600.0
INLET_TEMPERATURE_K = INLET_TEMPERATURE_C + 273.15
INLET_PRESSURE_KPA = 101.3
INLET_PRESSURE_PA = INLET_PRESSURE_KPA * 1000.0

CATALYST_VOLUME_M3 = 56.0
AXIAL_INLET_SUPERFICIAL_VELOCITY_M_S = 2.0
RADIAL_INNER_RADIUS_M = 1.0
RADIAL_BED_HEIGHT_M = 6.0

ERGUN_PARAMETERS = ErgunParameters(
    pellet_diameter_m=0.005,
    bed_void_fraction=0.431,
    catalyst_bulk_density_kg_m3=1422.0,
    ergun_a=1.75,
    ergun_b=150.0,
    gas_viscosity_pa_s=4.0e-5,
)

SEGMENTS = 12_000
PROFILE_POINTS = 240

FIGURE_SIZE = (6.4, 4.2)
FIGURE_DPI = 300
AXIS_LABEL_FONT_SIZE = 15
TICK_LABEL_FONT_SIZE = 13
LEGEND_FONT_SIZE = 12
LINE_WIDTH = 2.4


class PressureProfile(BaseModel):
    """圧力プロファイル描画に使う1系列分の結果。"""

    label: str
    catalyst_volume_m3: list[float]
    pressure_kpa: list[float]
    outlet_pressure_kpa: float
    pressure_drop_kpa: float
    eb_conversion: float
    styrene_selectivity: float
    inlet_superficial_velocity_m_s: float
    outlet_superficial_velocity_m_s: float


class AxialGeometry(BaseModel):
    """Axial flow 反応器の幾何条件。"""

    cross_section_area_m2: float
    diameter_m: float
    length_m: float


def inlet_volumetric_flow_m3_s() -> float:
    """入口 stream の理想気体体積流量を返す。"""
    total_flow_mol_s = INLET_STREAM.total_flow_kmol_s() * 1000.0
    return (
        total_flow_mol_s
        * UNIVERSAL_CONSTANTS.gas_constant_j_per_mol_k
        * INLET_TEMPERATURE_K
        / INLET_PRESSURE_PA
    )


def build_radial_geometry() -> RadialBedGeometry:
    """指定触媒体積から radial 触媒層厚みを決める。"""
    outer_radius_m = math.sqrt(
        RADIAL_INNER_RADIUS_M**2
        + CATALYST_VOLUME_M3 / (math.pi * RADIAL_BED_HEIGHT_M)
    )
    return RadialBedGeometry(
        inner_radius_m=RADIAL_INNER_RADIUS_M,
        bed_height_m=RADIAL_BED_HEIGHT_M,
        bed_thickness_m=outer_radius_m - RADIAL_INNER_RADIUS_M,
        catalyst_bulk_density_kg_m3=ERGUN_PARAMETERS.catalyst_bulk_density_kg_m3,
    )


def build_axial_geometry() -> AxialGeometry:
    """入口空塔速度から axial 反応器径と長さを決める。"""
    cross_section_area_m2 = (
        inlet_volumetric_flow_m3_s() / AXIAL_INLET_SUPERFICIAL_VELOCITY_M_S
    )
    diameter_m = math.sqrt(4.0 * cross_section_area_m2 / math.pi)
    length_m = CATALYST_VOLUME_M3 / cross_section_area_m2
    return AxialGeometry(
        cross_section_area_m2=cross_section_area_m2,
        diameter_m=diameter_m,
        length_m=length_m,
    )


def axial_catalyst_volume_at(
    axial_geometry: AxialGeometry,
    axial_position_m: float,
) -> float:
    """Axial flow 反応器の累積触媒体積を返す。"""
    return axial_geometry.cross_section_area_m2 * axial_position_m


def radial_catalyst_volume_at(
    radial_geometry: RadialBedGeometry,
    radial_position_m: float,
) -> float:
    """Radial flow 反応器の累積触媒体積を返す。"""
    return math.pi * radial_geometry.bed_height_m * (
        radial_position_m**2 - radial_geometry.inner_radius_m**2
    )


def run_axial(axial_geometry: AxialGeometry) -> PressureProfile:
    """1段 axial flow 反応器を計算する。"""
    result = PfrAdiabaticReactor().run(
        inlet=INLET_STREAM,
        feed=INLET_STREAM,
        stage_index=1,
        inlet_temperature_k=INLET_TEMPERATURE_K,
        inlet_pressure_pa=INLET_PRESSURE_PA,
        cross_section_area_m2=axial_geometry.cross_section_area_m2,
        stage_length_m=axial_geometry.length_m,
        cumulative_length_offset_m=0.0,
        ergun_parameters=ERGUN_PARAMETERS,
        catalyst_bulk_density_kg_m3=ERGUN_PARAMETERS.catalyst_bulk_density_kg_m3,
        segments=SEGMENTS,
        profile_points=PROFILE_POINTS,
    )
    pressure_kpa = [
        float(point.pressure_kpa)
        for point in result.profile
        if point.pressure_kpa is not None
    ]
    return PressureProfile(
        label="Axial flow",
        catalyst_volume_m3=[
            axial_catalyst_volume_at(
                axial_geometry=axial_geometry,
                axial_position_m=point.axial_position_m,
            )
            for point in result.profile
            if point.pressure_kpa is not None
        ],
        pressure_kpa=pressure_kpa,
        outlet_pressure_kpa=result.outlet.pressure_kpa,
        pressure_drop_kpa=result.stage_log.reactor_pressure_drop_kpa,
        eb_conversion=result.stage_log.eb_conversion,
        styrene_selectivity=result.stage_log.styrene_selectivity,
        inlet_superficial_velocity_m_s=(
            result.stage_log.inlet_superficial_velocity_m_per_s
        ),
        outlet_superficial_velocity_m_s=(
            result.stage_log.outlet_superficial_velocity_m_per_s
        ),
    )


def run_radial(radial_geometry: RadialBedGeometry) -> PressureProfile:
    """1段 radial flow 反応器を計算する。"""
    result = RadialAdiabaticReactor().run(
        inlet=INLET_STREAM,
        feed=INLET_STREAM,
        stage_index=1,
        inlet_temperature_k=INLET_TEMPERATURE_K,
        inlet_pressure_pa=INLET_PRESSURE_PA,
        geometry=radial_geometry,
        ergun_parameters=ERGUN_PARAMETERS,
        segments=SEGMENTS,
        profile_points=PROFILE_POINTS,
    )
    pressure_kpa = [
        float(point.pressure_kpa)
        for point in result.profile
        if point.pressure_kpa is not None
    ]
    return PressureProfile(
        label="Radial flow",
        catalyst_volume_m3=[
            radial_catalyst_volume_at(
                radial_geometry=radial_geometry,
                radial_position_m=float(point.radial_position_m),
            )
            for point in result.profile
            if point.pressure_kpa is not None and point.radial_position_m is not None
        ],
        pressure_kpa=pressure_kpa,
        outlet_pressure_kpa=result.outlet.pressure_kpa,
        pressure_drop_kpa=result.stage_log.reactor_pressure_drop_kpa,
        eb_conversion=result.stage_log.eb_conversion,
        styrene_selectivity=result.stage_log.styrene_selectivity,
        inlet_superficial_velocity_m_s=(
            result.stage_log.inlet_superficial_velocity_m_per_s
        ),
        outlet_superficial_velocity_m_s=(
            result.stage_log.outlet_superficial_velocity_m_per_s
        ),
    )


def configure_axes(ax: plt.Axes) -> None:
    """スライド掲載用の軸表示に整える。"""
    ax.set_xlabel("累積触媒体積 [m$^3$]")
    ax.set_ylabel("圧力 [kPa]")
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
    ax.grid(False)
    ax.legend(frameon=False, fontsize=LEGEND_FONT_SIZE, loc="lower left")


def save_pressure_plot(profiles: list[PressureProfile]) -> None:
    """圧力プロファイル図を保存する。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=FIGURE_SIZE, dpi=FIGURE_DPI)
    styles = {
        "Axial flow": {"color": "tab:orange", "linestyle": "-"},
        "Radial flow": {"color": "tab:blue", "linestyle": "-"},
    }
    for profile in profiles:
        ax.plot(
            profile.catalyst_volume_m3,
            profile.pressure_kpa,
            label=profile.label,
            linewidth=LINE_WIDTH,
            **styles[profile.label],
        )
    ax.set_xlim(left=0.0, right=CATALYST_VOLUME_M3)
    configure_axes(ax=ax)
    fig.tight_layout()
    fig.savefig(OUTPUT_PATH, bbox_inches="tight")
    plt.close(fig)


def print_case_summary(
    axial_geometry: AxialGeometry,
    radial_geometry: RadialBedGeometry,
    profiles: list[PressureProfile],
) -> None:
    """比較条件と計算結果を標準出力へ出す。"""
    print("Fixed one-stage axial/radial pressure-drop comparison")
    print(f"  EB feed            = {INLET_STREAM.eb:.3f} kmol/h")
    print(f"  Steam feed         = {INLET_STREAM.steam:.3f} kmol/h")
    print(f"  Steam/EB           = {INLET_STREAM.steam / INLET_STREAM.eb:.3f}")
    print(f"  inlet_temperature  = {INLET_TEMPERATURE_C:.3f} C")
    print(f"  inlet_pressure     = {INLET_PRESSURE_KPA:.3f} kPa")
    print(f"  catalyst_volume    = {CATALYST_VOLUME_M3:.6f} m3")
    print(
        f"  axial geometry     = D {axial_geometry.diameter_m:.6f} m, "
        f"A {axial_geometry.cross_section_area_m2:.6f} m2, "
        f"L {axial_geometry.length_m:.6f} m"
    )
    print(
        f"  radial geometry    = ri {radial_geometry.inner_radius_m:.6f} m, "
        f"ro {radial_geometry.outer_radius_m:.6f} m, "
        f"H {radial_geometry.bed_height_m:.6f} m, "
        f"delta {radial_geometry.bed_thickness_m:.6f} m"
    )
    for profile in profiles:
        print(
            f"  {profile.label:12s}: "
            f"outlet {profile.outlet_pressure_kpa:.3f} kPa, "
            f"deltaP {profile.pressure_drop_kpa:.3f} kPa, "
            f"uin {profile.inlet_superficial_velocity_m_s:.3f} m/s, "
            f"uout {profile.outlet_superficial_velocity_m_s:.3f} m/s, "
            f"X_EB {profile.eb_conversion:.4f}, "
            f"S_SM {profile.styrene_selectivity:.4f}"
        )
    print(f"Saved: {OUTPUT_PATH.relative_to(REPO_ROOT)}")


def main() -> None:
    """固定条件の圧力損失比較図を作成する。"""
    axial_geometry = build_axial_geometry()
    radial_geometry = build_radial_geometry()
    profiles = [
        run_radial(radial_geometry=radial_geometry),
        run_axial(axial_geometry=axial_geometry),
    ]
    save_pressure_plot(profiles=profiles)
    print_case_summary(
        axial_geometry=axial_geometry,
        radial_geometry=radial_geometry,
        profiles=profiles,
    )


if __name__ == "__main__":
    main()
