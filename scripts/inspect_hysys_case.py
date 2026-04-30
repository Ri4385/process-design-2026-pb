"""HYSYS ケースの COM 経由で読める構造を JSON 出力する。

このスクリプトは原則として読み取りだけを行う。
ケースを開いた後、保存せずに閉じる。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Sequence

import pythoncom
import pywintypes
import win32com.client


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_PATH = REPO_ROOT / "data" / "hysys" / "process_design_0430v4.hsc"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "diagnostics"
PROG_IDS: tuple[str, ...] = (
    "HYSYS.Application.NewInstance.V14.0",
    "HYSYS.Application.V14.0",
    "HYSYS.Application.NewInstance",
    "HYSYS.Application",
)
QUANTITY_UNITS: dict[str, tuple[str, ...]] = {
    "Temperature": ("C", "degC", "K"),
    "Pressure": ("kPa", "Pa", "atm"),
    "MolarFlow": ("kgmole/h", "kmol/h", "kgmole/s", "kmol/s"),
    "MassFlow": ("kg/h", "kg/s"),
    "VolumeFlow": ("m3/h", "m3/s"),
    "VapourFraction": ("", "fraction"),
}
COLLECTION_ATTRS: tuple[str, ...] = (
    "MaterialStreams",
    "EnergyStreams",
    "Operations",
    "OperationsCollection",
    "ColumnFlowsheets",
    "SubFlowsheets",
)
OPERATION_LINK_ATTRS: tuple[str, ...] = (
    "Feeds",
    "Products",
    "MaterialFeeds",
    "MaterialProducts",
    "EnergyStreams",
    "EnergyFeeds",
    "EnergyProducts",
)
STREAM_KEY_ATTR_PATTERNS: tuple[str, ...] = (
    "Temperature",
    "Pressure",
    "MolarFlow",
    "MassFlow",
    "ComponentMolarFlow",
    "ComponentMolarFraction",
    "VapourFraction",
    "CanModifyStream",
)
OPERATION_KEY_ATTR_PATTERNS: tuple[str, ...] = (
    "Feed",
    "Product",
    "Stream",
    "ColumnFlowsheet",
    "Duty",
    "Pressure",
    "Temperature",
    "Reflux",
    "Reboil",
    "Condenser",
    "Reboiler",
    "Spec",
)
COLUMN_PROBE_ATTRS: tuple[str, ...] = (
    "ColumnFlowsheet",
    "Column",
    "ColumnOperation",
    "ColumnOp",
    "MainTS",
    "TraySection",
    "TraySections",
    "Specs",
    "Specifications",
    "ActiveSpecs",
    "ColumnSpecs",
    "MonitorSpecs",
    "RefluxRatio",
    "RefluxRatioValue",
    "RefluxRate",
    "RefluxRateValue",
    "BoilupRatio",
    "BoilupRatioValue",
    "ReboilRatio",
    "ReboilRatioValue",
    "CondenserDuty",
    "CondenserDutyValue",
    "ReboilerDuty",
    "ReboilerDutyValue",
    "TopPressure",
    "TopPressureValue",
    "BottomPressure",
    "BottomPressureValue",
    "CondenserPressure",
    "CondenserPressureValue",
    "ReboilerPressure",
    "ReboilerPressureValue",
    "NumStages",
    "NumberOfStages",
    "FeedStage",
    "FeedStageNumber",
)
CHILD_PROBE_ATTRS: tuple[str, ...] = (
    "Operations",
    "MaterialStreams",
    "EnergyStreams",
    "Specs",
    "Specifications",
    "ActiveSpecs",
    "ColumnSpecs",
    "TraySections",
    "Stages",
    "Feeds",
    "Products",
)
SCALAR_PROBE_UNITS: dict[str, tuple[str, ...]] = {
    "RefluxRatio": ("",),
    "BoilupRatio": ("",),
    "ReboilRatio": ("",),
    "CondenserDuty": ("kJ/h", "kW"),
    "ReboilerDuty": ("kJ/h", "kW"),
    "Duty": ("kJ/h", "kW"),
    "TopPressure": ("kPa",),
    "BottomPressure": ("kPa",),
    "CondenserPressure": ("kPa",),
    "ReboilerPressure": ("kPa",),
    "ProductTemperature": ("C", "degC"),
    "ProductPressure": ("kPa",),
    "PressureDrop": ("kPa",),
    "VesselTemperature": ("C", "degC"),
    "VesselPressure": ("kPa",),
}


@dataclass(frozen=True)
class ObjectSummary:
    """COM オブジェクトの要約。"""

    name: str
    type_name: str | None
    key_attrs: list[str]
    available_attrs: list[str] | None


@dataclass(frozen=True)
class StreamSummary:
    """HYSYS ストリームの要約。"""

    name: str
    type_name: str | None
    key_attrs: list[str]
    available_attrs: list[str] | None
    writable_candidates: list[str]
    quantities: dict[str, float | None]
    component_names: list[str]
    component_molar_flow: dict[str, float] | None
    component_molar_fraction: dict[str, float] | None


@dataclass(frozen=True)
class OperationSummary:
    """HYSYS 操作オブジェクトの要約。"""

    name: str
    type_name: str | None
    key_attrs: list[str]
    available_attrs: list[str] | None
    linked_objects: dict[str, list[str]]
    probed_attrs: dict[str, Any]


@dataclass(frozen=True)
class CaseInspection:
    """ケース調査結果。"""

    connected: bool
    prog_id: str
    case_path: str
    simulation_case: ObjectSummary
    flowsheet: ObjectSummary
    fluid_package: ObjectSummary | None
    component_names: list[str]
    collection_counts: dict[str, int | None]
    material_streams: list[StreamSummary]
    energy_streams: list[StreamSummary]
    operations: list[OperationSummary]


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
        help="JSON の保存先。未指定なら data/diagnostics/{case_stem}_inspection.json に上書き保存する",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="ファイル保存せず、フル JSON を標準出力へ表示する",
    )
    parser.add_argument(
        "--include-attrs",
        action="store_true",
        help="全 available_attrs も出力する。通常は不要",
    )
    return parser.parse_args()


def connect_hysys() -> tuple[Any, str]:
    """HYSYS COM アプリケーションへ接続する。"""
    errors: list[str] = []
    for prog_id in PROG_IDS:
        try:
            app = win32com.client.Dispatch(prog_id)
            return app, prog_id
        except pywintypes.com_error as exc:
            errors.append(f"{prog_id}: {exc}")
    joined = "\n".join(errors)
    raise RuntimeError(f"HYSYS に接続できませんでした。\n{joined}")


def open_case(app: Any, case_path: Path) -> Any:
    """HYSYS ケースを開く。"""
    simulation_cases = getattr(app, "SimulationCases", None)
    if simulation_cases is None:
        raise RuntimeError("SimulationCases を取得できませんでした。")

    errors: list[str] = []
    for candidate in (
        lambda: simulation_cases.Open(str(case_path)),
        lambda: simulation_cases.Open(case_path),
        lambda: simulation_cases.Open(str(case_path), False),
    ):
        try:
            return candidate()
        except Exception as exc:
            errors.append(str(exc))

    joined = "\n".join(errors)
    raise RuntimeError(f"ケースを開けませんでした: {case_path}\n{joined}")


def get_flowsheet(simulation_case: Any) -> Any:
    """ケースから flowsheet を取得する。"""
    for attr_name in ("Flowsheet", "MainFlowsheet"):
        flowsheet = getattr(simulation_case, attr_name, None)
        if flowsheet is not None:
            return flowsheet
    raise RuntimeError("Flowsheet を取得できませんでした。")


def object_name(obj: Any) -> str:
    """COM オブジェクト名を返す。"""
    for attr_name in ("Name", "Tag", "TaggedName"):
        value = safe_getattr(obj, attr_name)
        if isinstance(value, str) and value:
            return value
    return "<unknown>"


def object_type_name(obj: Any) -> str | None:
    """COM オブジェクトの型名らしき情報を返す。"""
    for attr_name in ("TypeName", "ClassName", "ObjectType", "OperationType"):
        value = safe_getattr(obj, attr_name)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, (int, float)):
            return str(value)
    return type(obj).__name__


def safe_getattr(obj: Any, attr_name: str) -> Any | None:
    """例外を握って属性を取得する。"""
    try:
        return getattr(obj, attr_name)
    except Exception:
        return None


def safe_attr_names(obj: Any, limit: int = 220) -> list[str]:
    """dir の結果を安全に返す。"""
    try:
        names = sorted(name for name in dir(obj) if not name.startswith("_"))
    except Exception:
        return []
    return names[:limit]


def filter_attrs(attrs: Sequence[str], patterns: Sequence[str]) -> list[str]:
    """指定パターンを含む属性だけ返す。"""
    return [
        attr
        for attr in attrs
        if any(pattern.lower() in attr.lower() for pattern in patterns)
    ]


def summarize_object(obj: Any, include_attrs: bool) -> ObjectSummary:
    """COM オブジェクトの要約を作る。"""
    attrs = safe_attr_names(obj)
    return ObjectSummary(
        name=object_name(obj),
        type_name=object_type_name(obj),
        key_attrs=filter_attrs(attrs, ("Flowsheet", "FluidPackage", "MaterialStreams", "EnergyStreams", "Operations", "Save", "Close")),
        available_attrs=attrs if include_attrs else None,
    )


def coerce_name_list(value: Any) -> list[str]:
    """COM 由来の名前一覧を list[str] に変換する。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return [str(item) for item in value]
    except TypeError:
        return []
    except Exception:
        return []


def iter_collection(collection: Any) -> list[Any]:
    """COM collection を list に変換する。"""
    if collection is None:
        return []

    count = collection_count(collection)
    if count is None:
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


def collection_count(collection: Any) -> int | None:
    """COM collection の Count を返す。"""
    try:
        return int(collection.Count)
    except Exception:
        return None


def object_reference_summary(obj: Any) -> dict[str, Any]:
    """COM オブジェクト参照の短い要約を返す。"""
    return {
        "name": object_name(obj),
        "type_name": object_type_name(obj),
        "key_attrs": filter_attrs(safe_attr_names(obj), OPERATION_KEY_ATTR_PATTERNS + STREAM_KEY_ATTR_PATTERNS),
    }


def probe_collection(value: Any) -> dict[str, Any] | None:
    """collection らしき属性を要約する。"""
    count = collection_count(value)
    if count is None:
        return None
    items = iter_collection(value)
    return {
        "count": count,
        "items": [object_reference_summary(item) for item in items],
    }


def probe_scalar_value(obj: Any, attr_name: str) -> float | str | bool | None:
    """候補属性の値をできる範囲で読む。"""
    value = safe_getattr(obj, attr_name)
    if value is None:
        value = safe_getattr(obj, f"{attr_name}Value")
    if isinstance(value, (int, float, str, bool)):
        return value

    units = SCALAR_PROBE_UNITS.get(attr_name)
    if units is not None:
        quantity_value = get_quantity(obj, attr_name, units)
        if quantity_value is not None:
            return quantity_value
    return None


def probe_attr(obj: Any, attr_name: str) -> dict[str, Any] | None:
    """候補属性を直接取得して要約する。"""
    value = safe_getattr(obj, attr_name)
    if value is None:
        scalar = probe_scalar_value(obj, attr_name)
        if scalar is None:
            return None
        return {"kind": "scalar", "value": scalar}

    if isinstance(value, (int, float, str, bool)):
        return {"kind": "scalar", "value": value}

    collection = probe_collection(value)
    if collection is not None:
        return {"kind": "collection", **collection}

    scalar = probe_scalar_value(obj, attr_name)
    if scalar is not None:
        return {"kind": "quantity", "value": scalar}

    return {"kind": "object", **object_reference_summary(value)}


def probe_operation_attrs(operation: Any) -> dict[str, Any]:
    """操作オブジェクトで重要そうな属性を直接調べる。"""
    probed: dict[str, Any] = {}
    for attr_name in COLUMN_PROBE_ATTRS:
        result = probe_attr(operation, attr_name)
        if result is not None:
            probed[attr_name] = result

    for parent_attr in ("ColumnFlowsheet", "Column", "ColumnOperation", "ColumnOp"):
        parent = safe_getattr(operation, parent_attr)
        if parent is None:
            continue
        child_results: dict[str, Any] = {}
        for child_attr in CHILD_PROBE_ATTRS + COLUMN_PROBE_ATTRS:
            result = probe_attr(parent, child_attr)
            if result is not None:
                child_results[child_attr] = result
        if child_results:
            probed[f"{parent_attr}.*"] = child_results
    return probed


def get_quantity(obj: Any, attr_name: str, units: Sequence[str]) -> float | None:
    """単一物理量を取得する。"""
    quantity = safe_getattr(obj, attr_name)
    if quantity is not None:
        for unit in units:
            try:
                if unit:
                    return float(quantity.GetValue(unit))
                return float(quantity.Value)
            except Exception:
                pass
        try:
            return float(quantity.Value)
        except Exception:
            pass

    scalar_value = safe_getattr(obj, f"{attr_name}Value")
    if isinstance(scalar_value, (int, float)):
        return float(scalar_value)
    return None


def get_values(obj: Any, attr_name: str, units: Sequence[str]) -> list[float] | None:
    """配列物理量を取得する。"""
    quantity = safe_getattr(obj, attr_name)
    if quantity is not None:
        for unit in units:
            try:
                if unit:
                    return [float(value) for value in quantity.GetValues(unit)]
                return [float(value) for value in quantity.Values]
            except Exception:
                pass
        try:
            return [float(value) for value in quantity.Values]
        except Exception:
            pass

    raw_values = safe_getattr(obj, f"{attr_name}Value")
    if raw_values is None:
        return None
    try:
        return [float(value) for value in raw_values]
    except Exception:
        return None


def component_value_map(component_names: Sequence[str], values: list[float] | None) -> dict[str, float] | None:
    """成分名と値を辞書にする。"""
    if values is None:
        return None
    if len(component_names) != len(values):
        return None
    return {name: value for name, value in zip(component_names, values, strict=True)}


def get_component_names_from_stream(stream: Any, fallback_names: Sequence[str]) -> list[str]:
    """ストリームから成分名を取得する。"""
    for candidate in (
        safe_getattr(stream, "ComponentNames"),
        safe_getattr(safe_getattr(stream, "ComponentMolarFlow"), "ComponentNames"),
    ):
        names = coerce_name_list(candidate)
        if names:
            return names
    return list(fallback_names)


def get_fluid_package(flowsheet: Any) -> Any | None:
    """FluidPackage を取得する。"""
    for attr_name in ("FluidPackage", "BasisManager", "FluidPackages"):
        value = safe_getattr(flowsheet, attr_name)
        if value is not None:
            return value
    return None


def get_case_component_names(flowsheet: Any) -> list[str]:
    """ケース内の成分名一覧を取得する。"""
    fluid_package = get_fluid_package(flowsheet)
    if fluid_package is not None:
        for attr_name in ("ComponentNames", "ComponentList"):
            names = coerce_name_list(safe_getattr(fluid_package, attr_name))
            if names:
                return names
        components = safe_getattr(fluid_package, "Components")
        names = [object_name(component) for component in iter_collection(components)]
        if names:
            return names

    material_streams = safe_getattr(flowsheet, "MaterialStreams")
    for stream in iter_collection(material_streams):
        names = coerce_name_list(safe_getattr(stream, "ComponentNames"))
        if names:
            return names
    return []


def stream_writable_candidates(stream: Any) -> list[str]:
    """書き換え候補になるストリーム属性を返す。"""
    candidates: list[str] = []
    for attr_name in ("Temperature", "Pressure", "MolarFlow", "ComponentMolarFlow", "ComponentMolarFraction"):
        if safe_getattr(stream, attr_name) is not None or safe_getattr(stream, f"{attr_name}Value") is not None:
            candidates.append(attr_name)
    return candidates


def summarize_stream(stream: Any, fallback_component_names: Sequence[str], include_attrs: bool) -> StreamSummary:
    """ストリームの要約を作る。"""
    attrs = safe_attr_names(stream)
    component_names = get_component_names_from_stream(stream, fallback_component_names)
    component_molar_flow = component_value_map(
        component_names,
        get_values(stream, "ComponentMolarFlow", ("kgmole/h", "kmol/h")),
    )
    component_molar_fraction = component_value_map(
        component_names,
        get_values(stream, "ComponentMolarFraction", ("", "fraction")),
    )
    quantities = {
        attr_name: get_quantity(stream, attr_name, units)
        for attr_name, units in QUANTITY_UNITS.items()
    }
    return StreamSummary(
        name=object_name(stream),
        type_name=object_type_name(stream),
        key_attrs=filter_attrs(attrs, STREAM_KEY_ATTR_PATTERNS),
        available_attrs=attrs if include_attrs else None,
        writable_candidates=stream_writable_candidates(stream),
        quantities=quantities,
        component_names=component_names,
        component_molar_flow=component_molar_flow,
        component_molar_fraction=component_molar_fraction,
    )


def summarize_operation(operation: Any, include_attrs: bool) -> OperationSummary:
    """操作オブジェクトの要約を作る。"""
    attrs = safe_attr_names(operation)
    linked_objects: dict[str, list[str]] = {}
    for attr_name in OPERATION_LINK_ATTRS:
        value = safe_getattr(operation, attr_name)
        items = iter_collection(value)
        if items:
            linked_objects[attr_name] = [object_name(item) for item in items]
            continue
        single_name = object_name(value) if value is not None else None
        if single_name and single_name != "<unknown>":
            linked_objects[attr_name] = [single_name]

    return OperationSummary(
        name=object_name(operation),
        type_name=object_type_name(operation),
        key_attrs=filter_attrs(attrs, OPERATION_KEY_ATTR_PATTERNS),
        available_attrs=attrs if include_attrs else None,
        linked_objects=linked_objects,
        probed_attrs=probe_operation_attrs(operation),
    )


def collect_collection_counts(flowsheet: Any) -> dict[str, int | None]:
    """代表的な collection の件数を返す。"""
    return {
        attr_name: collection_count(safe_getattr(flowsheet, attr_name))
        for attr_name in COLLECTION_ATTRS
    }


def collect_streams(flowsheet: Any, attr_name: str, component_names: Sequence[str], include_attrs: bool) -> list[StreamSummary]:
    """指定 collection のストリーム要約を返す。"""
    collection = safe_getattr(flowsheet, attr_name)
    return [summarize_stream(stream, component_names, include_attrs) for stream in iter_collection(collection)]


def collect_operations(flowsheet: Any, include_attrs: bool) -> list[OperationSummary]:
    """操作オブジェクト要約を返す。"""
    operations: list[OperationSummary] = []
    seen_names: set[str] = set()
    for attr_name in ("Operations", "OperationsCollection"):
        collection = safe_getattr(flowsheet, attr_name)
        for operation in iter_collection(collection):
            name = object_name(operation)
            if name in seen_names:
                continue
            seen_names.add(name)
            operations.append(summarize_operation(operation, include_attrs))
    return operations


def strip_none(value: Any) -> Any:
    """JSON 出力から None の項目を落とす。"""
    if isinstance(value, dict):
        return {key: strip_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [strip_none(item) for item in value]
    return value


def inspect_case(app: Any, prog_id: str, case_path: Path, include_attrs: bool) -> CaseInspection:
    """ケースを開いて構造情報を収集する。"""
    simulation_case = open_case(app=app, case_path=case_path.resolve())
    try:
        flowsheet = get_flowsheet(simulation_case)
        fluid_package = get_fluid_package(flowsheet)
        component_names = get_case_component_names(flowsheet)
        return CaseInspection(
            connected=True,
            prog_id=prog_id,
            case_path=str(case_path.resolve()),
            simulation_case=summarize_object(simulation_case, include_attrs),
            flowsheet=summarize_object(flowsheet, include_attrs),
            fluid_package=summarize_object(fluid_package, include_attrs) if fluid_package is not None else None,
            component_names=component_names,
            collection_counts=collect_collection_counts(flowsheet),
            material_streams=collect_streams(flowsheet, "MaterialStreams", component_names, include_attrs),
            energy_streams=collect_streams(flowsheet, "EnergyStreams", component_names, include_attrs),
            operations=collect_operations(flowsheet, include_attrs),
        )
    finally:
        close_case(simulation_case)


def close_case(simulation_case: Any) -> None:
    """ケースを保存せずに閉じる。"""
    close_method = safe_getattr(simulation_case, "Close")
    if not callable(close_method):
        return
    try:
        close_method(False)
    except Exception:
        try:
            close_method()
        except Exception:
            pass


def quit_hysys(app: Any | None) -> None:
    """HYSYS アプリケーションを終了する。"""
    if app is None:
        return
    quit_method = safe_getattr(app, "Quit")
    if callable(quit_method):
        try:
            quit_method()
        except Exception:
            pass


def default_output_path(case_path: Path) -> Path:
    """ケースパスから既定の診断 JSON 保存先を返す。"""
    return DEFAULT_OUTPUT_DIR / f"{case_path.stem}_inspection.json"


def write_json(payload: dict[str, Any], output_json: Path) -> None:
    """JSON を標準出力またはファイルへ出力する。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(text + "\n", encoding="utf-8")
    print(json.dumps({"output_json": str(output_json.resolve())}, ensure_ascii=False, indent=2))


def main() -> None:
    """ケース調査を実行する。"""
    args = parse_args()
    case_path = args.case_path
    if not case_path.is_absolute():
        case_path = REPO_ROOT / case_path
    if not case_path.exists():
        raise FileNotFoundError(case_path)

    pythoncom.CoInitialize()
    app: Any | None = None
    try:
        app, prog_id = connect_hysys()
        inspection = inspect_case(app=app, prog_id=prog_id, case_path=case_path, include_attrs=bool(args.include_attrs))
        payload = strip_none(asdict(inspection))
        if args.stdout:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            output_json = args.output_json
            if output_json is None:
                output_json = default_output_path(case_path)
            elif not output_json.is_absolute():
                output_json = REPO_ROOT / output_json
            write_json(payload, output_json)
    finally:
        quit_hysys(app)
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
