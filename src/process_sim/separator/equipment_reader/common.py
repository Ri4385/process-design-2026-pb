"""HYSYS equipment reader の共通処理。"""

from __future__ import annotations

import math
from typing import Any

from process_sim.plant.const import HYSYS_INVALID_SENTINEL


def required_attr(obj: Any, attr_name: str, label: str) -> Any:
    """必須 COM 属性を取得する。"""
    value = getattr(obj, attr_name, None)
    if value is None:
        raise RuntimeError(f"{label}.{attr_name} を取得できませんでした")
    return value


def collection_item(obj: Any, collection_attr_name: str, item_name: str) -> Any:
    """COM collection から名前指定で item を取得する。"""
    collection = required_attr(obj, collection_attr_name, "flowsheet")
    try:
        return collection.Item(item_name)
    except Exception as exc:
        raise RuntimeError(
            f"flowsheet.{collection_attr_name}.Item({item_name}) を取得できませんでした"
        ) from exc


def required_number(value: float | None, label: str) -> float:
    """HYSYS 由来の必須数値を取り出す。"""
    if value is None or not math.isfinite(value) or math.isclose(value, HYSYS_INVALID_SENTINEL):
        raise RuntimeError(f"{label} を取得できませんでした: value={value}")
    return float(value)


def numeric_values(obj: Any, attr_name: str, label: str) -> list[float]:
    """COM 属性から数値配列を取得する。"""
    value = getattr(obj, attr_name, None)
    if value is None:
        raise RuntimeError(f"{label}.{attr_name} を取得できませんでした")
    try:
        return [float(item) for item in value]
    except TypeError as exc:
        raise RuntimeError(f"{label}.{attr_name} を数値配列として読めませんでした") from exc
