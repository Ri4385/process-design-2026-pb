from pathlib import Path

import pytest

from process_sim.plant.convergence import PlantFeedPlan, run_plant_convergence
from process_sim.plant.feed import FreshFeed
from process_sim.plant.models import PlantRunRecord, PlantStreamRecord
from process_sim.reactor.cases.styrene_default import ReactorCase
from process_sim.reactor.core.stream import ReactorFeed


def stream_record(name: str, component_flows: dict[str, float]) -> PlantStreamRecord:
    total = sum(component_flows.values())
    fractions = {
        component: flow / total
        for component, flow in component_flows.items()
    } if total > 0.0 else {}
    return PlantStreamRecord(
        name=name,
        temperature_c=None,
        pressure_kpa=None,
        total_molar_flow_kmol_h=total,
        component_molar_flow_kmol_h=component_flows,
        component_molar_fraction=fractions,
    )


def test_plant_convergence_uses_startup_feed_then_previous_recycle_output() -> None:
    feeds: list[ReactorFeed] = []

    def fake_runner(reactor_case: ReactorCase) -> PlantRunRecord:
        feeds.append(reactor_case.feed)
        return PlantRunRecord(
            case_path=Path("fake.hsc"),
            reactor_outlet_temperature_c=0.0,
            reactor_outlet_pressure_kpa=0.0,
            streams={
                "sm_product": stream_record("sm_product", {"Styrene": 1.0}),
                "eb_recycle": stream_record("eb_recycle", {"E-Benzene": 200.0}),
                "water_recycle": stream_record("water_recycle", {"H2O": 2300.0}),
            },
            metadata={},
        )

    feed_plan = PlantFeedPlan(
        startup_reactor_feed=ReactorFeed(eb=480.0, steam=2370.0),
        steady_fresh_feed=FreshFeed(hydrocarbon_kmol_h=265.0 / 0.995, steam_kmol_h=28.0),
    )

    result = run_plant_convergence(feed_plan=feed_plan, plant_runner=fake_runner)

    assert result.converged
    assert len(result.iterations) == 2
    assert feeds[0].eb == pytest.approx(480.0)
    assert feeds[0].steam == pytest.approx(2370.0)
    assert feeds[1].eb == pytest.approx(465.0)
    assert feeds[1].steam == pytest.approx(2328.0)
    assert result.final_iteration.sm_product_kmol_h == pytest.approx(1.0)
