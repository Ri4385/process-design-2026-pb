"""固定 HYSYS ケース上の機器参照先定義。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HysysEquipmentReference(BaseModel):
    """HYSYS 上の参照先に共通する識別情報。"""

    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str


class DistillationColumnReference(HysysEquipmentReference):
    """HYSYS 上の蒸留塔参照先。"""

    operation_name: str
    condenser_energy_name: str
    reboiler_energy_name: str


class DecanterReference(HysysEquipmentReference):
    """HYSYS spreadsheet 上のデカンター寸法参照先。"""

    spreadsheet_name: str
    radius_cell: str
    length_cell: str


class CoolerReference(HysysEquipmentReference):
    """HYSYS 上の冷却器参照先。"""

    energy_name: str


class HeaterReference(HysysEquipmentReference):
    """HYSYS 上の加熱器参照先。"""

    energy_name: str


class PumpReference(HysysEquipmentReference):
    """HYSYS 上のポンプ参照先。"""

    energy_name: str


class CompressorReference(HysysEquipmentReference):
    """HYSYS 上のコンプレッサー参照先。"""

    energy_name: str


class ValveReference(HysysEquipmentReference):
    """HYSYS 上のバルブ参照先。"""

    operation_names: tuple[str, ...]


DISTILLATION_COLUMNS: tuple[DistillationColumnReference, ...] = (
    DistillationColumnReference(
        id="sm_column",
        display_name="SM分離塔",
        operation_name="T-1",
        condenser_energy_name="TQ-11",
        reboiler_energy_name="TQ-12",
    ),
    DistillationColumnReference(
        id="eb_column",
        display_name="EB分離塔",
        operation_name="T-2",
        condenser_energy_name="TQ-21",
        reboiler_energy_name="TQ-22",
    ),
    DistillationColumnReference(
        id="bztl_column",
        display_name="BZTL分離塔",
        operation_name="T-3",
        condenser_energy_name="TQ-31",
        reboiler_energy_name="TQ-32",
    ),
)

DECANTERS: tuple[DecanterReference, ...] = (
    DecanterReference(
        id="decanter_1",
        display_name="デカンター1基目",
        spreadsheet_name="SPRDSHT-1",
        radius_cell="A2",
        length_cell="A3",
    ),
    DecanterReference(
        id="decanter_2",
        display_name="デカンター2基目",
        spreadsheet_name="SPRDSHT-2",
        radius_cell="A2",
        length_cell="A3",
    ),
)

COOLERS: tuple[CoolerReference, ...] = (
    CoolerReference(
        id="decanter_1_cooler",
        display_name="デカンター1基目冷却器",
        energy_name="CQ-1",
    ),
    CoolerReference(
        id="decanter_2_cooler",
        display_name="デカンター2基目冷却器",
        energy_name="CQ-2",
    ),
    CoolerReference(
        id="sm_product_cooler",
        display_name="SM製品冷却器",
        energy_name="CQ-3",
    ),
    CoolerReference(
        id="benzene_product_cooler",
        display_name="BZ製品冷却器",
        energy_name="CQ-4",
    ),
    CoolerReference(
        id="toluene_product_cooler",
        display_name="TL製品冷却器",
        energy_name="CQ-5",
    ),
)

HEATERS: tuple[HeaterReference, ...] = (
    HeaterReference(
        id="steam_inlet_heater",
        display_name="入口加熱 steam",
        energy_name="E-heat-water",
    ),
    HeaterReference(
        id="eb_inlet_heater",
        display_name="入口加熱 EB",
        energy_name="E-heat-EB",
    ),
    HeaterReference(
        id="reactor_trim_heater",
        display_name="反応器前 trim heater",
        energy_name="QE-2",
    ),
)

PUMPS: tuple[PumpReference, ...] = (
    PumpReference(
        id="water_inlet_pump",
        display_name="入口加圧 ポンプ水",
        energy_name="PQ-2",
    ),
    PumpReference(
        id="eb_inlet_pump",
        display_name="入口加圧 ポンプEB",
        energy_name="PQ-1",
    ),
    PumpReference(
        id="sm_column_outlet_pump",
        display_name="SM分離塔後 ポンプ",
        energy_name="PQ-3",
    ),
    PumpReference(
        id="sm_product_pump",
        display_name="製品加圧ポンプ SM",
        energy_name="PQ-4",
    ),
)

COMPRESSORS: tuple[CompressorReference, ...] = (
    CompressorReference(
        id="offgas_compressor",
        display_name="SM分離塔後 排ガスコンプレッサー",
        energy_name="KQ-2",
    ),
)

VALVES: tuple[ValveReference, ...] = (
    ValveReference(
        id="sm_column_pressure_reduction_valves",
        display_name="SM分離塔前 バルブ減圧",
        operation_names=("VLV-1-2", "VLV-2"),
    ),
)
