"""HYSYS spreadsheet からデカンターの機器モデルを読み取る。"""

from __future__ import annotations

import math
from typing import Any

from process_sim.separator.equipment import Decanter
from process_sim.separator.equipment_reader.common import collection_item, required_number
from process_sim.separator.hysys_equipment_reference import DECANTERS, DecanterReference


DECANTER_DIAMETER_CELL_ROW = 0
DECANTER_DIAMETER_CELL_COLUMN = 1
DECANTER_LENGTH_CELL_ROW = 0
DECANTER_LENGTH_CELL_COLUMN = 2


def read_decanters(flowsheet: Any) -> tuple[Decanter, ...]:
    """HYSYS flowsheet からデカンターを読み取る。"""
    return tuple(read_decanter(flowsheet, reference) for reference in DECANTERS)


def read_decanter(flowsheet: Any, reference: DecanterReference) -> Decanter:
    """HYSYS spreadsheet からデカンター1基を読み取る。"""
    spreadsheet = collection_item(flowsheet, "Operations", reference.spreadsheet_name)
    diameter_m = required_number(
        spreadsheet_cell_value(
            spreadsheet,
            DECANTER_DIAMETER_CELL_ROW,
            DECANTER_DIAMETER_CELL_COLUMN,
        ),
        f"{reference.spreadsheet_name} decanter diameter",
    )
    length_m = required_number(
        spreadsheet_cell_value(
            spreadsheet,
            DECANTER_LENGTH_CELL_ROW,
            DECANTER_LENGTH_CELL_COLUMN,
        ),
        f"{reference.spreadsheet_name} decanter length",
    )
    radius_m = diameter_m / 2.0
    volume_m3 = math.pi * radius_m**2 * length_m
    return Decanter(
        id=reference.id,
        display_name=reference.display_name,
        spreadsheet_name=reference.spreadsheet_name,
        radius_m=radius_m,
        length_m=length_m,
        volume_m3=volume_m3,
    )


def spreadsheet_cell_value(spreadsheet: Any, row: int, column: int) -> float | None:
    """HYSYS spreadsheet cell の数値を読む。"""
    cell = spreadsheet.Cell(row, column)
    if isinstance(cell, (int, float)):
        return float(cell)
    for attr_name in ("CellValue", "Value"):
        value = getattr(cell, attr_name, None)
        if isinstance(value, (int, float)):
            return float(value)
    return None
