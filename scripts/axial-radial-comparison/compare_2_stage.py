"""Compare pressure profiles of two-stage PFR and two-stage radial-flow reactors.

Both reactor systems use:
- the same inlet stream,
- the same inlet pressure,
- the same inlet temperature for each stage,
- the same catalyst and Ergun parameters,
- the same total catalyst volume.

Run from the repository root:
    uv run python scripts/axial-radial-comparison/compare_two_stage.py
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

# Same inlet conditions for both reactor systems.
# Each second-stage inlet is reheated to this same temperature.
INLET_TEMPERATURE_K = 600.0 + 273.15
INLET_PRESSURE_PA = 101_300.0

# Interstage pressure drop is set to zero in this comparison.
# This keeps the figure focused on packed-bed pressure drop.
INTERSTAGE_PRESSURE_DROP_PA = 20_000.0

# Same catalyst and Ergun parameters for both reactor systems.
ERGUN_PARAMETERS = ErgunParameters(
    pellet_diameter_m=0.003,
    bed_void_fraction=0.4312,
    catalyst_bulk_density_kg_m3=1422.0,
    ergun_a=1.75,
    ergun_b=150.0,
    gas_viscosity_pa_s=4.0e-5,
)

STAGES = 2

# Radial-flow reactor case per stage.
# Total catalyst volume is STAGES times this stage volume.
RADIAL_STAGE_GEOMETRY = RadialBedGeometry(
    inner_radius_m=1.0,
    bed_height_m=5.0,
    bed_thickness_m=0.90,
    catalyst_bulk_density_kg_m3=ERGUN_PARAMETERS.catalyst_bulk_density_kg_m3,
)

TOTAL_CATALYST_VOLUME_M3 = STAGES * RADIAL_STAGE_GEOMETRY.catalyst_volume_m3

# PFR case.
# Cross-sectional area is set equal to the radial reactor inlet flow area,
# so the inlet superficial mass velocity is also equal.
# Stage length is chosen so that each PFR stage volume equals each radial stage volume.
PFR_CROSS_SECTION_AREA_M2 = RADIAL_STAGE_GEOMETRY.flow_area_m2(
    RADIAL_STAGE_GEOMETRY.inner_radius_m
)
PFR_STAGE_LENGTH_M = (
    RADIAL_STAGE_GEOMETRY.catalyst_volume_m3 / PFR_CROSS_SECTION_AREA_M2
)

SEGMENTS_PER_STAGE = 12_000
PROFILE_POINTS_PER_STAGE = 120
OUTPUT_DIR = Path(__file__).resolve().parent / "media"
OUTPUT_PATH = OUTPUT_DIR / "pressure_profile_pfr_vs_radial_2stage.png"


@dataclass(frozen=True)
class PressureProfile:
    label: str
    catalyst_volume_m3: list[float]
    pressure_kpa: list[float]
    eb_conversion: float
    styrene_selectivity: float


def pfr_catalyst_volume_at(
    stage_index: int,
    axial_position_m: float,
) -> float:
    """Cumulative catalyst volume in the two-stage PFR."""
    stage_offset_volume = (stage_index - 1) * PFR_CROSS_SECTION_AREA_M2 * PFR_STAGE_LENGTH_M
    local_volume = PFR_CROSS_SECTION_AREA_M2 * axial_position_m
    return stage_offset_volume + local_volume


def radial_catalyst_volume_at(
    stage_index: int,
    radial_position_m: float,
) -> float:
    """Cumulative catalyst volume in the two-stage radial-flow reactor."""
    inner = RADIAL_STAGE_GEOMETRY.inner_radius_m
    height = RADIAL_STAGE_GEOMETRY.bed_height_m
    stage_offset_volume = (stage_index - 1) * RADIAL_STAGE_GEOMETRY.catalyst_volume_m3
    local_volume = math.pi * height * (radial_position_m**2 - inner**2)
    return stage_offset_volume + local_volume


def run_pfr_two_stage() -> PressureProfile:
    reactor = PfrAdiabaticReactor()
    current_stream = INLET_STREAM
    current_pressure_pa = INLET_PRESSURE_PA

    catalyst_volume_m3: list[float] = []
    pressure_kpa: list[float] = []

    for stage_index in range(1, STAGES + 1):
        result = reactor.run(
            inlet=current_stream,
            feed=INLET_STREAM,
            stage_index=stage_index,
            inlet_temperature_k=INLET_TEMPERATURE_K,
            inlet_pressure_pa=current_pressure_pa,
            cross_section_area_m2=PFR_CROSS_SECTION_AREA_M2,
            stage_length_m=PFR_STAGE_LENGTH_M,
            cumulative_length_offset_m=(stage_index - 1) * PFR_STAGE_LENGTH_M,
            ergun_parameters=ERGUN_PARAMETERS,
            catalyst_bulk_density_kg_m3=ERGUN_PARAMETERS.catalyst_bulk_density_kg_m3,
            segments=SEGMENTS_PER_STAGE,
            profile_points=PROFILE_POINTS_PER_STAGE,
        )

        for point in result.profile:
            if point.pressure_kpa is None:
                continue
            catalyst_volume_m3.append(
                pfr_catalyst_volume_at(
                    stage_index=stage_index,
                    axial_position_m=point.axial_position_m,
                )
            )
            pressure_kpa.append(float(point.pressure_kpa))

        current_stream = result.outlet.stream
        current_pressure_pa = max(
            result.outlet.pressure_kpa * 1000.0 - INTERSTAGE_PRESSURE_DROP_PA,
            1.0,
        )

    return PressureProfile(
        label="Axial flow",
        catalyst_volume_m3=catalyst_volume_m3,
        pressure_kpa=pressure_kpa,
        eb_conversion=reactor.eb_conversion(feed=INLET_STREAM, stream=current_stream),
        styrene_selectivity=reactor.styrene_selectivity(
            feed=INLET_STREAM,
            stream=current_stream,
        ),
    )


def run_radial_two_stage() -> PressureProfile:
    reactor = RadialAdiabaticReactor()
    current_stream = INLET_STREAM
    current_pressure_pa = INLET_PRESSURE_PA

    catalyst_volume_m3: list[float] = []
    pressure_kpa: list[float] = []

    for stage_index in range(1, STAGES + 1):
        result = reactor.run(
            inlet=current_stream,
            feed=INLET_STREAM,
            stage_index=stage_index,
            inlet_temperature_k=INLET_TEMPERATURE_K,
            inlet_pressure_pa=current_pressure_pa,
            geometry=RADIAL_STAGE_GEOMETRY,
            ergun_parameters=ERGUN_PARAMETERS,
            segments=SEGMENTS_PER_STAGE,
            profile_points=PROFILE_POINTS_PER_STAGE,
        )

        for point in result.profile:
            if point.pressure_kpa is None or point.radial_position_m is None:
                continue
            catalyst_volume_m3.append(
                radial_catalyst_volume_at(
                    stage_index=stage_index,
                    radial_position_m=float(point.radial_position_m),
                )
            )
            pressure_kpa.append(float(point.pressure_kpa))

        current_stream = result.outlet.stream
        current_pressure_pa = max(
            result.outlet.pressure_kpa * 1000.0 - INTERSTAGE_PRESSURE_DROP_PA,
            1.0,
        )

    return PressureProfile(
        label="Radial flow",
        catalyst_volume_m3=catalyst_volume_m3,
        pressure_kpa=pressure_kpa,
        eb_conversion=reactor.eb_conversion(feed=INLET_STREAM, stream=current_stream),
        styrene_selectivity=reactor.styrene_selectivity(
            feed=INLET_STREAM,
            stream=current_stream,
        ),
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
    ax.legend(loc="upper right", frameon=False)


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
    print("Fixed two-stage comparison case")
    print(f"  stages             = {STAGES}")
    print(f"  stage_temperature  = {INLET_TEMPERATURE_K:.2f} K")
    print(f"  inlet_pressure     = {INLET_PRESSURE_PA / 1000.0:.3f} kPa")
    print(f"  interstage_dp      = {INTERSTAGE_PRESSURE_DROP_PA / 1000.0:.3f} kPa")
    print(f"  total_cat_volume   = {TOTAL_CATALYST_VOLUME_M3:.6f} m3")
    print(
        f"  radial stage geom  = ri {RADIAL_STAGE_GEOMETRY.inner_radius_m:.3f} m, "
        f"H {RADIAL_STAGE_GEOMETRY.bed_height_m:.3f} m, "
        f"delta {RADIAL_STAGE_GEOMETRY.bed_thickness_m:.3f} m"
    )
    print(
        f"  pfr stage geom     = A {PFR_CROSS_SECTION_AREA_M2:.6f} m2, "
        f"L {PFR_STAGE_LENGTH_M:.6f} m"
    )

    for profile in profiles:
        dp = profile.pressure_kpa[0] - profile.pressure_kpa[-1]
        print(
            f"  {profile.label:30s}: "
            f"outlet {profile.pressure_kpa[-1]:.3f} kPa, "
            f"deltaP {dp:.3f} kPa, "
            f"X_EB {profile.eb_conversion:.4f}, "
            f"S_SM {profile.styrene_selectivity:.4f}"
        )

    print(f"Saved: {OUTPUT_PATH.relative_to(ROOT_DIR)}")


def main() -> None:
    pfr_profile = run_pfr_two_stage()
    radial_profile = run_radial_two_stage()
    profiles = [pfr_profile, radial_profile]
    plot_profiles(profiles)
    print_case_summary(profiles)


if __name__ == "__main__":
    main()