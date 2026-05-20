"""Compare pressure profiles of one PFR and one radial-flow reactor.

The purpose of this script is to compare pressure drop only under a fixed,
explicit case definition. Both reactors receive the same inlet stream,
temperature, pressure, catalyst properties, and total catalyst volume.

Run from the repository root:
    uv run python scripts/axial-radial-comparison/compare.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math

import matplotlib.pyplot as plt

from process_sim.reactor.core.pressure_drop import ErgunParameters
from process_sim.reactor.core.radial_geometry import RadialBedGeometry
from process_sim.reactor.core.stream import ReactorStream
from process_sim.reactor.types.pfr_adiabatic import PfrAdiabaticReactor
from process_sim.reactor.types.radial_adiabatic import RadialAdiabaticReactor

ROOT_DIR = Path(__file__).resolve().parents[2]

# -----------------------------------------------------------------------------
# Fixed comparison case
# -----------------------------------------------------------------------------
# Inlet flow is taken from the supplied reactor log. Units are kmol/h.
INLET_STREAM = ReactorStream(
    eb=395.707,
    steam=1978.349,
    styrene=0.495,
    hydrogen=0.025,
    benzene=1.393,
    toluene=1.998,
    co2=0.053,
    ethylene=0.0,
    methane=0.004,
    co=0.0,
)

# Same inlet conditions for both reactors.
INLET_TEMPERATURE_K = 600.0 + 273.15
INLET_PRESSURE_PA = 101_300.0

# Same catalyst and Ergun parameters for both reactors.
ERGUN_PARAMETERS = ErgunParameters(
    pellet_diameter_m=0.003,
    bed_void_fraction=0.4312,
    catalyst_bulk_density_kg_m3=1422.0,
    ergun_a=1.75,
    ergun_b=150.0,
    gas_viscosity_pa_s=4.0e-5,
)

# Radial-flow reactor case. This geometry fixes the catalyst volume.
RADIAL_GEOMETRY = RadialBedGeometry(
    inner_radius_m=1.0,
    bed_height_m=5.0,
    bed_thickness_m=0.90,
    catalyst_bulk_density_kg_m3=ERGUN_PARAMETERS.catalyst_bulk_density_kg_m3,
)

# PFR case. The cross-sectional area is set equal to the radial reactor inlet
# flow area, so the inlet superficial mass velocity is also equal. The length
# is then chosen so that the PFR catalyst volume equals the radial bed volume.
PFR_CROSS_SECTION_AREA_M2 = RADIAL_GEOMETRY.flow_area_m2(
    RADIAL_GEOMETRY.inner_radius_m
)
PFR_LENGTH_M = RADIAL_GEOMETRY.catalyst_volume_m3 / PFR_CROSS_SECTION_AREA_M2

SEGMENTS = 12_000
PROFILE_POINTS = 240
OUTPUT_DIR = Path(__file__).resolve().parent / "media"
OUTPUT_PATH = OUTPUT_DIR / "pressure_profile_pfr_vs_radial.png"


@dataclass(frozen=True)
class PressureProfile:
    label: str
    catalyst_volume_m3: list[float]
    pressure_kpa: list[float]
    eb_conversion: float
    styrene_selectivity: float


def pfr_catalyst_volume_at(axial_position_m: float) -> float:
    """Cumulative catalyst volume in the PFR."""
    return PFR_CROSS_SECTION_AREA_M2 * axial_position_m


def radial_catalyst_volume_at(radial_position_m: float) -> float:
    """Cumulative annular catalyst volume from the inner radius."""
    inner = RADIAL_GEOMETRY.inner_radius_m
    height = RADIAL_GEOMETRY.bed_height_m
    return math.pi * height * (radial_position_m**2 - inner**2)


def run_pfr() -> PressureProfile:
    result = PfrAdiabaticReactor().run(
        inlet=INLET_STREAM,
        feed=INLET_STREAM,
        stage_index=1,
        inlet_temperature_k=INLET_TEMPERATURE_K,
        inlet_pressure_pa=INLET_PRESSURE_PA,
        cross_section_area_m2=PFR_CROSS_SECTION_AREA_M2,
        stage_length_m=PFR_LENGTH_M,
        cumulative_length_offset_m=0.0,
        ergun_parameters=ERGUN_PARAMETERS,
        catalyst_bulk_density_kg_m3=ERGUN_PARAMETERS.catalyst_bulk_density_kg_m3,
        segments=SEGMENTS,
        profile_points=PROFILE_POINTS,
    )
    return PressureProfile(
        label="Axial-flow",
        catalyst_volume_m3=[
            pfr_catalyst_volume_at(p.axial_position_m) for p in result.profile
        ],
        pressure_kpa=[
            float(p.pressure_kpa)
            for p in result.profile
            if p.pressure_kpa is not None
        ],
        eb_conversion=result.stage_log.eb_conversion,
        styrene_selectivity=result.stage_log.styrene_selectivity,
    )


def run_radial() -> PressureProfile:
    result = RadialAdiabaticReactor().run(
        inlet=INLET_STREAM,
        feed=INLET_STREAM,
        stage_index=1,
        inlet_temperature_k=INLET_TEMPERATURE_K,
        inlet_pressure_pa=INLET_PRESSURE_PA,
        geometry=RADIAL_GEOMETRY,
        ergun_parameters=ERGUN_PARAMETERS,
        segments=SEGMENTS,
        profile_points=PROFILE_POINTS,
    )
    return PressureProfile(
        label="Radial-flow",
        catalyst_volume_m3=[
            radial_catalyst_volume_at(float(p.radial_position_m))
            for p in result.profile
            if p.radial_position_m is not None
        ],
        pressure_kpa=[
            float(p.pressure_kpa)
            for p in result.profile
            if p.pressure_kpa is not None
        ],
        eb_conversion=result.stage_log.eb_conversion,
        styrene_selectivity=result.stage_log.styrene_selectivity,
    )


def configure_axes(ax: plt.Axes) -> None:
    """Apply a simple academic figure style."""
    ax.tick_params(
        axis="both",
        which="both",
        direction="in",
        top=True,
        right=True,
    )
    ax.minorticks_on()
    ax.grid(False)
    ax.set_xlabel("Cumulative catalyst volume, $V_{cat}$ / m$^3$")
    ax.set_ylabel("Pressure / kPa")
    ax.legend(frameon=False)


def plot_profiles(profiles: list[PressureProfile]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(5.2, 3.6), dpi=300)

    for profile in profiles:
        ax.plot(profile.catalyst_volume_m3, profile.pressure_kpa, label=profile.label)

    annotation_lines = [
        (
            f"{profile.label}: "
            f"$X_{{EB}}$ = {profile.eb_conversion:.3f}, "
            f"$S_{{SM}}$ = {profile.styrene_selectivity:.3f}"
        )
        for profile in profiles
    ]

    ax.text(
        0.03,
        0.05,
        "\n".join(annotation_lines),
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=8,
        bbox={
            "boxstyle": "round,pad=0.3",
            "facecolor": "white",
            "edgecolor": "none",
            "alpha": 0.8,
        },
    )

    configure_axes(ax)
    fig.tight_layout()
    fig.savefig(OUTPUT_PATH, bbox_inches="tight")
    plt.close(fig)


def print_case_summary(profiles: list[PressureProfile]) -> None:
    print("Fixed comparison case")
    print(f"  inlet_temperature = {INLET_TEMPERATURE_K:.2f} K")
    print(f"  inlet_pressure    = {INLET_PRESSURE_PA / 1000.0:.3f} kPa")
    print(f"  catalyst_volume  = {RADIAL_GEOMETRY.catalyst_volume_m3:.6f} m3")
    print(
        f"  radial geometry   = ri {RADIAL_GEOMETRY.inner_radius_m:.3f} m, "
        f"H {RADIAL_GEOMETRY.bed_height_m:.3f} m, "
        f"delta {RADIAL_GEOMETRY.bed_thickness_m:.3f} m"
    )
    print(
        f"  pfr geometry      = A {PFR_CROSS_SECTION_AREA_M2:.6f} m2, "
        f"L {PFR_LENGTH_M:.6f} m"
    )

    for profile in profiles:
        dp = profile.pressure_kpa[0] - profile.pressure_kpa[-1]
        print(
            f"  {profile.label:20s}: "
            f"outlet {profile.pressure_kpa[-1]:.3f} kPa, "
            f"deltaP {dp:.3f} kPa, "
            f"X_EB {profile.eb_conversion:.4f}, "
            f"S_SM {profile.styrene_selectivity:.4f}"
        )

    print(f"Saved: {OUTPUT_PATH.relative_to(ROOT_DIR)}")


def main() -> None:
    pfr_profile = run_pfr()
    radial_profile = run_radial()
    profiles = [pfr_profile, radial_profile]
    plot_profiles(profiles)
    print_case_summary(profiles)


if __name__ == "__main__":
    main()