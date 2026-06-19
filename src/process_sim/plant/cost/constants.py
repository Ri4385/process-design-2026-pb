"""全体プラントコスト評価で使う単価と係数。"""

from __future__ import annotations


YEN_PER_OKU_YEN = 100_000_000.0
DEPRECIATION_YEARS = 7.0
PLANT_CAPITAL_FACTOR = 2.5
ANCILLARY_FACILITIES_FACTOR = 1.0
MAINTENANCE_RATE_PER_YEAR = 0.03
LABOR_COST_YEN_PER_YEAR = 400_000_000.0

SM_SALES_CAP_TON_PER_YEAR = 200_000.0
FURNACE_EFFICIENCY = 0.8

FEED_PRICE_YEN_PER_KG: dict[str, float] = {
    "eb": 198.63,
    "steam": 5.0,
}

PRODUCT_PRICE_YEN_PER_KG: dict[str, float] = {
    "styrene": 232.231,
    "benzene": 149.269,
    "toluene": 184.07,
}

UTILITY_PRICE = {
    "steam_130c_yen_per_mj": 1.0,
    "steam_160c_yen_per_mj": 1.08,
    "steam_250c_yen_per_mj": 1.4,
    "propylene_yen_per_mj": 0.8,
    "cooling_water_yen_per_ton": 10.0,
    "electricity_yen_per_kwh": 15.0,
    "hexane_yen_per_kg": 30.0,
}

LHV_MJ_PER_KMOL = {
    "hydrogen": 241.795,
    "methane": 802.854,
}
HEXANE_LHV_MJ_PER_KG = 44.73

CP_WATER_KJ_KG_K = 4.184
COOLING_WATER_INLET_C = 30.0
COOLING_WATER_OUTLET_C = 45.0
COOLING_WATER_DELTA_T_K = COOLING_WATER_OUTLET_C - COOLING_WATER_INLET_C
PROPYLENE_REFRIGERANT_TEMPERATURE_C = 0.0

STEAM_TEMPERATURE_C = {
    "steam_130c": 130.0,
    "steam_160c": 160.0,
    "steam_250c": 250.0,
}

U_KJ_M2_K_H = {
    "gas_gas": 720.0,
    "gas_liquid": 720.0,
    "liquid_liquid": 1080.0,
    "boiling_liquid_condensing_gas": 5400.0,
    "liquid_gas": 720.0,
    "gas_condensing_gas": 1800.0,
    "liquid_condensing_gas": 3600.0,
    "boiling_liquid_gas": 1800.0,
    "boiling_liquid_liquid": 3600.0,
}
