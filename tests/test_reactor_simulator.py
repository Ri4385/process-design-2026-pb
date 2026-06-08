from dataclasses import replace

import pytest

from process_sim.constants.physical_properties import SPECIES_PHYSICAL_PROPERTIES
from process_sim.constants.reaction_networks import STYRENE_SIX_REACTION_NETWORK
from process_sim.constants.universal import UNIVERSAL_CONSTANTS
from process_sim.reactor.cases.styrene_radial_default import RadialReactorCase
from process_sim.reactor.cases.styrene_default import ReactorCase
from process_sim.reactor.core.balance import (
    ReactorBalanceContext,
    pfr_adiabatic_derivatives,
)
from process_sim.reactor.core import config
from process_sim.reactor.core.models import (
    RadialReactorRunConditions,
    ReactorRunConditions,
)
from process_sim.reactor.core.pressure_drop import ErgunParameters
from process_sim.reactor.core.reaction import reaction_rates
from process_sim.reactor.core.stream import COMPONENT_ORDER, ReactorFeed
from process_sim.reactor.core.thermodynamics import (
    reaction_enthalpy_kj_per_kmol,
    standard_reaction_enthalpy_kj_per_kmol,
)
from process_sim.reactor.types.staged_adiabatic_radial import (
    StagedAdiabaticRadialFlowModel,
)
from process_sim.reactor.types.staged_adiabatic_pfr import StagedAdiabaticPfrModel
from process_sim.plant.summary import (
    format_pfr_reactor_report,
    format_radial_reactor_report,
)


def make_test_feed() -> ReactorFeed:
    return ReactorFeed(
        eb=605.9,
        steam=3029.5,
        styrene=0.0606,
        hydrogen=0.0,
        benzene=0.0606,
        toluene=0.0606,
        co2=0.0,
        ethylene=0.0,
        methane=0.0,
        co=0.0,
    )


def make_test_pfr_case() -> ReactorCase:
    return ReactorCase(
        feed=make_test_feed(),
        conditions=ReactorRunConditions(
            pressure_kpa=200.0,
            stage_inlet_temperatures_c=(550.0, 550.0, 550.0),
            inlet_superficial_velocity_m_per_s=2.0,
            stage_ld_ratios=(3.0, 3.0, 3.0),
            pellet_diameter_m=0.003,
            bed_void_fraction=0.4312,
            catalyst_bulk_density_kg_m3=1422.0,
            ergun_a=1.75,
            ergun_b=150.0,
            gas_viscosity_pa_s=4.0e-5,
            interstage_reheater_pressure_drop_pa=20_000.0,
            segments_per_stage=300,
            profile_points_per_stage=6,
        ),
    )


def make_test_radial_case() -> RadialReactorCase:
    return RadialReactorCase(
        feed=make_test_feed(),
        conditions=RadialReactorRunConditions(
            inlet_pressure_pa=200_000.0,
            stage_inlet_temperatures_k=(823.15, 823.15, 823.15),
            inlet_superficial_velocity_m_per_s=2.0,
            center_channel_radius_m=1.0,
            bed_height_m=6.0,
            bed_thicknesses_m=(0.45, 0.9, 0.9),
            pellet_diameter_m=0.003,
            bed_void_fraction=0.4312,
            catalyst_bulk_density_kg_m3=1422.0,
            ergun_a=1.75,
            ergun_b=150.0,
            gas_viscosity_pa_s=4.0e-5,
            interstage_reheater_pressure_drop_pa=20_000.0,
            segments_per_stage=12000,
            profile_points_per_stage=12,
        ),
    )


@pytest.mark.parametrize(
    ("model", "case"),
    [
        (StagedAdiabaticPfrModel(), make_test_pfr_case()),
        (StagedAdiabaticRadialFlowModel(), make_test_radial_case()),
    ],
)
def test_numba_reactor_core_matches_python_path(
    model: StagedAdiabaticPfrModel | StagedAdiabaticRadialFlowModel,
    case: ReactorCase | RadialReactorCase,
) -> None:
    original = config.USE_NUMBA_REACTOR_CORE
    case = replace(case, conditions=replace(case.conditions, segments_per_stage=100))
    try:
        config.USE_NUMBA_REACTOR_CORE = False
        python_result = model.run(feed=case.feed, conditions=case.conditions)
        config.USE_NUMBA_REACTOR_CORE = True
        numba_result = model.run(feed=case.feed, conditions=case.conditions)
    finally:
        config.USE_NUMBA_REACTOR_CORE = original

    assert numba_result.outlet.pressure_kpa == pytest.approx(
        python_result.outlet.pressure_kpa
    )
    assert numba_result.outlet.temperature_c == pytest.approx(
        python_result.outlet.temperature_c
    )
    assert numba_result.eb_conversion == pytest.approx(python_result.eb_conversion)
    assert numba_result.styrene_selectivity == pytest.approx(
        python_result.styrene_selectivity
    )
    assert numba_result.log.carbon_balance_error_fraction == pytest.approx(
        python_result.log.carbon_balance_error_fraction
    )
    assert numba_result.log.hydrogen_balance_error_fraction == pytest.approx(
        python_result.log.hydrogen_balance_error_fraction
    )


def test_physical_properties_match_documented_values() -> None:
    eb = SPECIES_PHYSICAL_PROPERTIES["eb"]
    benzene = SPECIES_PHYSICAL_PROPERTIES["benzene"]

    assert eb.molecular_weight == pytest.approx(106.168)
    assert eb.heat_of_formation_kj_per_kmol == pytest.approx(29_800.0)
    assert eb.heat_capacity.b == pytest.approx(7.072e-1)
    assert benzene.heat_capacity.b == pytest.approx(4.744e-1)


def test_standard_reaction_enthalpies_are_calculated_from_formation_enthalpies() -> (
    None
):
    expected_kj_per_kmol = {
        "r1": 117_700.0,
        "r2": 105_500.0,
        "r3": -54_700.0,
        "r4": 210_500.0,
        "r5": 206_300.0,
        "r6": -41_200.0,
    }

    actual = {
        reaction.reaction_id: standard_reaction_enthalpy_kj_per_kmol(
            reaction=reaction,
            properties=SPECIES_PHYSICAL_PROPERTIES,
            universal=UNIVERSAL_CONSTANTS,
        )
        for reaction in STYRENE_SIX_REACTION_NETWORK.reactions
    }

    assert actual == pytest.approx(expected_kj_per_kmol)


def test_temperature_dependent_reaction_enthalpy_uses_heat_capacity_integral() -> None:
    reaction = STYRENE_SIX_REACTION_NETWORK.reactions[0]

    standard = standard_reaction_enthalpy_kj_per_kmol(
        reaction=reaction,
        properties=SPECIES_PHYSICAL_PROPERTIES,
        universal=UNIVERSAL_CONSTANTS,
    )
    at_high_temperature = reaction_enthalpy_kj_per_kmol(
        reaction=reaction,
        temperature_k=850.0,
        properties=SPECIES_PHYSICAL_PROPERTIES,
        universal=UNIVERSAL_CONSTANTS,
    )

    assert at_high_temperature != pytest.approx(standard)


def test_six_reaction_network_produces_all_rates_and_net_reversible_rate() -> None:
    partial_pressures_pa = {
        "eb": 30_000.0,
        "steam": 70_000.0,
        "styrene": 2_000.0,
        "hydrogen": 3_000.0,
        "benzene": 500.0,
        "toluene": 500.0,
        "co2": 500.0,
        "ethylene": 500.0,
        "methane": 500.0,
        "co": 500.0,
    }

    rates = reaction_rates(
        network=STYRENE_SIX_REACTION_NETWORK,
        temperature_k=850.0,
        partial_pressures_pa=partial_pressures_pa,
        universal=UNIVERSAL_CONSTANTS,
    )

    assert [rate.reaction_id for rate in rates] == ["r1", "r2", "r3", "r4", "r5", "r6"]
    assert rates[0].rate_kmol_per_s_m3 > 0.0


def test_adiabatic_balance_returns_component_and_temperature_derivatives() -> None:
    case = make_test_pfr_case()
    state_vector = case.feed.to_vector_kmol_s() + [
        case.conditions.stage_inlet_temperatures_c[0] + 273.15,
        case.conditions.pressure_kpa * UNIVERSAL_CONSTANTS.pa_per_kpa,
    ]
    context = ReactorBalanceContext(
        cross_section_area_m2=1.0,
        network=STYRENE_SIX_REACTION_NETWORK,
        properties=SPECIES_PHYSICAL_PROPERTIES,
        universal=UNIVERSAL_CONSTANTS,
        ergun_parameters=ErgunParameters(
            pellet_diameter_m=case.conditions.pellet_diameter_m,
            bed_void_fraction=case.conditions.bed_void_fraction,
            catalyst_bulk_density_kg_m3=case.conditions.catalyst_bulk_density_kg_m3,
            ergun_a=case.conditions.ergun_a,
            ergun_b=case.conditions.ergun_b,
            gas_viscosity_pa_s=case.conditions.gas_viscosity_pa_s,
        ),
    )

    derivatives = pfr_adiabatic_derivatives(state_vector=state_vector, context=context)

    assert len(derivatives) == len(COMPONENT_ORDER) + 2
    assert any(abs(value) > 0.0 for value in derivatives[:-1])


def test_staged_adiabatic_reactor_produces_stage_logs() -> None:
    model = StagedAdiabaticPfrModel()
    case = make_test_pfr_case()

    result = model.run(feed=case.feed, conditions=case.conditions)

    assert len(result.log.stage_logs) == 3
    assert len(result.log.profile) > 3
    assert result.log.cross_section_area_m2 > 0.0
    assert result.log.total_catalyst_volume_m3 is not None
    assert result.log.total_catalyst_volume_m3 > 0.0
    assert result.outlet.pressure_kpa < case.conditions.pressure_kpa
    assert result.log.reheat_pressure_drop_kpa == pytest.approx(40.0)


def test_pfr_pressure_positive_check_uses_unclipped_pressure() -> None:
    model = StagedAdiabaticPfrModel()
    case = make_test_pfr_case()
    conditions = ReactorRunConditions(
        pressure_kpa=50.0,
        stage_inlet_temperatures_c=(550.0, 550.0),
        inlet_superficial_velocity_m_per_s=2.0,
        stage_ld_ratios=(4.0, 4.0),
        pellet_diameter_m=case.conditions.pellet_diameter_m,
        bed_void_fraction=case.conditions.bed_void_fraction,
        catalyst_bulk_density_kg_m3=case.conditions.catalyst_bulk_density_kg_m3,
        ergun_a=case.conditions.ergun_a,
        ergun_b=case.conditions.ergun_b,
        gas_viscosity_pa_s=case.conditions.gas_viscosity_pa_s,
        interstage_reheater_pressure_drop_pa=0.0,
        segments_per_stage=50,
        profile_points_per_stage=5,
    )

    result = model.run(feed=case.feed, conditions=conditions)

    assert result.outlet.pressure_kpa > 0.0
    assert result.log.stage_logs[0].pressure_positive_ok is False
    assert result.log.pressure_positive_ok is False


def test_radial_reactor_produces_pressure_and_atom_balance_logs() -> None:
    model = StagedAdiabaticRadialFlowModel()
    case = make_test_radial_case()

    result = model.run(feed=case.feed, conditions=case.conditions)

    assert len(result.log.stage_logs) == 3
    assert result.outlet.pressure_kpa > 30.0
    assert result.log.reactor_pressure_drop_kpa is not None
    assert result.log.reheat_pressure_drop_kpa == pytest.approx(40.0)
    assert result.log.carbon_balance_error_fraction is not None
    assert result.log.hydrogen_balance_error_fraction is not None
    assert result.log.carbon_balance_error_fraction < 1e-6
    assert result.log.hydrogen_balance_error_fraction < 1e-6
    assert result.log.max_re_over_one_minus_void is not None


def test_reactor_result_remains_non_negative() -> None:
    model = StagedAdiabaticPfrModel()
    case = make_test_pfr_case()

    result = model.run(feed=case.feed, conditions=case.conditions)
    outlet = result.outlet.stream

    for flow in outlet.to_component_flows_kmol_h().values():
        assert flow >= 0.0


def test_reactor_stage_logs_include_temperature_change_and_reheat_duty() -> None:
    model = StagedAdiabaticPfrModel()
    case = make_test_pfr_case()

    result = model.run(feed=case.feed, conditions=case.conditions)

    for stage_log in result.log.stage_logs:
        assert stage_log.stage_length_m > 0.0
        assert stage_log.inlet_pressure_kpa is not None
        assert stage_log.outlet_pressure_kpa is not None
    assert any(
        stage_log.outlet_temperature_c != pytest.approx(stage_log.inlet_temperature_c)
        for stage_log in result.log.stage_logs
    )
    assert result.log.stage_logs[0].reheat_duty_mw is not None
    assert result.log.stage_logs[1].reheat_duty_mw is not None
    assert result.log.stage_logs[2].reheat_duty_mw is None


def test_pfr_reactor_report_contains_design_sections() -> None:
    model = StagedAdiabaticPfrModel()
    case = make_test_pfr_case()

    result = model.run(feed=case.feed, conditions=case.conditions)
    report = format_pfr_reactor_report(feed=case.feed, result=result)

    assert "[PFR Reactor Summary]" in report
    assert "[Feed]" in report
    assert "[Overall]" in report
    assert "[Stage Summary]" in report
    assert "[Stage Outlet Molar Flows, kmol/h]" in report
    assert "cross section area" in report
    assert "equivalent diameter" in report
    assert "atom balance:" in report
    assert "constraints:" in report
    assert "profile velocity 1-3 m/s" in report
    assert "stage length <= 10 m" in report


def test_radial_reactor_report_contains_design_sections() -> None:
    model = StagedAdiabaticRadialFlowModel()
    case = make_test_radial_case()

    result = model.run(feed=case.feed, conditions=case.conditions)
    report = format_radial_reactor_report(feed=case.feed, result=result)

    assert "[Radial Reactor Summary]" in report
    assert "[Feed]" in report
    assert "[Overall]" in report
    assert "[Stage Summary]" in report
    assert "[Stage Outlet Molar Flows, kmol/h]" in report
    assert "atom balance:" in report
    assert "constraints:" in report
    assert "bed outlet velocity >= 1 m/s" in report
    assert "reheat pressure drop" in report
