"""蒸留塔 COM オブジェクトに存在する各段物性関連 key を調査する。"""

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
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "diagnostics"
DEFAULT_ATTR_LIMIT = 700
TARGET_TYPE_NAME = "distillation"
TARGET_KEYWORDS: tuple[str, ...] = (
    "Density",
    "MassFlow",
    "Vapour",
    "Vapor",
    "Liquid",
    "Liq",
    "Stage",
    "Tray",
    "Column",
    "Profile",
    "Hydraulic",
    "Temperature",
    "Pressure",
)
IMPORTANT_CHILD_ATTRS: tuple[str, ...] = (
    "ColumnFlowsheet",
    "Operations",
    "MaterialStreams",
    "EnergyStreams",
    "Streams",
)
TRANSPORT_PROFILE_CHILD_CANDIDATES: tuple[str, ...] = (
    "Performance",
    "PerformancePlots",
    "Plots",
    "Plot",
    "Profiles",
    "Profile",
    "ProfileTables",
    "ProfileTable",
    "PropertyProfiles",
    "PropertyProfile",
    "TransportProperties",
    "TransportProperty",
    "TransportPropertyProfiles",
    "TransportPropertyProfile",
    "TransportPropertyTable",
    "TransportPropertyTables",
    "PropertyProfileTable",
    "PropertyProfileTables",
    "HydraulicProfiles",
    "HydraulicProfile",
    "Tables",
    "Table",
    "DataTables",
    "DataTable",
    "ColumnProfiles",
    "ColumnProfile",
)
TRANSPORT_PROFILE_VALUE_CANDIDATES: tuple[str, ...] = (
    "Values",
    "Value",
    "CellValues",
    "TableValues",
    "ProfileValues",
    "StageValues",
    "TrayValues",
    "RowValues",
    "ColumnValues",
    "VapourDensity",
    "VapourDensityValue",
    "VaporDensity",
    "VaporDensityValue",
    "VapourMassDensity",
    "VapourMassDensityValue",
    "VaporMassDensity",
    "VaporMassDensityValue",
    "VapourMassFlow",
    "VapourMassFlowValue",
    "VaporMassFlow",
    "VaporMassFlowValue",
    "LiquidDensity",
    "LiquidDensityValue",
    "LiqDensity",
    "LiqDensityValue",
    "LiquidMassDensity",
    "LiquidMassDensityValue",
    "LiqMassDensity",
    "LiqMassDensityValue",
)


class CollectionItemSummary(BaseModel):
    """collection item の属性一覧を表す。"""

    index: int
    name: str
    type_name: str | None = None
    matched_attrs: list[str] = Field(default_factory=list)
    all_attrs: list[str] = Field(default_factory=list)
    direct_candidate_hits: dict[str, str] = Field(default_factory=dict)


class ObjectKeySummary(BaseModel):
    """COM オブジェクトに存在する key の要約を表す。"""

    path: str
    name: str
    type_name: str | None = None
    matched_attrs: list[str] = Field(default_factory=list)
    all_attrs: list[str] = Field(default_factory=list)
    direct_candidate_hits: dict[str, str] = Field(default_factory=dict)
    direct_value_hits: dict[str, str] = Field(default_factory=dict)
    collections: dict[str, list[CollectionItemSummary]] = Field(default_factory=dict)
    children: list[ObjectKeySummary] = Field(default_factory=list)


class DistillationKeyInspection(BaseModel):
    """蒸留塔 key 調査結果を表す。"""

    case_path: str
    prog_id: str
    target_type_name: str
    target_keywords: list[str]
    operations_seen: list[dict[str, str | None]]
    distillation_operations: list[ObjectKeySummary]
    missing: dict[str, str | list[str]]


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case-path",
        type=Path,
        default=DEFAULT_CASE_PATH,
        help="調査する HYSYS .hsc ファイル",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="JSON の保存先。未指定なら scripts/distillation/diagnostics/{case_stem}_tray_hydraulics_probe.json",
    )
    parser.add_argument(
        "--operation",
        action="append",
        default=[],
        help="対象 operation 名。複数指定可。未指定なら type_name が distillation の operation を調査する",
    )
    parser.add_argument(
        "--attr-limit",
        type=int,
        default=DEFAULT_ATTR_LIMIT,
        help="dir() で保存する属性数の上限",
    )
    return parser.parse_args()


def resolve_repo_path(path: Path) -> Path:
    """相対パスを repository root 基準で絶対パスにする。"""
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def default_output_path(case_path: Path) -> Path:
    """既定の JSON 出力先を返す。"""
    return DEFAULT_OUTPUT_DIR / f"{case_path.stem}_tray_hydraulics_probe.json"


def write_json(payload: BaseModel, output_path: Path) -> None:
    """JSON を UTF-8 で保存する。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        payload.model_dump_json(indent=2, exclude_none=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output_json": str(output_path.resolve())}, ensure_ascii=False, indent=2))


def matched_attrs(attrs: Sequence[str]) -> list[str]:
    """目的の物性に関係しそうな属性名だけ抽出する。"""
    return [
        attr
        for attr in attrs
        if any(keyword.lower() in attr.lower() for keyword in TARGET_KEYWORDS)
    ]


def object_kind(value: Any) -> str:
    """COM 値の種類を短く表す。"""
    if isinstance(value, (int, float, str, bool)):
        return type(value).__name__
    count = collection_count(value)
    if count is not None:
        return f"collection[{count}]"
    type_name = object_type_name(value)
    return str(type_name or type(value).__name__)


def direct_candidate_hits(obj: Any, attr_names: Sequence[str]) -> dict[str, str]:
    """dir() に出ない可能性がある候補属性を直接確認する。"""
    hits: dict[str, str] = {}
    for attr_name in attr_names:
        value = safe_getattr(obj, attr_name)
        if value is not None:
            hits[attr_name] = object_kind(value)
    return hits


def get_operations(flowsheet: Any) -> list[Any]:
    """flowsheet から operation 一覧を返す。"""
    return iter_collection(safe_getattr(flowsheet, "Operations"))


def summarize_operations(flowsheet: Any) -> list[dict[str, str | None]]:
    """ケース内 operation の名前と型を返す。"""
    return [
        {
            "name": object_name(operation),
            "type_name": object_type_name(operation),
        }
        for operation in get_operations(flowsheet)
    ]


def selected_operations(flowsheet: Any, operation_names: Sequence[str]) -> list[Any]:
    """指定名または type_name が distillation の operation を返す。"""
    operations = get_operations(flowsheet)
    if operation_names:
        named = {object_name(operation): operation for operation in operations}
        return [named[name] for name in operation_names if name in named]
    return [
        operation
        for operation in operations
        if str(object_type_name(operation) or "").lower() == TARGET_TYPE_NAME
    ]


def collection_count(value: Any) -> int | None:
    """COM collection の Count を返す。"""
    try:
        return int(value.Count)
    except Exception:
        return None


def summarize_collection_items(collection: Any, attr_limit: int) -> list[CollectionItemSummary]:
    """collection item の key を列挙する。"""
    items: list[CollectionItemSummary] = []
    for index, item in enumerate(iter_collection(collection)):
        attrs = safe_attr_names(item, limit=attr_limit)
        items.append(
            CollectionItemSummary(
                index=index,
                name=object_name(item),
                type_name=object_type_name(item),
                matched_attrs=matched_attrs(attrs),
                all_attrs=attrs,
                direct_candidate_hits=direct_candidate_hits(
                    item,
                    TRANSPORT_PROFILE_CHILD_CANDIDATES + TRANSPORT_PROFILE_VALUE_CANDIDATES,
                ),
            )
        )
    return items


def existing_child_attrs(obj: Any, attrs: Sequence[str]) -> list[str]:
    """実在する重要 child 属性名を返す。"""
    child_attrs: list[str] = []
    for attr in IMPORTANT_CHILD_ATTRS + TRANSPORT_PROFILE_CHILD_CANDIDATES:
        if attr in child_attrs:
            continue
        if attr in attrs or attr in TRANSPORT_PROFILE_CHILD_CANDIDATES:
            if safe_getattr(obj, attr) is not None:
                child_attrs.append(attr)
    return child_attrs


def summarize_object_keys(
    obj: Any,
    path: str,
    attr_limit: int,
    depth: int,
    visited: set[int],
) -> ObjectKeySummary:
    """COM オブジェクトの key と主要 child の key を列挙する。"""
    object_id = id(obj)
    if object_id in visited:
        attrs = safe_attr_names(obj, limit=attr_limit)
        return ObjectKeySummary(
            path=path,
            name=object_name(obj),
            type_name=object_type_name(obj),
            matched_attrs=matched_attrs(attrs),
            all_attrs=attrs,
            direct_candidate_hits=direct_candidate_hits(obj, TRANSPORT_PROFILE_CHILD_CANDIDATES),
            direct_value_hits=direct_candidate_hits(obj, TRANSPORT_PROFILE_VALUE_CANDIDATES),
        )
    visited.add(object_id)

    attrs = safe_attr_names(obj, limit=attr_limit)
    summary = ObjectKeySummary(
        path=path,
        name=object_name(obj),
        type_name=object_type_name(obj),
        matched_attrs=matched_attrs(attrs),
        all_attrs=attrs,
        direct_candidate_hits=direct_candidate_hits(obj, TRANSPORT_PROFILE_CHILD_CANDIDATES),
        direct_value_hits=direct_candidate_hits(obj, TRANSPORT_PROFILE_VALUE_CANDIDATES),
    )

    if depth <= 0:
        return summary

    for attr in existing_child_attrs(obj, attrs):
        value = safe_getattr(obj, attr)
        count = collection_count(value)
        if count is not None:
            summary.collections[attr] = summarize_collection_items(value, attr_limit)
            continue
        summary.children.append(
            summarize_object_keys(
                obj=value,
                path=f"{path}.{attr}",
                attr_limit=attr_limit,
                depth=depth - 1,
                visited=visited,
            )
        )
    return summary


def build_missing(
    operation_names: Sequence[str],
    operations_seen: Sequence[dict[str, str | None]],
    distillation_operations: Sequence[ObjectKeySummary],
) -> dict[str, str | list[str]]:
    """調査対象が見つからない場合の確認情報を返す。"""
    missing: dict[str, str | list[str]] = {}
    if operation_names and not distillation_operations:
        seen_names = [str(item["name"]) for item in operations_seen if item.get("name")]
        missing["requested_operations_not_found"] = list(operation_names)
        missing["available_operation_names"] = seen_names
    if not operation_names and not distillation_operations:
        missing["distillation_operation"] = "type_name が distillation の operation が見つかりませんでした。"
    return missing


def inspect_distillation_keys(
    app: Any,
    prog_id: str,
    case_path: Path,
    operation_names: Sequence[str],
    attr_limit: int,
) -> DistillationKeyInspection:
    """蒸留塔 COM オブジェクトに存在する key を調査する。"""
    simulation_case = open_case(app=app, case_path=case_path.resolve())
    try:
        flowsheet = get_flowsheet(simulation_case)
        operations_seen = summarize_operations(flowsheet)
        distillation_operations = [
            summarize_object_keys(
                obj=operation,
                path=f"Operations.{object_name(operation)}",
                attr_limit=attr_limit,
                depth=2,
                visited=set(),
            )
            for operation in selected_operations(flowsheet, operation_names)
        ]
        return DistillationKeyInspection(
            case_path=str(case_path.resolve()),
            prog_id=prog_id,
            target_type_name=TARGET_TYPE_NAME,
            target_keywords=list(TARGET_KEYWORDS),
            operations_seen=operations_seen,
            distillation_operations=distillation_operations,
            missing=build_missing(operation_names, operations_seen, distillation_operations),
        )
    finally:
        close_case(simulation_case)


def main() -> None:
    """蒸留塔 key 調査を実行する。"""
    args = parse_args()
    case_path = resolve_repo_path(args.case_path)
    if not case_path.exists():
        raise FileNotFoundError(case_path)

    output_path = args.output_json
    if output_path is None:
        output_path = default_output_path(case_path)
    else:
        output_path = resolve_repo_path(output_path)

    pythoncom.CoInitialize()
    app: Any | None = None
    try:
        app, prog_id = connect_hysys()
        inspection = inspect_distillation_keys(
            app=app,
            prog_id=prog_id,
            case_path=case_path,
            operation_names=args.operation,
            attr_limit=args.attr_limit,
        )
        write_json(inspection, output_path)
    finally:
        quit_hysys(app)
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
