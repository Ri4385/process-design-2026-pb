"""HYSYS から pump / compressor の機器モデルを読み取る。"""

from __future__ import annotations

from typing import Any

from process_sim.separator.equipment import Compressor, Pump
from process_sim.separator.equipment_reader.common import collection_item, required_number
from process_sim.separator.hysys_equipment_reference import (
    COMPRESSORS,
    PUMPS,
    CompressorReference,
    PumpReference,
)
from process_sim.separator.hysys_io import get_quantity


def read_pumps(flowsheet: Any) -> tuple[Pump, ...]:
    """HYSYS flowsheet からポンプを読み取る。"""
    return tuple(read_pump(flowsheet, reference) for reference in PUMPS)


def read_compressors(flowsheet: Any) -> tuple[Compressor, ...]:
    """HYSYS flowsheet からコンプレッサーを読み取る。"""
    return tuple(read_compressor(flowsheet, reference) for reference in COMPRESSORS)


def read_pump(flowsheet: Any, reference: PumpReference) -> Pump:
    """HYSYS pump の energy stream からポンプ1基を読み取る。"""
    energy_stream = collection_item(flowsheet, "EnergyStreams", reference.energy_name)
    return Pump(
        id=reference.id,
        display_name=reference.display_name,
        energy_name=reference.energy_name,
        power_kw=energy_stream_power_kw(energy_stream, reference.energy_name),
    )


def read_compressor(flowsheet: Any, reference: CompressorReference) -> Compressor:
    """HYSYS compressor の energy stream からコンプレッサー1基を読み取る。"""
    energy_stream = collection_item(flowsheet, "EnergyStreams", reference.energy_name)
    return Compressor(
        id=reference.id,
        display_name=reference.display_name,
        energy_name=reference.energy_name,
        power_kw=energy_stream_power_kw(energy_stream, reference.energy_name),
    )


def energy_stream_power_kw(energy_stream: Any, label: str) -> float:
    """pump / compressor の energy stream power を kW で読む。"""
    value = get_quantity(energy_stream, "Power", ("kW",))
    return required_number(value, f"{label}.Power")
