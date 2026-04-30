"""Plant-level records shared across reactor and separator implementations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


PLANT_STREAM_NAMES: tuple[str, ...] = (
    "reactor_outlet",
    "separator_feed",
    "off_gas",
    "water_recycle",
    "eb_recycle",
    "sm_product",
    "bz_product",
    "tl_product",
)


@dataclass(frozen=True)
class PlantStreamRecord:
    """主要ストリームの記録。単位は明示された属性名に従う。"""

    name: str
    temperature_c: float | None
    pressure_kpa: float | None
    total_molar_flow_kmol_h: float | None
    component_molar_flow_kmol_h: dict[str, float]
    component_molar_fraction: dict[str, float]


@dataclass(frozen=True)
class PlantRunRecord:
    """プラントを1回流した結果の記録。"""

    case_path: Path
    reactor_outlet_temperature_c: float
    reactor_outlet_pressure_kpa: float
    streams: dict[str, PlantStreamRecord]
    metadata: dict[str, Any]
