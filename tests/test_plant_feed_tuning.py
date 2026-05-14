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
    DEFAULT_TARGET_SM_KMOL_H,
    FeedTuningOptions,
    build_initial_feed_guess,
    is_converged,
    is_valid_recycle_stream,
    limited_feed_step,
    tune_fresh_feed_fast,
)
from process_sim.reactor.cases.styrene_default import ReactorCase


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
    guess = build_initial_feed_guess(target_sm_kmol_h=DEFAULT_TARGET_SM_KMOL_H)

    assert DEFAULT_TARGET_SM_KMOL_H == pytest.approx(240.033)
    assert guess.reactor_inlet_eb_kmol_h == pytest.approx(480.066)
    assert guess.unreacted_eb_kmol_h == pytest.approx(240.033)
    assert guess.recycle_eb_kmol_h == pytest.approx(237.63267)
    assert guess.fresh_eb_kmol_h == pytest.approx(242.43333)
    assert guess.reactor_inlet_h2o_kmol_h == pytest.approx(2400.33)
    assert guess.recycle_h2o_kmol_h == pytest.approx(2376.3267)
    assert guess.fresh_h2o_kmol_h == pytest.approx(24.0033)
    assert guess.reactor_feed.eb == pytest.approx(480.066)
    assert guess.reactor_feed.steam == pytest.approx(2400.33)


def test_fast_feed_tuning_uses_initial_guess_without_secant_update() -> None:
    reactor_eb_values: list[float] = []

    def fake_runner(reactor_case: ReactorCase) -> PlantRunRecord:
        reactor_eb_values.append(reactor_case.feed.eb)
        sm_flow = reactor_case.feed.eb * 0.5
        return PlantRunRecord(
            case_path=Path("fake.hsc"),
            reactor_outlet_temperature_c=0.0,
            reactor_outlet_pressure_kpa=0.0,
            streams={
                "reactor_outlet": stream_record("reactor_outlet", {"E-Benzene": 240.033, "H2O": 2400.33}),
                "sm_product": stream_record("sm_product", {"Styrene": sm_flow}),
                "eb_recycle": stream_record("eb_recycle", {"E-Benzene": 237.63267}),
                "water_recycle": stream_record("water_recycle", {"H2O": 2376.3267}),
            },
            metadata={},
        )

    result = tune_fresh_feed_fast(
        options=FeedTuningOptions(
            target_sm_kmol_h=DEFAULT_TARGET_SM_KMOL_H,
            max_runs=2,
            sm_tolerance_kmol_h=1e-6,
        ),
        plant_runner=fake_runner,
    )

    assert result.converged
    assert len(result.runs) == 1
    assert reactor_eb_values == pytest.approx([480.066])
    assert result.best_run.sm_product_kmol_h == pytest.approx(240.033)
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
    assert "--hidden" in command
    assert captured["timeout"] == pytest.approx(12.5)
    assert captured["check"] is False
