"""SM分離塔の還流比を書き込み、機器読み取りで確認する。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from typing import Any

from process_sim.plant.const import DEFAULT_HYSYS_CASE_PATH
from process_sim.separator.equipment import DistillationColumn
from process_sim.separator.equipment_reader.distillation import reflux_ratio_from_column
from process_sim.separator.equipment_reader.process_equipment import read_process_equipment
from process_sim.separator.hysys_io import (
    get_operation,
    get_flowsheet,
    hysys_case,
    wait_for_hysys_calculation,
)


SM_COLUMN_OPERATION_NAME = "T-1"
SM_COLUMN_ID = "sm_column"
CHECK_REFLUX_RATIO = 7.0
READBACK_ABS_TOLERANCE = 1.0e-6
REFLUX_SPEC_NAME = "Reflux Ratio"
SPEC_VALUE_ATTR_CANDIDATES = (
    "SpecValue",
    "SpecValueValue",
    "SpecifiedValue",
    "SpecifiedValueValue",
    "TargetValue",
    "TargetValueValue",
    "GoalValue",
    "GoalValueValue",
    "Value",
    "ValueValue",
)


class RefluxRatioWriteResult(BaseModel):
    """還流比 spec への書き込み結果。"""

    model_config = ConfigDict(frozen=True)

    attr_name: str
    method: str


def main() -> None:
    """既定 HYSYS case で SM分離塔還流比の書き込みを確認する。"""
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

        before_reflux_ratio = reflux_ratio_from_column(column_flowsheet, SM_COLUMN_OPERATION_NAME)
        reflux_spec = find_reflux_ratio_spec(column_flowsheet)
        write_result = write_reflux_ratio_spec(reflux_spec, CHECK_REFLUX_RATIO)
        wait_for_hysys_calculation(simulation_case)

        direct_readback = reflux_ratio_from_column(column_flowsheet, SM_COLUMN_OPERATION_NAME)
        equipment = read_process_equipment(simulation_case)
        sm_column = require_distillation_column(equipment.distillation_columns, SM_COLUMN_ID)

    print("SM分離塔 還流比書き込み確認")
    print(f"- case: {DEFAULT_HYSYS_CASE_PATH}")
    print(f"- operation: {SM_COLUMN_OPERATION_NAME}")
    print(f"- spec: {REFLUX_SPEC_NAME}")
    print(f"- write attr: {write_result.attr_name}")
    print(f"- write method: {write_result.method}")
    print(f"- before: {before_reflux_ratio:.8g}")
    print(f"- write: {CHECK_REFLUX_RATIO:.8g}")
    print(f"- direct readback: {direct_readback:.8g}")
    print(f"- read_process_equipment: {sm_column.reflux_ratio:.8g}")
    print(f"- direct readback ok: {is_close(direct_readback, CHECK_REFLUX_RATIO)}")
    print(f"- equipment readback ok: {is_close(sm_column.reflux_ratio, CHECK_REFLUX_RATIO)}")


def find_reflux_ratio_spec(column_flowsheet: Any) -> Any:
    """ColumnFlowsheet から Reflux Ratio spec を取得する。"""
    specifications = getattr(column_flowsheet, "Specifications", None)
    if specifications is None:
        raise RuntimeError("ColumnFlowsheet.Specifications を取得できませんでした。")

    for spec in iter_collection_items(specifications):
        if object_name(spec) == REFLUX_SPEC_NAME:
            return spec
    names = ", ".join(object_name(spec) for spec in iter_collection_items(specifications))
    raise RuntimeError(f"{REFLUX_SPEC_NAME} spec を取得できませんでした。specifications={names}")


def write_reflux_ratio_spec(reflux_spec: Any, reflux_ratio: float) -> RefluxRatioWriteResult:
    """Reflux Ratio spec の指定値へ無次元値を書き込む。"""
    errors: list[str] = []

    for attr_name in SPEC_VALUE_ATTR_CANDIDATES:
        try:
            setattr(reflux_spec, attr_name, reflux_ratio)
            return RefluxRatioWriteResult(attr_name=attr_name, method="setattr")
        except Exception as exc:
            errors.append(f"{attr_name} setattr: {exc}")

        quantity = getattr(reflux_spec, attr_name, None)
        if quantity is None or isinstance(quantity, (int, float)):
            continue
        set_value = getattr(quantity, "SetValue", None)
        if callable(set_value):
            try:
                set_value(reflux_ratio, "")
                return RefluxRatioWriteResult(attr_name=attr_name, method="SetValue('')")
            except Exception as exc:
                errors.append(f"{attr_name}.SetValue(''): {exc}")
        try:
            quantity.Value = reflux_ratio
            return RefluxRatioWriteResult(attr_name=attr_name, method="Value")
        except Exception as exc:
            errors.append(f"{attr_name}.Value: {exc}")

    attr_names = ", ".join(matching_attr_names(reflux_spec))
    raise RuntimeError(
        "還流比 spec の指定値を書き込めませんでした。\n"
        + f"spec attrs containing value/spec/target/goal: {attr_names}\n"
        + "\n".join(errors)
    )


def iter_collection_items(collection: Any) -> list[Any]:
    """COM collection を list に変換する。"""
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


def object_name(obj: Any) -> str:
    """COM object の表示名を返す。"""
    for attr_name in ("Name", "Tag", "TaggedName", "name"):
        value = getattr(obj, attr_name, None)
        if isinstance(value, str) and value:
            return value
    return "<unknown>"


def matching_attr_names(obj: Any) -> list[str]:
    """spec 値書き込みに関係しそうな属性名を返す。"""
    try:
        names = sorted(name for name in dir(obj) if not name.startswith("_"))
    except Exception:
        return []
    patterns = ("value", "spec", "target", "goal", "active", "estimate")
    return [name for name in names if any(pattern in name.lower() for pattern in patterns)]


def require_distillation_column(
    columns: tuple[DistillationColumn, ...],
    column_id: str,
) -> DistillationColumn:
    """id から蒸留塔モデルを取得する。"""
    for column in columns:
        if column.id == column_id:
            return column
    raise RuntimeError(f"{column_id} を read_process_equipment 結果から取得できませんでした。")


def is_close(actual: float, expected: float) -> bool:
    """還流比の読み返し一致を判定する。"""
    return abs(actual - expected) <= READBACK_ABS_TOLERANCE


if __name__ == "__main__":
    main()
