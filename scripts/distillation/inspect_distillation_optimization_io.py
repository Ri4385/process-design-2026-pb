"""蒸留塔部分最適化に必要な HYSYS 入出力経路を確認する。"""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from pydantic import BaseModel, Field
import pythoncom


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_inspect_hysys_case = importlib.import_module("scripts.inspect_hysys_case")
close_case = _inspect_hysys_case.close_case
connect_hysys = _inspect_hysys_case.connect_hysys
get_flowsheet = _inspect_hysys_case.get_flowsheet
iter_collection = _inspect_hysys_case.iter_collection
object_name = _inspect_hysys_case.object_name
object_type_name = _inspect_hysys_case.object_type_name
open_case = _inspect_hysys_case.open_case
quit_hysys = _inspect_hysys_case.quit_hysys
safe_attr_names = _inspect_hysys_case.safe_attr_names
safe_getattr = _inspect_hysys_case.safe_getattr

DEFAULT_CASE_PATH = SCRIPT_DIR / "hysys" / "process_design_0525v1.hsc"
DEFAULT_OUTPUT_PATH = SCRIPT_DIR / "diagnostics" / "distillation_optimization_io_probe.json"

TOWER_OPERATION_NAMES: dict[str, str] = {
    "tower1": "T-1",
    "tower2": "T-2",
    "tower3": "T-3",
}
PRODUCT_COOLER_NAMES: tuple[str, ...] = ("C-3", "C-4", "C-5")
PROFILE_ATTRS: tuple[str, ...] = (
    "ColumnStages",
    "FeedColumnStages",
    "NetMassVapourFlowsValue",
    "NetMassLiquidFlowsValue",
    "NetMolarVapourFlowsValue",
    "TemperaturesValue",
    "PressuresValue",
    "NetLiqVolLiquidFlowsValue",
)
FEED_STAGE_ITEM_VALUE_ATTRS: tuple[str, ...] = (
    "Stage",
    "StageValue",
    "StageNumber",
    "StageNumberValue",
    "Tray",
    "TrayValue",
    "TrayNumber",
    "TrayNumberValue",
    "Value",
)
TRAYSECTION_MATCH_WORDS: tuple[str, ...] = (
    "feed",
    "stage",
    "tray",
    "location",
    "specify",
    "section",
)
COOLER_VALUE_ATTRS: tuple[str, ...] = (
    "Duty",
    "DutyValue",
    "HeatFlow",
    "HeatFlowValue",
    "FeedTemperature",
    "FeedTemperatureValue",
    "ProductTemperature",
    "ProductTemperatureValue",
)


class AttrRead(BaseModel):
    """属性読み取り結果。"""

    exists: bool
    kind: str | None = None
    value: float | str | bool | None = None
    values: list[float | str | bool] | None = None
    error: str | None = None


class FeedStageWriteProbe(BaseModel):
    """feed 段書き換え確認結果。"""

    attr_exists: bool
    collection_count: int | None = None
    current_values: list[float | str | bool] | None = None
    item_reads: list[dict[str, AttrRead]] = Field(default_factory=list)
    item_matched_attrs: list[list[str]] = Field(default_factory=list)
    can_write_same_value: bool | None = None
    same_value_error: str | None = None
    can_write_changed_value: bool | None = None
    changed_value_error: str | None = None
    restored: bool | None = None
    restore_error: str | None = None


class FeedLocationCallProbe(BaseModel):
    """feed location 指定呼び出しの確認結果。"""

    label: str
    success: bool
    error: str | None = None


class FeedLocationDutyProbe(BaseModel):
    """feed 段指定後の duty 読み取り確認結果。"""

    requested_stage: int
    call_success: bool
    call_error: str | None = None
    solve_success: bool | None = None
    solve_error: str | None = None
    feed_stage_values_after: list[float | str | bool] | None = None
    energy_streams_after: list[EnergyStreamProbe] = Field(default_factory=list)


class TraySectionFeedLocationProbe(BaseModel):
    """traysection 経由の feed location 確認結果。"""

    found: bool
    name: str | None = None
    type_name: str | None = None
    matched_attrs: list[str] = Field(default_factory=list)
    feed_stage_values: list[float | str | bool] | None = None
    feed_stream_names: list[str] = Field(default_factory=list)
    tray_section_feed_names: list[str] = Field(default_factory=list)
    same_stage_calls: list[FeedLocationCallProbe] = Field(default_factory=list)
    changed_stage_calls: list[FeedLocationCallProbe] = Field(default_factory=list)
    restore_calls: list[FeedLocationCallProbe] = Field(default_factory=list)


class EnergyStreamProbe(BaseModel):
    """column 内部 energy stream 確認結果。"""

    index: int
    name: str
    type_name: str | None = None
    heat_flow: AttrRead


class TowerIoProbe(BaseModel):
    """塔ごとの入出力確認結果。"""

    tower: str
    operation_name: str
    operation_found: bool
    operation_type_name: str | None = None
    column_flowsheet_found: bool
    column_flowsheet_name: str | None = None
    profile_attrs: dict[str, AttrRead] = Field(default_factory=dict)
    energy_streams: list[EnergyStreamProbe] = Field(default_factory=list)
    feed_stage_write: FeedStageWriteProbe
    traysection_feed_location: TraySectionFeedLocationProbe
    feed_location_duty_probes: list[FeedLocationDutyProbe] = Field(default_factory=list)


class CoolerIoProbe(BaseModel):
    """冷却器ごとの入出力確認結果。"""

    operation_name: str
    found: bool
    type_name: str | None = None
    matched_attrs: list[str] = Field(default_factory=list)
    values: dict[str, AttrRead] = Field(default_factory=dict)
    linked_energy_streams: list[str] = Field(default_factory=list)
    linked_material_streams: dict[str, list[str]] = Field(default_factory=dict)


class DistillationOptimizationIoProbe(BaseModel):
    """蒸留塔部分最適化の HYSYS IO 確認結果。"""

    case_path: str
    prog_id: str
    towers: list[TowerIoProbe]
    coolers: list[CoolerIoProbe]


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-path", type=Path, default=DEFAULT_CASE_PATH)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--probe-feed-write-change",
        action="store_true",
        help="feed 段を一時的に別値へ変更し、元に戻す確認も行う。保存はしない。",
    )
    parser.add_argument(
        "--probe-feed-duty-after-location",
        action="store_true",
        help="SpecifyFeedLocation 後に solve して duty を読む確認を行う。保存はしない。",
    )
    parser.add_argument(
        "--probe-feed-radius",
        type=int,
        default=1,
        help="現在 feed 段から上下何段まで確認するか。",
    )
    return parser.parse_args()


def resolve_repo_path(path: Path) -> Path:
    """相対パスを repository root 基準にする。"""
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def collection_count(value: Any) -> int | None:
    """COM collection の Count を返す。"""
    try:
        return int(value.Count)
    except Exception:
        return None


def value_kind(value: Any) -> str:
    """値の種類を短く返す。"""
    if isinstance(value, (int, float, str, bool)):
        return type(value).__name__
    count = collection_count(value)
    if count is not None:
        return f"collection[{count}]"
    return str(object_type_name(value) or type(value).__name__)


def scalar_value(value: Any) -> float | str | bool | None:
    """単一値を JSON 化できる形にする。"""
    if isinstance(value, (int, float, str, bool)):
        return value
    for attr_name in ("Value", "CellValue", "HeatFlowValue"):
        attr_value = safe_getattr(value, attr_name)
        if isinstance(attr_value, (int, float, str, bool)):
            return attr_value
    return None


def coerce_values(value: Any) -> list[float | str | bool] | None:
    """配列値を JSON 化できる list にする。"""
    if value is None or isinstance(value, (str, bytes)):
        return None
    try:
        return [
            item
            for item in value
            if isinstance(item, (int, float, str, bool))
        ]
    except TypeError:
        return None


def read_attr(obj: Any, attr_name: str) -> AttrRead:
    """COM 属性を読む。"""
    try:
        value = getattr(obj, attr_name)
    except Exception as exc:
        return AttrRead(exists=False, error=str(exc))
    scalar = scalar_value(value)
    values = coerce_values(value)
    return AttrRead(
        exists=True,
        kind=value_kind(value),
        value=scalar,
        values=values,
    )


def read_quantity(obj: Any, attr_name: str, units: Sequence[str]) -> AttrRead:
    """単位付き quantity を読む。"""
    value = safe_getattr(obj, attr_name)
    if value is None:
        return read_attr(obj, attr_name)
    for unit in units:
        try:
            return AttrRead(
                exists=True,
                kind=value_kind(value),
                value=float(value.GetValue(unit)),
            )
        except Exception:
            pass
    return read_attr(obj, attr_name)


def operations_by_name(flowsheet: Any) -> dict[str, Any]:
    """flowsheet operation を名前で引ける辞書にする。"""
    return {
        object_name(operation): operation
        for operation in iter_collection(safe_getattr(flowsheet, "Operations"))
    }


def collection_names(obj: Any, attr_name: str) -> list[str]:
    """collection または単一 object の名前一覧を返す。"""
    value = safe_getattr(obj, attr_name)
    items = iter_collection(value)
    if items:
        return [object_name(item) for item in items]
    if value is not None:
        return [object_name(value)]
    return []


def first_positive_stage(values: Sequence[float | str | bool] | None) -> int | None:
    """feed stage 値から最初の正の整数段を返す。"""
    if values is None:
        return None
    for value in values:
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    return None


def first_named_item(obj: Any, attr_names: Sequence[str]) -> Any | None:
    """候補 collection から最初に名前を持つ item を返す。"""
    for attr_name in attr_names:
        for item in iter_collection(safe_getattr(obj, attr_name)):
            if object_name(item):
                return item
    return None


def find_traysection(column_flowsheet: Any) -> Any | None:
    """ColumnFlowsheet 内の traysection を取得する。"""
    for operation in iter_collection(safe_getattr(column_flowsheet, "Operations")):
        type_name = object_type_name(operation).lower()
        name = object_name(operation).lower()
        if type_name == "traysection" or "tray" in type_name or name == "main tower":
            return operation
    return None


def probe_call(label: str, func: Any) -> FeedLocationCallProbe:
    """COM 呼び出しを捕捉して結果にする。"""
    try:
        func()
    except Exception as exc:
        return FeedLocationCallProbe(label=label, success=False, error=str(exc))
    return FeedLocationCallProbe(label=label, success=True)


def specify_feed_location_calls(traysection: Any, feed_item: Any, stage: int) -> list[FeedLocationCallProbe]:
    """SpecifyFeedLocation の代表的な呼び出し候補を試す。"""
    feed_name = object_name(feed_item)
    method = safe_getattr(traysection, "SpecifyFeedLocation")
    if method is None:
        return [FeedLocationCallProbe(label="SpecifyFeedLocation missing", success=False, error="method not found")]
    return [
        probe_call(
            f"SpecifyFeedLocation(feed_object, {stage})",
            lambda: method(feed_item, stage),
        ),
        probe_call(
            f"SpecifyFeedLocation({feed_name!r}, {stage})",
            lambda: method(feed_name, stage),
        ),
        probe_call(
            f"SpecifyFeedLocation(1, {stage})",
            lambda: method(1, stage),
        ),
    ]


def solve_case(simulation_case: Any) -> None:
    """HYSYS case の計算更新を促す。"""
    solver = safe_getattr(simulation_case, "Solver")
    if solver is None:
        return
    can_solve = safe_getattr(solver, "CanSolve")
    if isinstance(can_solve, bool) and not can_solve:
        try:
            solver.CanSolve = True
        except Exception:
            pass
    for method_name in ("Solve", "Run"):
        method = safe_getattr(solver, method_name)
        if callable(method):
            method()
            return


def read_energy_streams(column_flowsheet: Any) -> list[EnergyStreamProbe]:
    """ColumnFlowsheet の energy stream duty を読む。"""
    return [
        EnergyStreamProbe(
            index=index,
            name=object_name(energy_stream),
            type_name=object_type_name(energy_stream),
            heat_flow=read_quantity(energy_stream, "HeatFlow", ("kW", "kJ/h")),
        )
        for index, energy_stream in enumerate(iter_collection(safe_getattr(column_flowsheet, "EnergyStreams")))
    ]


def probe_feed_location_duties(
    simulation_case: Any,
    column_flowsheet: Any,
    traysection: Any | None,
    current_stages: Sequence[float | str | bool] | None,
    radius: int,
) -> list[FeedLocationDutyProbe]:
    """現在 feed 段の近傍で、指定後に duty が読めるか確認する。"""
    if traysection is None:
        return []
    current_stage = first_positive_stage(current_stages)
    if current_stage is None:
        return []
    feed_item = first_named_item(
        traysection,
        ("TraySectionFeeds", "Feeds", "MaterialFeeds", "AttachedFeeds"),
    )
    if feed_item is None:
        feed_item = first_named_item(column_flowsheet, ("Feeds", "FeedStreams", "MaterialFeeds"))
    if feed_item is None:
        return []

    stages = [current_stage]
    for offset in range(1, max(radius, 0) + 1):
        stages.extend([current_stage - offset, current_stage + offset])
    stages = [stage for stage in stages if stage >= 1]

    method = safe_getattr(traysection, "SpecifyFeedLocation")
    if method is None:
        return [
            FeedLocationDutyProbe(
                requested_stage=stage,
                call_success=False,
                call_error="SpecifyFeedLocation method not found",
            )
            for stage in stages
        ]

    results: list[FeedLocationDutyProbe] = []
    for stage in stages:
        try:
            method(feed_item, stage)
        except Exception as exc:
            results.append(
                FeedLocationDutyProbe(
                    requested_stage=stage,
                    call_success=False,
                    call_error=str(exc),
                )
            )
            continue

        solve_success = True
        solve_error = None
        try:
            solve_case(simulation_case)
        except Exception as exc:
            solve_success = False
            solve_error = str(exc)

        feed_stages_after = coerce_values(safe_getattr(column_flowsheet, "FeedColumnStagesValue"))
        if feed_stages_after is None:
            feed_stages_after = coerce_values(safe_getattr(column_flowsheet, "FeedColumnStages"))
        results.append(
            FeedLocationDutyProbe(
                requested_stage=stage,
                call_success=True,
                solve_success=solve_success,
                solve_error=solve_error,
                feed_stage_values_after=feed_stages_after,
                energy_streams_after=read_energy_streams(column_flowsheet),
            )
        )

    try:
        method(feed_item, current_stage)
        solve_case(simulation_case)
    except Exception:
        pass
    return results


def probe_traysection_feed_location(
    column_flowsheet: Any,
    current_stages: Sequence[float | str | bool] | None,
    probe_change: bool,
) -> TraySectionFeedLocationProbe:
    """traysection の feed 段指定経路を確認する。"""
    traysection = find_traysection(column_flowsheet)
    if traysection is None:
        return TraySectionFeedLocationProbe(found=False)

    attrs = safe_attr_names(traysection, limit=700)
    matched_attrs = [
        attr
        for attr in attrs
        if any(word in attr.lower() for word in TRAYSECTION_MATCH_WORDS)
    ]
    current_stage = first_positive_stage(current_stages)
    feed_item = first_named_item(
        traysection,
        ("TraySectionFeeds", "Feeds", "MaterialFeeds", "AttachedFeeds"),
    )
    if feed_item is None:
        feed_item = first_named_item(column_flowsheet, ("Feeds", "FeedStreams", "MaterialFeeds"))

    same_calls: list[FeedLocationCallProbe] = []
    changed_calls: list[FeedLocationCallProbe] = []
    restore_calls: list[FeedLocationCallProbe] = []
    if feed_item is not None and current_stage is not None:
        same_calls = specify_feed_location_calls(traysection, feed_item, current_stage)
        if probe_change:
            changed_stage = current_stage + 1
            changed_calls = specify_feed_location_calls(traysection, feed_item, changed_stage)
            restore_calls = specify_feed_location_calls(traysection, feed_item, current_stage)

    return TraySectionFeedLocationProbe(
        found=True,
        name=object_name(traysection),
        type_name=object_type_name(traysection),
        matched_attrs=matched_attrs,
        feed_stage_values=list(current_stages) if current_stages is not None else None,
        feed_stream_names=collection_names(column_flowsheet, "FeedStreams")
        + collection_names(column_flowsheet, "Feeds"),
        tray_section_feed_names=collection_names(traysection, "TraySectionFeeds")
        + collection_names(traysection, "Feeds"),
        same_stage_calls=same_calls,
        changed_stage_calls=changed_calls,
        restore_calls=restore_calls,
    )


def assign_values(obj: Any, values: Sequence[float | str | bool]) -> None:
    """COM 配列属性へ値を書き込む。"""
    if hasattr(obj, "SetValues"):
        obj.SetValues(list(values))
        return
    if hasattr(obj, "Values"):
        obj.Values = list(values)
        return
    if hasattr(obj, "Value"):
        obj.Value = list(values)
        return
    raise RuntimeError("SetValues, Values, Value のいずれでも書き込めませんでした")


def assign_scalar(obj: Any, attr_name: str, value: float | str | bool) -> None:
    """COM item の単一属性へ値を書き込む。"""
    if attr_name == "Value":
        setattr(obj, "Value", value)
        return
    setattr(obj, attr_name, value)


def feed_stage_item_reads(item: Any) -> dict[str, AttrRead]:
    """FeedColumnStages item の候補値を読む。"""
    return {
        attr_name: read_attr(item, attr_name)
        for attr_name in FEED_STAGE_ITEM_VALUE_ATTRS
    }


def first_item_stage_value(item_reads: dict[str, AttrRead]) -> tuple[str, float | str | bool] | None:
    """item 読み取り結果から最初の数値属性を返す。"""
    for attr_name, result in item_reads.items():
        if isinstance(result.value, (int, float, str, bool)):
            return attr_name, result.value
    return None


def probe_feed_stage_write(column_flowsheet: Any, probe_change: bool) -> FeedStageWriteProbe:
    """FeedColumnStages の書き換え可能性を確認する。"""
    attr = safe_getattr(column_flowsheet, "FeedColumnStages")
    if attr is None:
        return FeedStageWriteProbe(attr_exists=False)

    items = iter_collection(attr)
    item_reads = [feed_stage_item_reads(item) for item in items]
    item_matched_attrs = [
        [
            name
            for name in safe_attr_names(item, limit=250)
            if any(word in name.lower() for word in ("stage", "tray", "feed", "value"))
        ]
        for item in items
    ]
    current = coerce_values(safe_getattr(column_flowsheet, "FeedColumnStagesValue"))
    if current is None:
        current = coerce_values(attr)
    if current is None:
        scalar = scalar_value(attr)
        current = [scalar] if scalar is not None else None
    if (current is None or len(current) == 0) and item_reads:
        values: list[float | str | bool] = []
        for reads in item_reads:
            item_value = first_item_stage_value(reads)
            if item_value is not None:
                values.append(item_value[1])
        current = values

    can_write_same: bool | None = None
    same_error: str | None = None
    can_write_changed: bool | None = None
    changed_error: str | None = None
    restored: bool | None = None
    restore_error: str | None = None

    if current:
        try:
            assign_values(attr, current)
            can_write_same = True
        except Exception as exc:
            can_write_same = False
            same_error = str(exc)
            if items and item_reads:
                item_value = first_item_stage_value(item_reads[0])
                if item_value is not None:
                    try:
                        assign_scalar(items[0], item_value[0], item_value[1])
                        can_write_same = True
                        same_error = None
                    except Exception as item_exc:
                        same_error = f"{same_error}; item.{item_value[0]}: {item_exc}"

    if probe_change and current and isinstance(current[0], (int, float)):
        changed = list(current)
        changed[0] = float(current[0]) + 1.0
        try:
            assign_values(attr, changed)
            can_write_changed = True
        except Exception as exc:
            can_write_changed = False
            changed_error = str(exc)
            if items and item_reads:
                item_value = first_item_stage_value(item_reads[0])
                if item_value is not None and isinstance(item_value[1], (int, float)):
                    try:
                        assign_scalar(items[0], item_value[0], float(item_value[1]) + 1.0)
                        can_write_changed = True
                        changed_error = None
                    except Exception as item_exc:
                        changed_error = f"{changed_error}; item.{item_value[0]}: {item_exc}"
        try:
            assign_values(attr, current)
            restored = True
        except Exception as exc:
            restored = False
            restore_error = str(exc)
            if items and item_reads:
                item_value = first_item_stage_value(item_reads[0])
                if item_value is not None:
                    try:
                        assign_scalar(items[0], item_value[0], item_value[1])
                        restored = True
                        restore_error = None
                    except Exception as item_exc:
                        restore_error = f"{restore_error}; item.{item_value[0]}: {item_exc}"

    return FeedStageWriteProbe(
        attr_exists=True,
        collection_count=collection_count(attr),
        current_values=current,
        item_reads=item_reads,
        item_matched_attrs=item_matched_attrs,
        can_write_same_value=can_write_same,
        same_value_error=same_error,
        can_write_changed_value=can_write_changed,
        changed_value_error=changed_error,
        restored=restored,
        restore_error=restore_error,
    )


def probe_tower(
    simulation_case: Any,
    tower: str,
    operation_name: str,
    operation: Any | None,
    probe_feed_write_change: bool,
    probe_feed_duty_after_location: bool,
    probe_feed_radius: int,
) -> TowerIoProbe:
    """塔の IO 経路を確認する。"""
    if operation is None:
        return TowerIoProbe(
            tower=tower,
            operation_name=operation_name,
            operation_found=False,
            column_flowsheet_found=False,
            feed_stage_write=FeedStageWriteProbe(attr_exists=False),
            traysection_feed_location=TraySectionFeedLocationProbe(found=False),
        )

    column_flowsheet = safe_getattr(operation, "ColumnFlowsheet")
    if column_flowsheet is None:
        return TowerIoProbe(
            tower=tower,
            operation_name=operation_name,
            operation_found=True,
            operation_type_name=object_type_name(operation),
            column_flowsheet_found=False,
            feed_stage_write=FeedStageWriteProbe(attr_exists=False),
            traysection_feed_location=TraySectionFeedLocationProbe(found=False),
        )

    profile_attrs = {attr_name: read_attr(column_flowsheet, attr_name) for attr_name in PROFILE_ATTRS}
    energy_streams = read_energy_streams(column_flowsheet)
    feed_stage_write = probe_feed_stage_write(column_flowsheet, probe_feed_write_change)
    traysection_feed_location = probe_traysection_feed_location(
        column_flowsheet,
        feed_stage_write.current_values,
        probe_feed_write_change,
    )
    traysection = find_traysection(column_flowsheet) if traysection_feed_location.found else None
    feed_location_duty_probes = (
        probe_feed_location_duties(
            simulation_case=simulation_case,
            column_flowsheet=column_flowsheet,
            traysection=traysection,
            current_stages=feed_stage_write.current_values,
            radius=probe_feed_radius,
        )
        if probe_feed_duty_after_location
        else []
    )
    return TowerIoProbe(
        tower=tower,
        operation_name=operation_name,
        operation_found=True,
        operation_type_name=object_type_name(operation),
        column_flowsheet_found=True,
        column_flowsheet_name=object_name(column_flowsheet),
        profile_attrs=profile_attrs,
        energy_streams=energy_streams,
        feed_stage_write=feed_stage_write,
        traysection_feed_location=traysection_feed_location,
        feed_location_duty_probes=feed_location_duty_probes,
    )


def linked_names(operation: Any, attr_names: Sequence[str]) -> dict[str, list[str]]:
    """linked object collection の名前を返す。"""
    result: dict[str, list[str]] = {}
    for attr_name in attr_names:
        items = iter_collection(safe_getattr(operation, attr_name))
        if items:
            result[attr_name] = [object_name(item) for item in items]
            continue
        value = safe_getattr(operation, attr_name)
        if value is not None:
            result[attr_name] = [object_name(value)]
    return result


def probe_cooler(operation_name: str, operation: Any | None) -> CoolerIoProbe:
    """冷却器の IO 経路を確認する。"""
    if operation is None:
        return CoolerIoProbe(operation_name=operation_name, found=False)
    attrs = safe_attr_names(operation, limit=500)
    matched = [
        attr
        for attr in attrs
        if any(word in attr.lower() for word in ("duty", "heat", "feed", "product", "temperature", "energy"))
    ]
    return CoolerIoProbe(
        operation_name=operation_name,
        found=True,
        type_name=object_type_name(operation),
        matched_attrs=matched,
        values={attr_name: read_attr(operation, attr_name) for attr_name in COOLER_VALUE_ATTRS},
        linked_energy_streams=[
            name
            for names in linked_names(operation, ("EnergyStreams", "EnergyFeeds", "EnergyProducts")).values()
            for name in names
        ],
        linked_material_streams=linked_names(operation, ("Feeds", "Products", "MaterialFeeds", "MaterialProducts")),
    )


def inspect_io(
    case_path: Path,
    probe_feed_write_change: bool,
    probe_feed_duty_after_location: bool,
    probe_feed_radius: int,
) -> DistillationOptimizationIoProbe:
    """HYSYS case を開いて部分最適化 IO を調査する。"""
    pythoncom.CoInitialize()
    app: Any | None = None
    simulation_case: Any | None = None
    try:
        app, prog_id = connect_hysys()
        simulation_case = open_case(app, case_path.resolve())
        flowsheet = get_flowsheet(simulation_case)
        operations = operations_by_name(flowsheet)
        return DistillationOptimizationIoProbe(
            case_path=str(case_path.resolve()),
            prog_id=prog_id,
            towers=[
                probe_tower(
                    simulation_case=simulation_case,
                    tower=tower,
                    operation_name=operation_name,
                    operation=operations.get(operation_name),
                    probe_feed_write_change=probe_feed_write_change,
                    probe_feed_duty_after_location=probe_feed_duty_after_location,
                    probe_feed_radius=probe_feed_radius,
                )
                for tower, operation_name in TOWER_OPERATION_NAMES.items()
            ],
            coolers=[
                probe_cooler(operation_name, operations.get(operation_name))
                for operation_name in PRODUCT_COOLER_NAMES
            ],
        )
    finally:
        if simulation_case is not None:
            close_case(simulation_case)
        quit_hysys(app)
        pythoncom.CoUninitialize()


def write_json(payload: BaseModel, output_path: Path) -> None:
    """JSON を UTF-8 で保存する。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(payload.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8")
    print(json.dumps({"output_json": str(output_path.resolve())}, ensure_ascii=False, indent=2))


def main() -> None:
    """調査を実行する。"""
    args = parse_args()
    case_path = resolve_repo_path(args.case_path)
    output_path = resolve_repo_path(args.output_json)
    if not case_path.exists():
        raise FileNotFoundError(case_path)
    payload = inspect_io(
        case_path=case_path,
        probe_feed_write_change=bool(args.probe_feed_write_change),
        probe_feed_duty_after_location=bool(args.probe_feed_duty_after_location),
        probe_feed_radius=args.probe_feed_radius,
    )
    write_json(payload, output_path)


if __name__ == "__main__":
    main()
