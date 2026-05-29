"""HYSYS から cooler / heater の機器モデルを読み取る。"""

from __future__ import annotations

from typing import Any

from process_sim.separator.equipment import Cooler, Heater
from process_sim.separator.equipment_reader.common import collection_item, required_number
from process_sim.separator.hysys_equipment_reference import (
    COOLERS,
    HEATERS,
    CoolerReference,
    HeaterReference,
)
from process_sim.separator.hysys_io import get_quantity


def read_coolers(flowsheet: Any) -> tuple[Cooler, ...]:
    """HYSYS flowsheet から冷却器を読み取る。"""
    return tuple(read_cooler(flowsheet, reference) for reference in COOLERS)


def read_heaters(flowsheet: Any) -> tuple[Heater, ...]:
    """HYSYS flowsheet から加熱器を読み取る。"""
    return tuple(read_heater(flowsheet, reference) for reference in HEATERS)


def read_cooler(flowsheet: Any, reference: CoolerReference) -> Cooler:
    """HYSYS cooler operation から冷却器1基を読み取る。"""
    operation = collection_item(flowsheet, "Operations", reference.operation_name)
    return Cooler(
        id=reference.id,
        display_name=reference.display_name,
        energy_name=reference.energy_name,
        duty_kw=operation_duty_kw(operation, reference.operation_name),
        inlet_temperature_c=operation_temperature_c(
            operation,
            "FeedTemperature",
            f"{reference.operation_name}.FeedTemperature",
        ),
        outlet_temperature_c=operation_temperature_c(
            operation,
            "ProductTemperature",
            f"{reference.operation_name}.ProductTemperature",
        ),
    )


def read_heater(flowsheet: Any, reference: HeaterReference) -> Heater:
    """HYSYS heater operation から加熱器1基を読み取る。"""
    operation = collection_item(flowsheet, "Operations", reference.operation_name)
    return Heater(
        id=reference.id,
        display_name=reference.display_name,
        energy_name=reference.energy_name,
        duty_kw=operation_duty_kw(operation, reference.operation_name),
        inlet_temperature_c=operation_temperature_c(
            operation,
            "FeedTemperature",
            f"{reference.operation_name}.FeedTemperature",
        ),
        outlet_temperature_c=operation_temperature_c(
            operation,
            "ProductTemperature",
            f"{reference.operation_name}.ProductTemperature",
        ),
    )


def operation_duty_kw(operation: Any, label: str) -> float:
    """cooler / heater operation の duty を kW で読む。"""
    value = get_quantity(operation, "Duty", ("kW", "kJ/h"))
    return required_number(value, f"{label}.Duty")


def operation_temperature_c(operation: Any, attr_name: str, label: str) -> float:
    """cooler / heater operation の温度を degC で読む。"""
    value = get_quantity(operation, attr_name, ("C", "degC"))
    return required_number(value, label)
