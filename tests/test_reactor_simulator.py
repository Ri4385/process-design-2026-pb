import pytest

from process_sim.constants.physical_properties import SPECIES_PHYSICAL_PROPERTIES
from process_sim.constants.reaction_networks import STYRENE_SIX_REACTION_NETWORK
from process_sim.constants.universal import UNIVERSAL_CONSTANTS
from process_sim.reactor.cases.styrene_radial_default import DEFAULT_STYRENE_RADIAL_REACTOR_CASE
from process_sim.reactor.cases.styrene_default import DEFAULT_STYRENE_REACTOR_CASE
from process_sim.reactor.core.balance import ReactorBalanceContext, pfr_adiabatic_derivatives
from process_sim.reactor.core.reaction import reaction_rates
from process_sim.reactor.core.stream import COMPONENT_ORDER
from process_sim.reactor.core.thermodynamics import reaction_enthalpy_kj_per_kmol, standard_reaction_enthalpy_kj_per_kmol
from process_sim.reactor.types.staged_adiabatic_radial import StagedAdiabaticRadialFlowModel
from process_sim.reactor.types.staged_adiabatic_pfr import StagedAdiabaticPfrModel
from process_sim.cli import default_case_payload, format_reactor_report
from process_sim.plant.summary import format_radial_reactor_report


def test_physical_properties_match_documented_values() -> None:
    eb = SPECIES_PHYSICAL_PROPERTIES["eb"]
    benzene = SPECIES_PHYSICAL_PROPERTIES["benzene"]

    assert eb.molecular_weight == pytest.approx(106.168)
    assert eb.heat_of_formation_kj_per_kmol == pytest.approx(29_800.0)
    assert eb.heat_capacity.b == pytest.approx(7.072e-1)
    assert benzene.heat_capacity.b == pytest.approx(4.744e-1)


def test_standard_reaction_enthalpies_are_calculated_from_formation_enthalpies() -> None:
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
    case = DEFAULT_STYRENE_REACTOR_CASE
    state_vector = case.feed.to_vector_kmol_s() + [case.conditions.stage_inlet_temperatures_c[0] + 273.15]
    context = ReactorBalanceContext(
        pressure_kpa=case.conditions.pressure_kpa,
        cross_section_area_m2=1.0,
        network=STYRENE_SIX_REACTION_NETWORK,
        properties=SPECIES_PHYSICAL_PROPERTIES,
        universal=UNIVERSAL_CONSTANTS,
    )

    derivatives = pfr_adiabatic_derivatives(state_vector=state_vector, context=context)

    assert len(derivatives) == len(COMPONENT_ORDER) + 1
    assert any(abs(value) > 0.0 for value in derivatives[:-1])


def test_staged_adiabatic_reactor_produces_stage_logs() -> None:
    model = StagedAdiabaticPfrModel()
    case = DEFAULT_STYRENE_REACTOR_CASE

    result = model.run(feed=case.feed, conditions=case.conditions)

    assert len(result.log.stage_logs) == 3
    assert len(result.log.profile) > 3
    assert result.log.cross_section_area_m2 > 0.0


def test_radial_reactor_produces_pressure_and_atom_balance_logs() -> None:
    model = StagedAdiabaticRadialFlowModel()
    case = DEFAULT_STYRENE_RADIAL_REACTOR_CASE

    result = model.run(feed=case.feed, conditions=case.conditions)

    assert len(result.log.stage_logs) == 3
    assert result.outlet.pressure_kpa > 30.0
    assert result.log.reactor_pressure_drop_kpa is not None
    assert result.log.reheat_pressure_drop_kpa == pytest.approx(40.0)
    assert result.log.atom_balance_ok is True
    assert result.log.max_re_over_one_minus_void is not None


def test_reactor_result_remains_non_negative() -> None:
    model = StagedAdiabaticPfrModel()
    case = DEFAULT_STYRENE_REACTOR_CASE

    result = model.run(feed=case.feed, conditions=case.conditions)
    outlet = result.outlet.stream

    for flow in outlet.to_component_flows_kmol_h().values():
        assert flow >= 0.0


def test_reactor_stage_logs_include_temperature_change_and_reheat_duty() -> None:
    model = StagedAdiabaticPfrModel()
    case = DEFAULT_STYRENE_REACTOR_CASE

    result = model.run(feed=case.feed, conditions=case.conditions)

    for stage_log in result.log.stage_logs:
        assert stage_log.stage_length_m > 0.0
        assert stage_log.outlet_temperature_c != pytest.approx(stage_log.inlet_temperature_c)
    assert result.log.stage_logs[0].reheat_duty_mw is not None
    assert result.log.stage_logs[1].reheat_duty_mw is not None
    assert result.log.stage_logs[2].reheat_duty_mw is None


def test_human_readable_report_contains_expected_sections() -> None:
    model = StagedAdiabaticPfrModel()
    case = DEFAULT_STYRENE_REACTOR_CASE

    result = model.run(feed=case.feed, conditions=case.conditions)
    report = format_reactor_report(result=result, payload=default_case_payload("pfr"))

    assert "反応器ログ" in report
    assert "入口条件 feed" in report
    assert "全体サマリー" in report
    assert "出口流量" in report
    assert "入口から出口までの差分" in report
    assert "各段ログ" in report
    assert "第1段" in report
    assert "第2段" in report
    assert "第3段" in report


def test_radial_reactor_report_contains_design_sections() -> None:
    model = StagedAdiabaticRadialFlowModel()
    case = DEFAULT_STYRENE_RADIAL_REACTOR_CASE

    result = model.run(feed=case.feed, conditions=case.conditions)
    report = format_radial_reactor_report(feed=case.feed, result=result)

    assert "[Radial Reactor Summary]" in report
    assert "[Feed]" in report
    assert "[Overall]" in report
    assert "[Stage Summary]" in report
    assert "[Stage Outlet Molar Flows, kmol/h]" in report
    assert "atom balance:" in report
    assert "constraints:" in report
    assert "reheat pressure drop" in report
