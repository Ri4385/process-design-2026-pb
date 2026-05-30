"""HYSYS から ProcessEquipment を組み立てる。"""

from __future__ import annotations

from typing import Any

from process_sim.separator.equipment import ProcessEquipment
from process_sim.separator.equipment_reader.decanter import read_decanters
from process_sim.separator.equipment_reader.distillation import read_distillation_columns
from process_sim.separator.equipment_reader.heat_exchanger import read_coolers, read_heaters
from process_sim.separator.equipment_reader.rotating_equipment import (
    read_compressors,
    read_pumps,
)
from process_sim.separator.hysys_io import get_flowsheet


def read_process_equipment(simulation_case: Any) -> ProcessEquipment:
    """HYSYS case から分離系機器一式を読み取る。"""
    flowsheet = get_flowsheet(simulation_case)
    return ProcessEquipment(
        distillation_columns=read_distillation_columns(flowsheet),
        decanters=read_decanters(flowsheet),
        coolers=read_coolers(flowsheet),
        heaters=read_heaters(flowsheet),
        pumps=read_pumps(flowsheet),
        compressors=read_compressors(flowsheet),
    )
