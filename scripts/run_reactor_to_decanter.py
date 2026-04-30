"""反応器既定ケースの出口を HYSYS の stream 1 に入れて再計算する。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Sequence

import pythoncom
import pywintypes
import win32com.client

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from process_sim.cli import default_case_payload
from process_sim.reactor.cases import DEFAULT_STYRENE_REACTOR_CASE
from process_sim.reactor.core.stream import ReactorStream
from process_sim.reactor.types import StagedAdiabaticPfrModel


CASE_PATH = REPO_ROOT / "data" / "hysys" / "decanter.hsc"
TARGET_STREAM_NAME = "1"
PROG_IDS: tuple[str, ...] = (
    "HYSYS.Application.NewInstance.V14.0",
    "HYSYS.Application.V14.0",
    "HYSYS.Application.NewInstance",
    "HYSYS.Application",
)
COMPONENT_ALIAS_MAP: dict[str, str] = {
    "styrene": "styrene",
    "styrenemonomer": "styrene",
    "eb": "eb",
    "ethylbenzene": "eb",
    "ebenzene": "eb",
    "toluene": "toluene",
    "steam": "steam",
    "water": "steam",
    "h2o": "steam",
    "benzene": "benzene",
    "co2": "co2",
    "carbondioxide": "co2",
    "ethylene": "ethylene",
    "methane": "methane",
    "co": "co",
    "carbonmonoxide": "co",
    "hydrogen": "hydrogen",
    "h2": "hydrogen",
}


@dataclass(frozen=True)
class StreamSnapshot:
    """HYSYS マテリアルストリームの取得結果。"""

    name: str
    temperature_c: float | None
    pressure_kpa: float | None
    total_molar_flow_kmol_h: float | None
    component_molar_flow_kmol_h: dict[str, float] | None
    component_molar_fraction: dict[str, float] | None


@dataclass(frozen=True)
class DiagnosticInfo:
    """切り分け用の診断情報。"""

    target_stream_requested_name: str
    target_stream_resolved_name: str
    target_stream_tag: str | None
    material_stream_names: list[str]
    component_name_sources: dict[str, list[str]]
    available_target_stream_attrs: list[str]
    available_flowsheet_attrs: list[str]
    available_fluid_package_attrs: list[str]


def connect_hysys() -> tuple[Any, str]:
    """HYSYS COM アプリケーションへ接続する。"""
    errors: list[str] = []
    for prog_id in PROG_IDS:
        try:
            app = win32com.client.Dispatch(prog_id)
            return app, prog_id
        except pywintypes.com_error as exc:
            errors.append(f"{prog_id}: {exc}")
    raise RuntimeError("HYSYS に接続できませんでした。\n" + "\n".join(errors))


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
    raise RuntimeError(f"ケースを開けませんでした: {case_path}\n" + "\n".join(errors))


def build_reactor_outlet() -> tuple[dict[str, Any], Any]:
    """反応器既定ケースを実行して出口を返す。"""
    payload = default_case_payload()
    model = StagedAdiabaticPfrModel()
    result = model.run(feed=DEFAULT_STYRENE_REACTOR_CASE.feed, conditions=DEFAULT_STYRENE_REACTOR_CASE.conditions)
    return payload, result


def get_flowsheet(simulation_case: Any) -> Any:
    """Flowsheet を返す。"""
    for attr_name in ("Flowsheet", "MainFlowsheet"):
        flowsheet = getattr(simulation_case, attr_name, None)
        if flowsheet is not None:
            return flowsheet
    raise RuntimeError("Flowsheet を取得できませんでした。")


def get_material_stream(flowsheet: Any, stream_name: str) -> Any:
    """指定名のマテリアルストリームを取得する。"""
    material_streams = getattr(flowsheet, "MaterialStreams", None)
    if material_streams is None:
        raise RuntimeError("MaterialStreams を取得できませんでした。")

    errors: list[str] = []
    for accessor in (
        lambda: material_streams.Item(stream_name),
        lambda: material_streams(stream_name),
    ):
        try:
            return accessor()
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError(f"stream {stream_name} を取得できませんでした。\n" + "\n".join(errors))


def get_component_names(stream: Any, flowsheet: Any) -> tuple[list[str], dict[str, list[str]]]:
    """HYSYS 側の成分名一覧を返す。"""
    fluid_package = getattr(flowsheet, "FluidPackage", None)
    source_map = {
        "stream.ComponentNames": coerce_name_list(getattr(stream, "ComponentNames", None)),
        "stream.ComponentMolarFlow.ComponentNames": coerce_name_list(
            getattr(getattr(stream, "ComponentMolarFlow", None), "ComponentNames", None)
        ),
        "flowsheet.FluidPackage.ComponentNames": coerce_name_list(
            getattr(fluid_package, "ComponentNames", None)
        ),
        "flowsheet.FluidPackage.ComponentList": coerce_name_list(
            getattr(fluid_package, "ComponentList", None)
        ),
        "flowsheet.FluidPackage.Components": get_component_collection_names(
            getattr(fluid_package, "Components", None)
        ),
    }
    for names in source_map.values():
        if names:
            return names, source_map
    raise RuntimeError("成分名一覧を取得できませんでした。")


def coerce_name_list(value: Any) -> list[str]:
    """COM 由来の名前一覧を Python list[str] に変換する。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return [str(item) for item in value]
    except TypeError:
        return []


def normalized_component_name(name: str) -> str:
    """成分名比較用に正規化する。"""
    return "".join(character for character in name.lower() if character.isalnum())


def reactor_component_flow(component_name: str, stream: ReactorStream) -> float:
    """HYSYS 成分名に対応する反応器出口流量を返す。"""
    field_name = COMPONENT_ALIAS_MAP.get(normalized_component_name(component_name))
    if field_name is None:
        raise RuntimeError(f"HYSYS 成分 {component_name} を反応器成分へ対応付けできませんでした。")
    return float(getattr(stream, field_name))


def set_quantity(
    stream: Any,
    attr_name: str,
    value: float,
    units: Sequence[str],
) -> None:
    """温度や圧力などの単一物理量を書き込む。"""
    quantity = getattr(stream, attr_name, None)
    errors: list[str] = []
    if quantity is not None:
        for unit in units:
            try:
                quantity.SetValue(value, unit)
                return
            except Exception as exc:
                errors.append(f"{attr_name}.SetValue({unit}): {exc}")
        try:
            quantity.Value = value
            return
        except Exception as exc:
            errors.append(f"{attr_name}.Value: {exc}")

    scalar_attr_name = f"{attr_name}Value"
    if hasattr(stream, scalar_attr_name):
        try:
            setattr(stream, scalar_attr_name, value)
            return
        except Exception as exc:
            errors.append(f"{scalar_attr_name}: {exc}")

    raise RuntimeError(f"{attr_name} を書き込めませんでした。\n" + "\n".join(errors))


def set_component_molar_flows(stream: Any, component_names: Sequence[str], reactor_stream: ReactorStream) -> None:
    """成分モル流量を HYSYS ストリームへ書き込む。"""
    values = [reactor_component_flow(name, reactor_stream) for name in component_names]
    quantity = getattr(stream, "ComponentMolarFlow", None)
    errors: list[str] = []
    if quantity is not None:
        for unit in ("kgmole/h", "kmol/h"):
            try:
                quantity.SetValues(values, unit)
                return
            except Exception as exc:
                errors.append(f"ComponentMolarFlow.SetValues({unit}): {exc}")

    if hasattr(stream, "ComponentMolarFlowValue"):
        try:
            stream.ComponentMolarFlowValue = values
            return
        except Exception as exc:
            errors.append(f"ComponentMolarFlowValue: {exc}")

    raise RuntimeError("成分モル流量を書き込めませんでした。\n" + "\n".join(errors))


def get_quantity(stream: Any, attr_name: str, units: Sequence[str]) -> float | None:
    """温度や圧力などの単一物理量を読み取る。"""
    quantity = getattr(stream, attr_name, None)
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

    scalar_attr_name = f"{attr_name}Value"
    value = getattr(stream, scalar_attr_name, None)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def get_component_molar_flows(stream: Any) -> list[float] | None:
    """成分モル流量一覧を読み取る。"""
    quantity = getattr(stream, "ComponentMolarFlow", None)
    if quantity is not None:
        for unit in ("kgmole/h", "kmol/h"):
            try:
                return [float(value) for value in quantity.GetValues(unit)]
            except Exception:
                pass

    values = getattr(stream, "ComponentMolarFlowValue", None)
    if values is None:
        return None
    try:
        return [float(value) for value in values]
    except TypeError:
        return None


def get_component_molar_fractions(stream: Any) -> list[float] | None:
    """成分モル分率一覧を読み取る。"""
    quantity = getattr(stream, "ComponentMolarFraction", None)
    if quantity is not None:
        try:
            return [float(value) for value in quantity.Values]
        except Exception:
            pass
        for unit in ("", "fraction"):
            try:
                return [float(value) for value in quantity.GetValues(unit)]
            except Exception:
                pass

    values = getattr(stream, "ComponentMolarFractionValue", None)
    if values is None:
        return None
    try:
        return [float(value) for value in values]
    except TypeError:
        return None


def iter_material_streams(flowsheet: Any) -> Iterable[Any]:
    """MaterialStreams を順に返す。"""
    material_streams = getattr(flowsheet, "MaterialStreams", None)
    if material_streams is None:
        raise RuntimeError("MaterialStreams を取得できませんでした。")

    count = int(material_streams.Count)
    for start_index in (0, 1):
        items: list[Any] = []
        try:
            for index in range(start_index, start_index + count):
                items.append(material_streams.Item(index))
        except Exception:
            continue
        if len(items) == count:
            return items
    raise RuntimeError("MaterialStreams を列挙できませんでした。")


def stream_name(stream: Any) -> str:
    """ストリーム名を返す。"""
    for attr_name in ("Name", "Tag"):
        value = getattr(stream, attr_name, None)
        if isinstance(value, str) and value:
            return value
    return "<unknown>"


def safe_attr_names(obj: Any) -> list[str]:
    """dir の結果を安全に文字列化する。"""
    try:
        return sorted(name for name in dir(obj) if not name.startswith("_"))
    except Exception:
        return []


def collect_material_stream_names(flowsheet: Any) -> list[str]:
    """ケース内のマテリアルストリーム名一覧を返す。"""
    return [stream_name(stream) for stream in iter_material_streams(flowsheet)]


def iter_collection_items(collection: Any) -> list[Any]:
    """COM collection を Python list に変換する。"""
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


def component_object_name(component: Any) -> str | None:
    """成分オブジェクトから名称を取り出す。"""
    for attr_name in ("Name", "TaggedName", "TypeName", "name"):
        value = getattr(component, attr_name, None)
        if isinstance(value, str) and value:
            return value
    return None


def get_component_collection_names(collection: Any) -> list[str]:
    """Component collection から成分名一覧を返す。"""
    names = [component_object_name(component) for component in iter_collection_items(collection)]
    return [name for name in names if name]


def build_diagnostic_info(
    flowsheet: Any,
    target_stream: Any,
    source_map: dict[str, list[str]],
) -> DiagnosticInfo:
    """切り分けに必要な情報をまとめる。"""
    fluid_package = getattr(flowsheet, "FluidPackage", None)
    tag_value = getattr(target_stream, "Tag", None)
    return DiagnosticInfo(
        target_stream_requested_name=TARGET_STREAM_NAME,
        target_stream_resolved_name=stream_name(target_stream),
        target_stream_tag=tag_value if isinstance(tag_value, str) else None,
        material_stream_names=collect_material_stream_names(flowsheet),
        component_name_sources=source_map,
        available_target_stream_attrs=safe_attr_names(target_stream),
        available_flowsheet_attrs=safe_attr_names(flowsheet),
        available_fluid_package_attrs=safe_attr_names(fluid_package) if fluid_package is not None else [],
    )


def component_value_map(component_names: Sequence[str], component_values: list[float] | None) -> dict[str, float] | None:
    """成分名と値の一覧を辞書化する。"""
    if component_values is None:
        return None
    if len(component_names) != len(component_values):
        return None
    return {
        name: value
        for name, value in zip(component_names, component_values, strict=True)
    }


def collect_stream_snapshots(flowsheet: Any) -> list[StreamSnapshot]:
    """マテリアルストリームを JSON 向けに記録する。"""
    snapshots: list[StreamSnapshot] = []
    fluid_package_component_names = get_component_collection_names(
        getattr(getattr(flowsheet, "FluidPackage", None), "Components", None)
    )
    for stream in iter_material_streams(flowsheet):
        component_names = coerce_name_list(getattr(stream, "ComponentNames", None))
        if not component_names:
            component_names = fluid_package_component_names

        component_flow = component_value_map(component_names, get_component_molar_flows(stream))
        component_fraction = component_value_map(component_names, get_component_molar_fractions(stream))
        snapshots.append(
            StreamSnapshot(
                name=stream_name(stream),
                temperature_c=get_quantity(stream, "Temperature", ("C", "degC")),
                pressure_kpa=get_quantity(stream, "Pressure", ("kPa",)),
                total_molar_flow_kmol_h=get_quantity(stream, "MolarFlow", ("kgmole/h", "kmol/h")),
                component_molar_flow_kmol_h=component_flow,
                component_molar_fraction=component_fraction,
            )
        )
    return snapshots


def main() -> None:
    """反応器出口を stream 1 に渡して結果を出力する。"""
    payload, reactor_result = build_reactor_outlet()
    pythoncom.CoInitialize()
    app: Any | None = None
    simulation_case: Any | None = None
    try:
        app, prog_id = connect_hysys()
        try:
            app.Visible = True
        except Exception:
            pass

        simulation_case = open_case(app, CASE_PATH.resolve())
        flowsheet = get_flowsheet(simulation_case)
        target_stream = get_material_stream(flowsheet, TARGET_STREAM_NAME)
        source_map: dict[str, list[str]] = {}
        try:
            component_names, source_map = get_component_names(target_stream, flowsheet)
        except RuntimeError as exc:
            diagnostic = build_diagnostic_info(flowsheet, target_stream, source_map)
            error_output = {
                "connected": True,
                "prog_id": prog_id,
                "case_path": str(CASE_PATH.resolve()),
                "error": str(exc),
                "diagnostic": asdict(diagnostic),
            }
            print(json.dumps(error_output, ensure_ascii=False, indent=2))
            return

        set_quantity(target_stream, "Temperature", reactor_result.outlet.temperature_c, ("C", "degC"))
        set_quantity(target_stream, "Pressure", reactor_result.outlet.pressure_kpa, ("kPa",))
        set_component_molar_flows(target_stream, component_names, reactor_result.outlet.stream)

        snapshots = collect_stream_snapshots(flowsheet)
        diagnostic = build_diagnostic_info(flowsheet, target_stream, source_map)
        output = {
            "connected": True,
            "prog_id": prog_id,
            "case_path": str(CASE_PATH.resolve()),
            "target_stream": TARGET_STREAM_NAME,
            "target_component_names": component_names,
            "diagnostic": asdict(diagnostic),
            "reactor_input": payload,
            "reactor_outlet": asdict(reactor_result.outlet),
            "material_streams": [asdict(snapshot) for snapshot in snapshots],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    finally:
        if simulation_case is not None:
            close_method = getattr(simulation_case, "Close", None)
            if callable(close_method):
                try:
                    close_method(False)
                except Exception:
                    try:
                        close_method()
                    except Exception:
                        pass
        if app is not None:
            quit_method = getattr(app, "Quit", None)
            if callable(quit_method):
                try:
                    quit_method()
                except Exception:
                    pass
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
