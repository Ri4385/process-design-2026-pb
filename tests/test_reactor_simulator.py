from process_sim.constants import DEFAULT_REACTOR_CONFIG
from process_sim.reactor.models import ReactorFeed, ReactorRunConditions
from process_sim.reactor.simulator import StyreneReactorModel


def test_reversible_primary_reaction_allows_reverse_progress() -> None:
    model = StyreneReactorModel(config=DEFAULT_REACTOR_CONFIG)
    feed = ReactorFeed(
        eb=0.0,
        steam=1.0,
        styrene=10.0,
        hydrogen=10.0,
    )
    conditions = ReactorRunConditions(
        pressure_kpa=DEFAULT_REACTOR_CONFIG.operation.pressure_kpa,
        temperature_c=DEFAULT_REACTOR_CONFIG.operation.temperature_c,
        reactor_volume_m3=1.0,
        steps=20,
    )

    result = model.run(feed=feed, conditions=conditions)

    assert result.outlet.eb > feed.eb
    assert result.outlet.styrene < feed.styrene
    assert result.outlet.hydrogen < feed.hydrogen


def test_reactor_state_remains_non_negative_during_reverse_progress() -> None:
    model = StyreneReactorModel(config=DEFAULT_REACTOR_CONFIG)
    feed = ReactorFeed(
        eb=0.0,
        steam=1.0,
        styrene=1.0e-6,
        hydrogen=1.0e-6,
    )
    conditions = ReactorRunConditions(
        pressure_kpa=DEFAULT_REACTOR_CONFIG.operation.pressure_kpa,
        temperature_c=DEFAULT_REACTOR_CONFIG.operation.temperature_c,
        reactor_volume_m3=10.0,
        steps=1,
    )

    result = model.run(feed=feed, conditions=conditions)

    assert result.outlet.eb >= 0.0
    assert result.outlet.steam >= 0.0
    assert result.outlet.styrene >= 0.0
    assert result.outlet.hydrogen >= 0.0
    assert result.outlet.benzene >= 0.0
    assert result.outlet.toluene >= 0.0
    assert result.outlet.co2 >= 0.0
