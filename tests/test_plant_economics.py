"""Plant 経済計算のテスト。"""

from __future__ import annotations

import math

import pytest

from process_sim.plant.economics import (
    VALUABLE_COMPONENT_PRICE_YEN_PER_KG,
    component_loss_cost_yen_per_year,
    cooling_utility_cost_yen_per_year,
    cooling_water_cost_yen_per_year,
    cooler_capital_cost_yen,
    decanter_capital_cost_yen,
    heat_exchanger_area_m2,
    log_mean_temperature_difference_k,
    steam_heating_cost_yen_per_year,
)


def test_cooling_utility_cost_yen_per_year() -> None:
    """冷却用役費を計算できる。"""
    assert cooling_utility_cost_yen_per_year(
        duty_kw=-100.0,
        refrigerant_yen_per_mj=0.8,
        hours_per_year=8000.0,
    ) == pytest.approx(2_304_000.0)


def test_cooling_water_cost_yen_per_year() -> None:
    """冷却水費を計算できる。"""
    assert cooling_water_cost_yen_per_year(
        duty_kw=41.84,
        cp_water_kj_kg_k=4.184,
        cooling_water_delta_t_k=10.0,
        cooling_water_yen_per_ton=10.0,
        hours_per_year=8000.0,
    ) == pytest.approx(288_000.0)


def test_steam_heating_cost_yen_per_year() -> None:
    """スチーム加熱費を計算できる。"""
    assert steam_heating_cost_yen_per_year(
        duty_kw=100.0,
        steam_yen_per_mj=1.0,
        hours_per_year=8000.0,
    ) == pytest.approx(2_880_000.0)


def test_component_loss_cost_yen_per_year() -> None:
    """有価成分流出損失を計算できる。"""
    result = component_loss_cost_yen_per_year(
        component_flow_kmol_h={
            "eb": 1.0,
            "styrene": 2.0,
            "benzene": 3.0,
            "toluene": 4.0,
        },
        price_yen_per_kg=VALUABLE_COMPONENT_PRICE_YEN_PER_KG,
        hours_per_year=10.0,
    )
    expected = 10.0 * (
        1.0 * 106.168 * 198.63
        + 2.0 * 104.152 * 232.231
        + 3.0 * 78.114 * 149.269
        + 4.0 * 92.141 * 184.07
    )
    assert result == pytest.approx(expected)


def test_equipment_costs_are_positive() -> None:
    """装置費計算が正値を返す。"""
    assert cooler_capital_cost_yen(100.0) > 0.0
    assert decanter_capital_cost_yen(50.0) > 0.0


def test_heat_exchanger_area_m2() -> None:
    """U と LMTD から伝熱面積を計算できる。"""
    assert heat_exchanger_area_m2(
        duty_kw=3600.0,
        overall_heat_transfer_kj_m2_k_h=3600.0,
        delta_t_lm_k=10.0,
    ) == pytest.approx(360.0)


def test_log_mean_temperature_difference_k() -> None:
    """対数平均温度差を計算できる。"""
    result = log_mean_temperature_difference_k(
        hot_inlet_c=100.0,
        hot_outlet_c=20.0,
        cold_inlet_c=0.0,
        cold_outlet_c=0.0,
    )
    assert result == pytest.approx((100.0 - 20.0) / math.log(100.0 / 20.0))
