"""HYSYS から読み取った分離系機器のモデル。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SeparatorEquipment(BaseModel):
    """分離系機器に共通する識別情報。"""

    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str


class DistillationColumn(SeparatorEquipment):
    """HYSYS から読み取った蒸留塔の装置状態。"""

    operation_name: str
    stage_count: int
    feed_stage: int
    diameter_m: float
    height_m: float
    reflux_ratio: float
    top_temperature_c: float
    bottom_temperature_c: float
    condenser_energy_name: str
    condenser_duty_kw: float
    reboiler_energy_name: str
    reboiler_duty_kw: float
    max_vapor_load_stage: int
    max_vapor_mass_flow_kg_s: float


class Decanter(SeparatorEquipment):
    """HYSYS spreadsheet から読み取ったデカンターの装置状態。"""

    spreadsheet_name: str
    radius_m: float
    length_m: float
    volume_m3: float


class Cooler(SeparatorEquipment):
    """HYSYS から読み取った冷却器の装置状態。"""

    energy_name: str
    duty_kw: float
    inlet_temperature_c: float
    outlet_temperature_c: float


class Heater(SeparatorEquipment):
    """HYSYS から読み取った加熱器の装置状態。"""

    energy_name: str
    duty_kw: float
    inlet_temperature_c: float
    outlet_temperature_c: float


class Pump(SeparatorEquipment):
    """HYSYS から読み取ったポンプの装置状態。"""

    energy_name: str
    power_kw: float


class Compressor(SeparatorEquipment):
    """HYSYS から読み取ったコンプレッサーの装置状態。"""

    energy_name: str
    power_kw: float


class ProcessEquipment(BaseModel):
    """コスト計算へ渡す分離系機器一式。"""

    model_config = ConfigDict(frozen=True)

    distillation_columns: tuple[DistillationColumn, ...]
    decanters: tuple[Decanter, ...]
    coolers: tuple[Cooler, ...]
    heaters: tuple[Heater, ...]
    pumps: tuple[Pump, ...]
    compressors: tuple[Compressor, ...]
