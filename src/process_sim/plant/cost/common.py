"""コスト評価の共通計算関数。"""

from __future__ import annotations

import math

from process_sim.constants.physical_properties import SPECIES_PHYSICAL_PROPERTIES
from process_sim.plant.const import HOURS_PER_YEAR
from process_sim.plant.cost.constants import YEN_PER_OKU_YEN


def yen_to_oku_yen(value_yen: float) -> float:
    """円を億円へ変換する。"""
    return value_yen / YEN_PER_OKU_YEN


def annual_component_value_yen(component_id: str, flow_kmol_h: float, price_yen_per_kg: float) -> float:
    """成分流量と単価から年間金額を計算する。"""
    property_ = SPECIES_PHYSICAL_PROPERTIES[component_id]
    return flow_kmol_h * property_.molecular_weight * price_yen_per_kg * HOURS_PER_YEAR


def annual_mass_value_yen(mass_kg_h: float, price_yen_per_kg: float) -> float:
    """質量流量と単価から年間金額を計算する。"""
    return mass_kg_h * price_yen_per_kg * HOURS_PER_YEAR


def annual_energy_value_yen(duty_kw: float, price_yen_per_mj: float) -> float:
    """熱 duty と MJ 単価から年間金額を計算する。"""
    return abs(duty_kw) * 3.6 * price_yen_per_mj * HOURS_PER_YEAR


def log_mean_temperature_difference_k(
    hot_inlet_c: float,
    hot_outlet_c: float,
    cold_inlet_c: float,
    cold_outlet_c: float,
) -> float:
    """向流熱交換器の対数平均温度差を計算する。"""
    delta_t_1 = hot_inlet_c - cold_outlet_c
    delta_t_2 = hot_outlet_c - cold_inlet_c
    if delta_t_1 <= 0.0 or delta_t_2 <= 0.0:
        raise ValueError(
            "temperature differences must be positive: "
            f"dt1={delta_t_1:.3f}, dt2={delta_t_2:.3f}"
        )
    if math.isclose(delta_t_1, delta_t_2):
        return delta_t_1
    return (delta_t_1 - delta_t_2) / math.log(delta_t_1 / delta_t_2)


def heat_exchanger_area_m2(duty_kw: float, u_kj_m2_k_h: float, lmtd_k: float) -> float:
    """熱負荷、U、LMTD から伝熱面積を計算する。"""
    if u_kj_m2_k_h <= 0.0:
        raise ValueError("overall heat transfer coefficient must be positive")
    if lmtd_k <= 0.0:
        raise ValueError("lmtd must be positive")
    return abs(duty_kw) * 3600.0 / (u_kj_m2_k_h * lmtd_k)


def require_positive(value: float, label: str) -> None:
    """値が正でない場合に停止する。"""
    if value <= 0.0:
        raise ValueError(f"{label} must be positive: {value}")
