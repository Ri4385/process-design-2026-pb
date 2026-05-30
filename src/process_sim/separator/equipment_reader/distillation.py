"""HYSYS から蒸留塔の機器モデルを読み取る。"""

from __future__ import annotations

import math
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict

from process_sim.plant.const import HYSYS_INVALID_SENTINEL
from process_sim.separator.equipment import DistillationColumn
from process_sim.separator.equipment_reader.common import (
    collection_item,
    numeric_values,
    required_attr,
    required_number,
)
from process_sim.separator.hysys_equipment_reference import (
    DISTILLATION_COLUMNS,
    DistillationColumnReference,
)
from process_sim.separator.hysys_io import get_quantity


SOUDFERS_BROWN_SF = 0.8
SOUDFERS_BROWN_K_M_S = 0.05
GAS_CONSTANT_PA_M3_PER_KMOL_K = 8.314 * 1000.0

TRAY_SPACING_M = 0.6
TOP_ALLOWANCE_M = 2.0
BOTTOM_ALLOWANCE_M = 4.0
FEED_STAGE_ALLOWANCE_M = 1.0


class ColumnHydraulics(BaseModel):
    """塔径計算に必要な蒸留塔 hydraulics 値。"""

    model_config = ConfigDict(frozen=True)

    design_stage: int
    vapor_mass_flow_kg_s: float
    diameter_m: float


def read_distillation_columns(flowsheet: Any) -> tuple[DistillationColumn, ...]:
    """HYSYS flowsheet から蒸留塔を読み取る。"""
    return tuple(read_distillation_column(flowsheet, reference) for reference in DISTILLATION_COLUMNS)


def read_distillation_column(flowsheet: Any, reference: DistillationColumnReference) -> DistillationColumn:
    """HYSYS flowsheet から蒸留塔1基を読み取る。"""
    operation = collection_item(flowsheet, "Operations", reference.operation_name)
    column_flowsheet = required_attr(operation, "ColumnFlowsheet", reference.operation_name)

    stage_count = stage_count_from_column(column_flowsheet, reference.operation_name)
    feed_stage = feed_stage_from_column(column_flowsheet, reference.operation_name)
    temperatures = numeric_values(column_flowsheet, "TemperaturesValue", reference.operation_name)
    hydraulics = column_hydraulics(column_flowsheet, stage_count, reference.operation_name)

    condenser = collection_item(flowsheet, "EnergyStreams", reference.condenser_energy_name)
    reboiler = collection_item(flowsheet, "EnergyStreams", reference.reboiler_energy_name)

    return DistillationColumn(
        id=reference.id,
        display_name=reference.display_name,
        operation_name=reference.operation_name,
        stage_count=stage_count,
        feed_stage=feed_stage,
        diameter_m=hydraulics.diameter_m,
        height_m=column_height_m(stage_count),
        reflux_ratio=reflux_ratio_from_column(column_flowsheet, reference.operation_name),
        top_temperature_c=required_number(
            temperatures[0],
            f"{reference.operation_name} top temperature",
        ),
        bottom_temperature_c=required_number(
            temperatures[-1],
            f"{reference.operation_name} bottom temperature",
        ),
        condenser_energy_name=reference.condenser_energy_name,
        condenser_duty_kw=heat_flow_kw(condenser, reference.condenser_energy_name),
        reboiler_energy_name=reference.reboiler_energy_name,
        reboiler_duty_kw=heat_flow_kw(reboiler, reference.reboiler_energy_name),
        max_vapor_load_stage=hydraulics.design_stage,
        max_vapor_mass_flow_kg_s=hydraulics.vapor_mass_flow_kg_s,
    )


def stage_count_from_column(column_flowsheet: Any, label: str) -> int:
    """ColumnFlowsheet から実段数を読む。"""
    column_stages = required_attr(column_flowsheet, "ColumnStages", label)
    count = int(required_attr(column_stages, "Count", f"{label}.ColumnStages"))
    if count <= 2:
        raise RuntimeError(f"{label}.ColumnStages.Count が小さすぎます: {count}")
    return count - 2


def feed_stage_from_column(column_flowsheet: Any, label: str) -> int:
    """ColumnFlowsheet から主 feed 段を読む。"""
    feed_stages = required_attr(column_flowsheet, "FeedColumnStages", label)
    count = int(required_attr(feed_stages, "Count", f"{label}.FeedColumnStages"))
    if count <= 0:
        raise RuntimeError(f"{label}.FeedColumnStages が空です")

    values: list[float] = []
    for index in range(count):
        item = feed_stages.Item(index)
        value = getattr(item, "StageNumberValue", None)
        if isinstance(value, (int, float)):
            values.append(float(value))
            if value > 0:
                return int(value)

    raise RuntimeError(
        f"{label}.FeedColumnStages から正の StageNumberValue を取得できませんでした: "
        f"values={values}"
    )


def column_height_m(stage_count: int) -> float:
    """段数から塔高さを計算する。"""
    return (
        TRAY_SPACING_M * (stage_count - 1)
        + TOP_ALLOWANCE_M
        + BOTTOM_ALLOWANCE_M
        + FEED_STAGE_ALLOWANCE_M
    )


def reflux_ratio_from_column(column_flowsheet: Any, label: str) -> float:
    """ColumnFlowsheet から塔の還流比を読む。"""
    value = getattr(column_flowsheet, "RefluxRatio", None)
    if not isinstance(value, (int, float)):
        value = get_quantity(column_flowsheet, "RefluxRatio", ("",))
    return required_number(value, f"{label}.ColumnFlowsheet.RefluxRatio")


def heat_flow_kw(energy_stream: Any, label: str) -> float:
    """energy stream の heat flow を kW で読む。"""
    value = get_quantity(energy_stream, "HeatFlow", ("kW",))
    return required_number(value, f"{label}.HeatFlow")


def column_hydraulics(column_flowsheet: Any, stage_count: int, label: str) -> ColumnHydraulics:
    """ColumnFlowsheet profile から塔径計算値を読む。"""
    vapor_mass_flows = numeric_values(column_flowsheet, "NetMassVapourFlowsValue", label)
    liquid_mass_flows = numeric_values(column_flowsheet, "NetMassLiquidFlowsValue", label)
    vapor_molar_flows = numeric_values(column_flowsheet, "NetMolarVapourFlowsValue", label)
    temperatures = numeric_values(column_flowsheet, "TemperaturesValue", label)
    pressures = numeric_values(column_flowsheet, "PressuresValue", label)
    liquid_volume_flows = numeric_values(column_flowsheet, "NetLiqVolLiquidFlowsValue", label)

    profile_lengths = (
        len(vapor_mass_flows),
        len(liquid_mass_flows),
        len(vapor_molar_flows),
        len(temperatures),
        len(pressures),
        len(liquid_volume_flows),
    )
    min_length = min(profile_lengths)
    if min_length <= 0:
        raise RuntimeError(f"{label} の profile 配列が空です: lengths={profile_lengths}")

    design_index = design_stage_index(vapor_mass_flows[:min_length], label)
    vapor_mass_flow_kg_s = required_number(
        vapor_mass_flows[design_index],
        f"{label} vapor mass flow",
    )
    liquid_mass_flow_kg_s = required_number(
        liquid_mass_flows[design_index],
        f"{label} liquid mass flow",
    )
    vapor_molar_flow_kmol_s = required_number(
        vapor_molar_flows[design_index],
        f"{label} vapor molar flow",
    )
    temperature_c = required_number(temperatures[design_index], f"{label} temperature")
    pressure_kpa = required_number(pressures[design_index], f"{label} pressure")
    liquid_volume_flow_m3_s = required_number(
        liquid_volume_flows[design_index],
        f"{label} liquid volume flow",
    )

    if pressure_kpa <= 0.0:
        raise RuntimeError(f"{label} pressure が 0 以下です: {pressure_kpa}")
    if liquid_volume_flow_m3_s <= 0.0:
        raise RuntimeError(
            f"{label} liquid volume flow が 0 以下です: {liquid_volume_flow_m3_s}"
        )

    vapor_volume_flow_m3_s = (
        vapor_molar_flow_kmol_s
        * GAS_CONSTANT_PA_M3_PER_KMOL_K
        * (273.15 + temperature_c)
        / (pressure_kpa * 1000.0)
    )
    if vapor_volume_flow_m3_s <= 0.0:
        raise RuntimeError(
            f"{label} vapor volume flow が 0 以下です: {vapor_volume_flow_m3_s}"
        )

    vapor_density_kg_m3 = vapor_mass_flow_kg_s / vapor_volume_flow_m3_s
    liquid_density_kg_m3 = liquid_mass_flow_kg_s / liquid_volume_flow_m3_s
    if liquid_density_kg_m3 <= vapor_density_kg_m3:
        raise RuntimeError(
            f"{label} 液密度 <= 蒸気密度です: "
            f"rho_l={liquid_density_kg_m3}, rho_v={vapor_density_kg_m3}"
        )

    allowable_mass_velocity_kg_m2_s = (
        SOUDFERS_BROWN_SF
        * SOUDFERS_BROWN_K_M_S
        * math.sqrt(vapor_density_kg_m3 * (liquid_density_kg_m3 - vapor_density_kg_m3))
    )
    if allowable_mass_velocity_kg_m2_s <= 0.0:
        raise RuntimeError(f"{label} allowable mass velocity が 0 以下です")

    diameter_m = math.sqrt(
        4.0 * vapor_mass_flow_kg_s / (math.pi * allowable_mass_velocity_kg_m2_s)
    )
    if column_height_m(stage_count) / diameter_m <= 0.0:
        raise RuntimeError(f"{label} L/D を計算できませんでした")

    return ColumnHydraulics(
        design_stage=design_index + 1,
        vapor_mass_flow_kg_s=vapor_mass_flow_kg_s,
        diameter_m=diameter_m,
    )


def design_stage_index(vapor_mass_flows: Sequence[float], label: str) -> int:
    """蒸気負荷が最大の段 index を返す。"""
    valid = [
        (index, value)
        for index, value in enumerate(vapor_mass_flows)
        if math.isfinite(value) and not math.isclose(value, HYSYS_INVALID_SENTINEL)
    ]
    if not valid:
        raise RuntimeError(f"{label} に有効な蒸気質量流量がありません")
    return max(valid, key=lambda item: item[1])[0]
