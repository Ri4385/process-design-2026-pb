from pathlib import Path

import pytest

from process_sim.plant.feed import (
    FreshFeed,
    FreshFeedPolicy,
    build_reactor_feed,
    reactor_feed_from_plant_stream,
)
from process_sim.plant.models import PlantRunRecord, PlantStreamRecord
from process_sim.plant.runner import run_plant_once_with_subprocess_timeout
from process_sim.plant.production_target import (
    FeedTuningOptions,
    InitialRecycleGuessPolicy,
    build_initial_feed_guess,
    is_converged,
    is_valid_recycle_stream,
    limited_feed_step,
    tune_fresh_feed_fast,
)
from process_sim.reactor.cases.styrene_default import ReactorCase
from process_sim.reactor.core.models import ReactorRunConditions
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


def reactor_case(feed: ReactorFeed) -> ReactorCase:
    return ReactorCase(
        feed=feed,
        conditions=ReactorRunConditions(
            pressure_kpa=200.0,
            stage_inlet_temperatures_c=(550.0,),
            stage_lengths_m=(1.0,),
            total_catalyst_volume_m3=1.0,
            pellet_diameter_m=0.003,
            bed_void_fraction=0.4,
            catalyst_bulk_density_kg_m3=1400.0,
            ergun_a=1.75,
            ergun_b=150.0,
            gas_viscosity_pa_s=4.0e-5,
            interstage_reheater_pressure_drop_pa=0.0,
            segments_per_stage=10,
            profile_points_per_stage=3,
        ),
    )


def test_recycle_stream_is_mapped_to_reactor_feed_components() -> None:
    stream = stream_record(
        name="eb_recycle",
        component_flows={
            "E-Benzene": 10.0,
            "Styrene": 1.5,
            "H2O": 2.0,
            "Benzene": 0.5,
        },
    )

    feed = reactor_feed_from_plant_stream(stream)

    assert feed.eb == pytest.approx(10.0)
    assert feed.styrene == pytest.approx(1.5)
    assert feed.steam == pytest.approx(2.0)
    assert feed.benzene == pytest.approx(0.5)


def test_build_reactor_feed_adds_fresh_feed_and_recycles() -> None:
    policy = FreshFeedPolicy(eb_mol_fraction=0.9, benzene_mol_fraction=0.1, steam_to_fresh_eb_ratio=4.0)
    fresh = FreshFeed(hydrocarbon_kmol_h=100.0, steam_kmol_h=360.0)
    eb_recycle = reactor_feed_from_plant_stream(stream_record("eb_recycle", {"E-Benzene": 20.0}))
    water_recycle = reactor_feed_from_plant_stream(stream_record("water_recycle", {"H2O": 30.0}))

    feed = build_reactor_feed(
        fresh_feed=fresh,
        eb_recycle=eb_recycle,
        water_recycle=water_recycle,
        policy=policy,
    )

    assert feed.eb == pytest.approx(110.0)
    assert feed.benzene == pytest.approx(10.0)
    assert feed.steam == pytest.approx(390.0)


def test_limited_feed_step_clamps_secant_prediction() -> None:
    assert limited_feed_step(
        current_feed_kmol_h=100.0,
        predicted_feed_kmol_h=200.0,
        max_step_fraction=0.3,
    ) == pytest.approx(130.0)
    assert limited_feed_step(
        current_feed_kmol_h=100.0,
        predicted_feed_kmol_h=50.0,
        max_step_fraction=0.3,
    ) == pytest.approx(70.0)


def test_initial_feed_guess_is_calculated_from_target_and_recycle_fractions() -> None:
    guess_policy = InitialRecycleGuessPolicy(
        single_pass_sm_yield_from_eb=0.5,
        eb_recycle_fraction=0.8,
        h2o_recycle_fraction=0.9,
        steam_to_eb_ratio=4.0,
    )

    guess = build_initial_feed_guess(target_sm_kmol_h=100.0, guess_policy=guess_policy)

    assert guess.reactor_inlet_eb_kmol_h > 0.0
    assert guess.reactor_inlet_h2o_kmol_h == pytest.approx(guess.reactor_inlet_eb_kmol_h * 4.0)
    assert guess.fresh_eb_kmol_h + guess.recycle_eb_kmol_h == pytest.approx(guess.reactor_inlet_eb_kmol_h)
    assert guess.recycle_eb_kmol_h == pytest.approx(guess.unreacted_eb_kmol_h * 0.8)
    assert guess.fresh_h2o_kmol_h + guess.recycle_h2o_kmol_h == pytest.approx(guess.reactor_inlet_h2o_kmol_h)
    assert guess.recycle_h2o_kmol_h == pytest.approx(guess.reactor_inlet_h2o_kmol_h * 0.9)
    assert guess.reactor_feed.eb == pytest.approx(guess.reactor_inlet_eb_kmol_h)
    assert guess.reactor_feed.steam == pytest.approx(guess.reactor_inlet_h2o_kmol_h)


def test_fast_feed_tuning_uses_initial_guess_without_secant_update() -> None:
    reactor_eb_values: list[float] = []

    def fake_runner(reactor_case: ReactorCase) -> PlantRunRecord:
        reactor_eb_values.append(reactor_case.feed.eb)
        return PlantRunRecord(
            case_path=Path("fake.hsc"),
            reactor_outlet_temperature_c=0.0,
            reactor_outlet_pressure_kpa=0.0,
            streams={
                "reactor_outlet": stream_record(
                    "reactor_outlet",
                    {"E-Benzene": reactor_case.feed.eb * 0.5, "H2O": reactor_case.feed.steam},
                ),
                "sm_product": stream_record(
                    "sm_product",
                    {
                        "Styrene": 100.0,
                        "Benzene": 0.1,
                    },
                ),
                "eb_recycle": stream_record("eb_recycle", {"E-Benzene": reactor_case.feed.eb * 0.5}),
                "water_recycle": stream_record("water_recycle", {"H2O": reactor_case.feed.steam}),
            },
            metadata={},
        )

    result = tune_fresh_feed_fast(
        options=FeedTuningOptions(
            target_sm_kmol_h=100.0,
            max_runs=2,
            min_runs=1,
            sm_tolerance_kmol_h=1.0,
            eb_recycle_tolerance_kmol_h=1.0e9,
            h2o_recycle_tolerance_kmol_h=1.0e9,
        ),
        base_reactor_case=reactor_case(ReactorFeed(eb=1.0, steam=1.0)),
        plant_runner=fake_runner,
        reactor_model="pfr",
    )

    assert result.converged
    assert len(result.runs) == 1
    assert reactor_eb_values[0] > 0.0
    assert result.best_run.sm_product_kmol_h == pytest.approx(100.1)
    assert FeedTuningOptions().sm_tolerance_kmol_h == pytest.approx(0.1)
    assert FeedTuningOptions().eb_recycle_tolerance_kmol_h == pytest.approx(0.1)
    assert FeedTuningOptions().h2o_recycle_tolerance_kmol_h == pytest.approx(0.1)


def test_invalid_recycle_stream_is_rejected() -> None:
    assert not is_valid_recycle_stream(None, "E-Benzene")
    assert not is_valid_recycle_stream(stream_record("eb_recycle", {"E-Benzene": -32767.0}), "E-Benzene")
    assert not is_valid_recycle_stream(stream_record("eb_recycle", {"E-Benzene": -1.0}), "E-Benzene")
    assert not is_valid_recycle_stream(stream_record("eb_recycle", {"Styrene": 1.0}), "E-Benzene")
    assert is_valid_recycle_stream(stream_record("eb_recycle", {"E-Benzene": 1.0}), "E-Benzene")


def test_feed_tuning_sm_margin_allows_tiny_float_error() -> None:
    assert is_converged(
        sm_margin_kmol_h=-1e-12,
        eb_recycle_error_kmol_h=0.0,
        h2o_recycle_error_kmol_h=0.0,
        options=FeedTuningOptions(),
    )


def test_plant_runner_subprocess_receives_case_path_and_hidden_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], timeout: float, check: bool) -> object:
        captured["command"] = command
        captured["timeout"] = timeout
        captured["check"] = check

        class Completed:
            returncode = 0

        return Completed()

    monkeypatch.setattr("process_sim.plant.runner.subprocess.run", fake_run)

    run_plant_once_with_subprocess_timeout(
        case_path=Path("data/hysys/custom.hsc"),
        hysys_visible=False,
        timeout_seconds=12.5,
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--case-path" in command
    assert str(Path("data/hysys/custom.hsc")) in command
    assert "--reactor-model" in command
    assert "radial" in command
    assert "--hidden" in command
    assert captured["timeout"] == pytest.approx(12.5)
    assert captured["check"] is False
