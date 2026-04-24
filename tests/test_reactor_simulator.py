from process_sim.constants import DEFAULT_REACTOR_CONFIG
from process_sim.cli import build_default_input, format_reactor_report
from process_sim.reactor.models import ReactorFeed, ReactorRunConditions
from process_sim.reactor.simulator import StyreneReactorModel


def build_reference_conditions() -> ReactorRunConditions:
    operation = DEFAULT_REACTOR_CONFIG.operation
    return ReactorRunConditions(
        pressure_kpa=operation.pressure_kpa,
        stage_inlet_temperatures_c=operation.stage_inlet_temperatures_c,
        stage_lengths_m=operation.stage_lengths_m,
        inlet_superficial_velocity_m_per_s=operation.inlet_superficial_velocity_m_per_s,
        segments_per_stage=operation.segments_per_stage,
        profile_points_per_stage=operation.profile_points_per_stage,
    )


def build_reference_feed() -> ReactorFeed:
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


def test_three_stage_adiabatic_reactor_produces_stage_logs() -> None:
    model = StyreneReactorModel(config=DEFAULT_REACTOR_CONFIG)

    result = model.run(feed=build_reference_feed(), conditions=build_reference_conditions())

    assert len(result.log.stage_logs) == 3
    assert len(result.log.profile) > 3
    assert result.log.cross_section_area_m2 > 0.0


def test_temperature_drops_inside_each_adiabatic_stage() -> None:
    model = StyreneReactorModel(config=DEFAULT_REACTOR_CONFIG)

    result = model.run(feed=build_reference_feed(), conditions=build_reference_conditions())

    for stage_log in result.log.stage_logs:
        assert stage_log.outlet_temperature_c < stage_log.inlet_temperature_c
        assert stage_log.stage_length_m > 0.0


def test_reactor_result_remains_non_negative() -> None:
    model = StyreneReactorModel(config=DEFAULT_REACTOR_CONFIG)

    result = model.run(feed=build_reference_feed(), conditions=build_reference_conditions())
    outlet = result.outlet.stream

    assert outlet.eb >= 0.0
    assert outlet.steam >= 0.0
    assert outlet.styrene >= 0.0
    assert outlet.hydrogen >= 0.0
    assert outlet.benzene >= 0.0
    assert outlet.toluene >= 0.0
    assert outlet.co2 >= 0.0
    assert outlet.ethylene >= 0.0
    assert outlet.methane >= 0.0
    assert outlet.co >= 0.0


def test_human_readable_report_contains_expected_sections() -> None:
    model = StyreneReactorModel(config=DEFAULT_REACTOR_CONFIG)

    result = model.run(feed=build_reference_feed(), conditions=build_reference_conditions())
    report = format_reactor_report(result=result, payload=build_default_input())

    assert "反応器ログ" in report
    assert "入口条件 feed" in report
    assert "全体サマリー" in report
    assert "出口流量" in report
    assert "入口から出口までの差分" in report
    assert "各段ログ" in report
    assert "第1段" in report
    assert "第2段" in report
    assert "第3段" in report
