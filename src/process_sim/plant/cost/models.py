"""全体プラントコスト評価の入出力モデル。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CostBreakdownItem(BaseModel):
    """費目別の金額と補足情報。"""

    model_config = ConfigDict(frozen=True)

    name: str
    yen_per_year: float = 0.0
    capital_yen: float = 0.0
    duty_kw: float = 0.0
    area_m2: float | None = None
    note: str = ""


class HeatRecoveryResult(BaseModel):
    """熱回収器の計算結果。"""

    model_config = ConfigDict(frozen=True)

    hot_equipment_id: str
    cold_equipment_id: str
    recovered_duty_kw: float
    hot_residual_cooling_kw: float
    cold_residual_heating_kw: float
    hot_inlet_c: float
    hot_outlet_c: float
    cold_inlet_c: float
    cold_outlet_c: float
    lmtd_k: float
    area_m2: float
    capital_yen: float


class TQStream(BaseModel):
    """T-Q 線図用の process stream 区間。"""

    model_config = ConfigDict(frozen=True)

    case_name: str
    stream_type: str
    role: str
    id: str
    inlet_temperature_c: float
    outlet_temperature_c: float
    duty_kw: float


class ExternalUtilityLoad(BaseModel):
    """熱回収後に外部 utility が担当する heat load。"""

    model_config = ConfigDict(frozen=True)

    utility: str
    target_id: str
    inlet_temperature_c: float | None
    outlet_temperature_c: float | None
    duty_kw: float


class CapitalCostResult(BaseModel):
    """建設費と年換算装置費の集計。"""

    model_config = ConfigDict(frozen=True)

    reactor: CostBreakdownItem
    distillation_columns: CostBreakdownItem
    heat_exchangers: CostBreakdownItem
    decanters: CostBreakdownItem
    pumps: CostBreakdownItem
    compressors: CostBreakdownItem
    ancillary_facilities_capital_yen: float
    total_plant_capital_yen: float
    annualized_equipment_yen_per_year: float
    heat_recovery: HeatRecoveryResult
    equipment_details: tuple[CostBreakdownItem, ...]


class RevenueCostResult(BaseModel):
    """製品収入の集計。"""

    model_config = ConfigDict(frozen=True)

    sm: CostBreakdownItem
    benzene: CostBreakdownItem
    toluene: CostBreakdownItem
    total_yen_per_year: float


class RawMaterialCostResult(BaseModel):
    """原料費の集計。"""

    model_config = ConfigDict(frozen=True)

    fresh_eb: CostBreakdownItem
    fresh_h2o: CostBreakdownItem
    total_yen_per_year: float


class UtilityCostResult(BaseModel):
    """utility cost の集計。"""

    model_config = ConfigDict(frozen=True)

    steam_130c: CostBreakdownItem
    steam_160c: CostBreakdownItem
    steam_250c: CostBreakdownItem
    cooling_water: CostBreakdownItem
    propylene_refrigerant: CostBreakdownItem
    electricity: CostBreakdownItem
    hexane_fuel: CostBreakdownItem
    total_yen_per_year: float
    furnace_required_duty_kw: float
    offgas_fuel_heat_mj_h: float
    hexane_fuel_heat_mj_h: float


class FixedOperatingCostResult(BaseModel):
    """固定運転費の集計。"""

    model_config = ConfigDict(frozen=True)

    labor: CostBreakdownItem
    maintenance: CostBreakdownItem
    total_yen_per_year: float


class WholePlantCostResult(BaseModel):
    """全体プラントコスト評価結果。"""

    model_config = ConfigDict(frozen=True)

    revenue: RevenueCostResult
    raw_material: RawMaterialCostResult
    capital: CapitalCostResult
    utility: UtilityCostResult
    fixed_operating: FixedOperatingCostResult
    annual_profit_yen_per_year: float
    tq_streams_no_heat_recovery: tuple[TQStream, ...]
    tq_streams_with_heat_recovery: tuple[TQStream, ...]
    external_utility_loads_with_heat_recovery: tuple[ExternalUtilityLoad, ...]
    warnings: tuple[str, ...]
