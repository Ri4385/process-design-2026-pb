"""デカンター用 HYSYS case の構造を調査する。"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

import pythoncom

from scripts.inspect_hysys_case import (
    CaseInspection,
    close_case,
    connect_hysys,
    get_flowsheet,
    inspect_case,
    open_case,
    quit_hysys,
    strip_none,
)


SCRIPT_DIR = Path(__file__).resolve().parent
CASE_PATH = SCRIPT_DIR / "hysys" / "decanter_0520v2.hsc"
OUTPUT_DIR = SCRIPT_DIR / "diagnostics"
FULL_OUTPUT_JSON = OUTPUT_DIR / "decanter_0520v2_inspection.json"
FOCUSED_OUTPUT_JSON = OUTPUT_DIR / "decanter_0520v2_focus.json"

TARGET_MATERIAL_STREAMS: tuple[str, ...] = (
    "reactor_outlet",
    "separator_feed",
    "off_gas",
    "water_recycle",
    "decanter_outlet",
    "before_tower1_feed",
    "tower1_feed",
)
TARGET_ENERGY_STREAMS: tuple[str, ...] = (
    "CQ-1",
)
TARGET_OPERATIONS: tuple[str, ...] = (
    "C-1",
    "V-1",
    "VLV-1",
)

TARGET_OPERATION_PROBES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "C-1": (
        ("Duty", ("kW", "kJ/h")),
        ("PressureDrop", ("kPa",)),
        ("FeedTemperature", ("C", "degC")),
        ("ProductTemperature", ("C", "degC")),
        ("FeedPressure", ("kPa",)),
        ("ProductPressure", ("kPa",)),
    ),
    "V-1": (
        ("VesselVolume", ("m3",)),
        ("VesselPressure", ("kPa",)),
        ("VesselTemperature", ("C", "degC")),
        ("SeparatorDiameter", ("m",)),
        ("SeparatorLengthOrHeight", ("m",)),
        ("VapourMolarFlow", ("kgmole/h", "kmol/h")),
        ("LiquidMolarFlow", ("kgmole/h", "kmol/h")),
        ("HeavyLiquidMolarFlow", ("kgmole/h", "kmol/h")),
    ),
    "VLV-1": (
        ("ProductPressure", ("kPa",)),
        ("FeedPressure", ("kPa",)),
        ("PressureDrop", ("kPa",)),
        ("ProductTemperature", ("C", "degC")),
        ("FeedTemperature", ("C", "degC")),
    ),
}


def write_json(payload: dict[str, Any], output_path: Path) -> None:
    """JSON を UTF-8 で保存する。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def items_by_name(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """name を key にした辞書を作る。"""
    named_items: dict[str, dict[str, Any]] = {}
    for item in items:
        name = item.get("name")
        if isinstance(name, str):
            named_items[name] = item
    return named_items


def pick_targets(
    items: list[dict[str, Any]],
    target_names: tuple[str, ...],
) -> dict[str, dict[str, Any] | None]:
    """対象名だけを抽出し、存在しないものは None にする。"""
    named_items = items_by_name(items)
    return {target_name: named_items.get(target_name) for target_name in target_names}


def missing_names(targets: dict[str, dict[str, Any] | None]) -> list[str]:
    """抽出対象のうち見つからなかった名前を返す。"""
    return [name for name, value in targets.items() if value is None]


def get_quantity_value(obj: Any, attr_name: str, units: tuple[str, ...]) -> float | None:
    """COM オブジェクトから単一物理量を読む。"""
    quantity = getattr(obj, attr_name, None)
    if quantity is not None:
        for unit in units:
            try:
                return float(quantity.GetValue(unit))
            except Exception:
                pass
        try:
            return float(quantity.Value)
        except Exception:
            pass

    scalar_value = getattr(obj, f"{attr_name}Value", None)
    if isinstance(scalar_value, (int, float)):
        return float(scalar_value)
    return None


def object_name(obj: Any) -> str:
    """COM オブジェクト名を返す。"""
    for attr_name in ("Name", "Tag", "TaggedName", "name"):
        value = getattr(obj, attr_name, None)
        if isinstance(value, str) and value:
            return value
    return "<unknown>"


def iter_collection_items(collection: Any) -> list[Any]:
    """COM collection を list に変換する。"""
    if collection is None:
        return []
    try:
        count = int(collection.Count)
    except Exception:
        return []

    for start_index in (0, 1):
        items: list[Any] = []
        try:
            for index in range(start_index, start_index + count):
                items.append(collection.Item(index))
        except Exception:
            continue
        if len(items) == count:
            return items
    return []


def get_target_operations(flowsheet: Any) -> dict[str, Any | None]:
    """対象 operation の COM オブジェクトを取得する。"""
    operations_collection = getattr(flowsheet, "Operations", None)
    operations = iter_collection_items(operations_collection)
    named_operations = {object_name(operation): operation for operation in operations}
    return {operation_name: named_operations.get(operation_name) for operation_name in TARGET_OPERATIONS}


def probe_target_operations(flowsheet: Any) -> dict[str, dict[str, float | None]]:
    """対象 operation の重要属性を直接読む。"""
    operations = get_target_operations(flowsheet)
    probed: dict[str, dict[str, float | None]] = {}
    for operation_name, operation in operations.items():
        attr_probes = TARGET_OPERATION_PROBES.get(operation_name, ())
        if operation is None:
            probed[operation_name] = {
                attr_name: None
                for attr_name, _ in attr_probes
            }
            continue
        probed[operation_name] = {
            attr_name: get_quantity_value(operation, attr_name, units)
            for attr_name, units in attr_probes
        }
    return probed


def build_focused_payload(inspection: CaseInspection, operation_probes: dict[str, dict[str, float | None]]) -> dict[str, Any]:
    """デカンター最適化で必要な対象だけの JSON payload を作る。"""
    payload = strip_none(asdict(inspection))
    material_streams = pick_targets(
        payload.get("material_streams", []),
        TARGET_MATERIAL_STREAMS,
    )
    energy_streams = pick_targets(
        payload.get("energy_streams", []),
        TARGET_ENERGY_STREAMS,
    )
    operations = pick_targets(
        payload.get("operations", []),
        TARGET_OPERATIONS,
    )
    return {
        "case_path": payload.get("case_path"),
        "prog_id": payload.get("prog_id"),
        "component_names": payload.get("component_names", []),
        "collection_counts": payload.get("collection_counts", {}),
        "targets": {
            "material_streams": material_streams,
            "energy_streams": energy_streams,
            "operations": operations,
        },
        "operation_probes": operation_probes,
        "missing": {
            "material_streams": missing_names(material_streams),
            "energy_streams": missing_names(energy_streams),
            "operations": missing_names(operations),
        },
    }


def main() -> None:
    """デカンター用 HYSYS case を調査して JSON を保存する。"""
    if not CASE_PATH.exists():
        raise FileNotFoundError(CASE_PATH)

    pythoncom.CoInitialize()
    app: Any | None = None
    try:
        app, prog_id = connect_hysys()
        inspection = inspect_case(
            app=app,
            prog_id=prog_id,
            case_path=CASE_PATH,
            include_attrs=True,
        )
        simulation_case = open_case(app, CASE_PATH)
        try:
            flowsheet = get_flowsheet(simulation_case)
            operation_probes = probe_target_operations(flowsheet)
        finally:
            close_case(simulation_case)
        full_payload = strip_none(asdict(inspection))
        focused_payload = build_focused_payload(inspection, operation_probes)
        write_json(full_payload, FULL_OUTPUT_JSON)
        write_json(focused_payload, FOCUSED_OUTPUT_JSON)
        print(
            json.dumps(
                {
                    "full_output_json": str(FULL_OUTPUT_JSON.resolve()),
                    "focused_output_json": str(FOCUSED_OUTPUT_JSON.resolve()),
                    "missing": focused_payload["missing"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        quit_hysys(app)
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
