"""SM分離塔の Reflux Ratio spec の COM 属性を調査する。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from process_sim.plant.const import DEFAULT_HYSYS_CASE_PATH
from process_sim.separator.equipment_reader.distillation import reflux_ratio_from_column
from process_sim.separator.hysys_io import get_flowsheet, get_operation, hysys_case


SM_COLUMN_OPERATION_NAME = "T-1"
REFLUX_SPEC_NAME = "Reflux Ratio"
OUTPUT_PATH = Path("scripts/distillation/diagnostics/sm_column_reflux_spec_probe.json")
PROBE_ATTR_PATTERNS = ("value", "spec", "target", "goal", "active", "estimate", "stage")


def main() -> None:
    """既定 HYSYS case の SM分離塔 Reflux Ratio spec を調査する。"""
    with hysys_case(DEFAULT_HYSYS_CASE_PATH.resolve(), visible=True) as (
        _app,
        simulation_case,
        _prog_id,
    ):
        flowsheet = get_flowsheet(simulation_case)
        operation = get_operation(flowsheet, SM_COLUMN_OPERATION_NAME)
        column_flowsheet = getattr(operation, "ColumnFlowsheet", None)
        if column_flowsheet is None:
            raise RuntimeError(f"{SM_COLUMN_OPERATION_NAME}.ColumnFlowsheet を取得できませんでした。")

        reflux_spec = find_named_item(
            getattr(column_flowsheet, "Specifications", None),
            REFLUX_SPEC_NAME,
        )
        active_specs = getattr(column_flowsheet, "ActiveSpecifications", None)
        payload = {
            "case_path": str(DEFAULT_HYSYS_CASE_PATH),
            "operation_name": SM_COLUMN_OPERATION_NAME,
            "column_reflux_ratio": reflux_ratio_from_column(column_flowsheet, SM_COLUMN_OPERATION_NAME),
            "specifications": summarize_collection(getattr(column_flowsheet, "Specifications", None)),
            "active_specifications": summarize_collection(active_specs),
            "reflux_spec": summarize_object(reflux_spec),
            "same_value_write_probe": same_value_write_probe(reflux_spec),
        }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output_json": str(OUTPUT_PATH.resolve())}, ensure_ascii=False, indent=2))


def find_named_item(collection: Any, item_name: str) -> Any:
    """COM collection から名前一致の item を返す。"""
    if collection is None:
        raise RuntimeError("collection がありません。")
    for item in iter_collection_items(collection):
        if object_name(item) == item_name:
            return item
    names = ", ".join(object_name(item) for item in iter_collection_items(collection))
    raise RuntimeError(f"{item_name} を取得できませんでした。items={names}")


def summarize_collection(collection: Any) -> list[dict[str, Any]]:
    """COM collection の item 要約を返す。"""
    return [
        {
            "index": index,
            "name": object_name(item),
            "type_name": object_type_name(item),
            "matched_attrs": matching_attr_names(item),
        }
        for index, item in enumerate(iter_collection_items(collection))
    ]


def summarize_object(obj: Any) -> dict[str, Any]:
    """COM object の属性と候補値を要約する。"""
    attrs = safe_attr_names(obj)
    matched_attrs = matching_attr_names(obj)
    return {
        "name": object_name(obj),
        "type_name": object_type_name(obj),
        "matched_attrs": matched_attrs,
        "matched_values": {attr_name: read_attr(obj, attr_name) for attr_name in matched_attrs},
        "all_attrs": attrs,
    }


def same_value_write_probe(obj: Any) -> list[dict[str, Any]]:
    """現在値と同じ値を書き込めるかを候補属性ごとに確認する。"""
    results: list[dict[str, Any]] = []
    for attr_name in matching_attr_names(obj):
        read_result = read_attr(obj, attr_name)
        value = read_result.get("value")
        if not isinstance(value, (int, float)):
            continue
        result: dict[str, Any] = {"attr": attr_name, "current_value": value}
        try:
            setattr(obj, attr_name, value)
            result["setattr_same_value"] = True
        except Exception as exc:
            result["setattr_same_value"] = False
            result["setattr_error"] = str(exc)
        quantity = getattr(obj, attr_name, None)
        if quantity is not None and not isinstance(quantity, (int, float)):
            try:
                quantity.Value = value
                result["quantity_value_same_value"] = True
            except Exception as exc:
                result["quantity_value_same_value"] = False
                result["quantity_value_error"] = str(exc)
        results.append(result)
    return results


def read_attr(obj: Any, attr_name: str) -> dict[str, Any]:
    """属性の値を安全に読む。"""
    try:
        value = getattr(obj, attr_name)
    except Exception as exc:
        return {"exists": False, "error": str(exc)}
    if isinstance(value, (int, float, str, bool)):
        return {"exists": True, "kind": type(value).__name__, "value": value}
    value_attr = getattr(value, "Value", None)
    if isinstance(value_attr, (int, float, str, bool)):
        return {"exists": True, "kind": "quantity", "value": value_attr}
    return {
        "exists": True,
        "kind": object_type_name(value),
        "name": object_name(value),
    }


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


def safe_attr_names(obj: Any) -> list[str]:
    """属性名一覧を安全に返す。"""
    try:
        return sorted(name for name in dir(obj) if not name.startswith("_"))
    except Exception:
        return []


def matching_attr_names(obj: Any) -> list[str]:
    """還流比 spec で重要そうな属性名を返す。"""
    return [
        name
        for name in safe_attr_names(obj)
        if any(pattern in name.lower() for pattern in PROBE_ATTR_PATTERNS)
    ]


def object_name(obj: Any) -> str:
    """COM object の表示名を返す。"""
    for attr_name in ("Name", "Tag", "TaggedName", "name"):
        value = getattr(obj, attr_name, None)
        if isinstance(value, str) and value:
            return value
    return "<unknown>"


def object_type_name(obj: Any) -> str | None:
    """COM object の型名を返す。"""
    for attr_name in ("TypeName", "ClassName", "ObjectType", "OperationType"):
        value = getattr(obj, attr_name, None)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, (int, float)):
            return str(value)
    return type(obj).__name__


if __name__ == "__main__":
    main()
