"""HYSYS COM IO for the separation section."""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
import time
from types import TracebackType
from typing import TYPE_CHECKING, Any, Generator, Sequence

import pythoncom
import pywintypes
import win32com.client

from process_sim.plant.models import PLANT_STREAM_NAMES, PlantStreamRecord
from process_sim.reactor.core.stream import ReactorStream

if TYPE_CHECKING:
    from process_sim.plant.hysys_controls import (
        DistillationRefluxRatioWriteSpec,
        FullMaterialStreamWriteSpec,
        HysysControlPlan,
        OperationWriteSpec,
        PressureMaterialStreamWriteSpec,
        TemperatureMaterialStreamWriteSpec,
    )


PROG_IDS: tuple[str, ...] = (
    "HYSYS.Application.NewInstance.V14.0",
    "HYSYS.Application.V14.0",
    "HYSYS.Application.NewInstance",
    "HYSYS.Application",
)

HYSYS_COMPONENT_TO_REACTOR_FIELD: dict[str, str] = {
    "methane": "methane",
    "ethylene": "ethylene",
    "styrene": "styrene",
    "styrenemonomer": "styrene",
    "ebenzene": "eb",
    "ethylbenzene": "eb",
    "eb": "eb",
    "toluene": "toluene",
    "benzene": "benzene",
    "co2": "co2",
    "carbondioxide": "co2",
    "co": "co",
    "carbonmonoxide": "co",
    "h2o": "steam",
    "water": "steam",
    "steam": "steam",
    "hydrogen": "hydrogen",
    "h2": "hydrogen",
}

TEMPERATURE_READBACK_ABS_TOLERANCE_C = 1.0e-3
PRESSURE_READBACK_ABS_TOLERANCE_KPA = 1.0e-3
FLOW_READBACK_ABS_TOLERANCE_KMOL_H = 1.0e-6
FLOW_READBACK_REL_TOLERANCE = 1.0e-6
REFLUX_RATIO_READBACK_ABS_TOLERANCE = 1.0e-4
REFLUX_RATIO_SPEC_NAME = "Reflux Ratio"
REFLUX_RATIO_GOAL_ATTR_NAME = "GoalValue"


def normalized_component_name(name: str) -> str:
    """成分名比較用に正規化する。"""
    return "".join(character for character in name.lower() if character.isalnum())


def connect_hysys() -> tuple[Any, str]:
    """HYSYS COM アプリケーションへ接続する。"""
    errors: list[str] = []
    for prog_id in PROG_IDS:
        try:
            return win32com.client.Dispatch(prog_id), prog_id
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


def get_flowsheet(simulation_case: Any) -> Any:
    """SimulationCase から flowsheet を取得する。"""
    for attr_name in ("Flowsheet", "MainFlowsheet"):
        flowsheet = getattr(simulation_case, attr_name, None)
        if flowsheet is not None:
            return flowsheet
    raise RuntimeError("Flowsheet を取得できませんでした。")


def get_material_stream(flowsheet: Any, stream_name: str) -> Any:
    """指定名の material stream を取得する。"""
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


def get_energy_stream(flowsheet: Any, stream_name: str) -> Any:
    """指定名の energy stream を取得する。"""
    energy_streams = getattr(flowsheet, "EnergyStreams", None)
    if energy_streams is None:
        raise RuntimeError("EnergyStreams を取得できませんでした。")

    errors: list[str] = []
    for accessor in (
        lambda: energy_streams.Item(stream_name),
        lambda: energy_streams(stream_name),
    ):
        try:
            return accessor()
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError(f"energy stream {stream_name} を取得できませんでした。\n" + "\n".join(errors))


def get_operation(flowsheet: Any, operation_name: str) -> Any:
    """指定名の operation を取得する。"""
    operations = getattr(flowsheet, "Operations", None)
    if operations is None:
        raise RuntimeError("Operations を取得できませんでした。")

    errors: list[str] = []
    for accessor in (
        lambda: operations.Item(operation_name),
        lambda: operations(operation_name),
    ):
        try:
            return accessor()
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError(f"operation {operation_name} を取得できませんでした。\n" + "\n".join(errors))


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


def object_name(obj: Any) -> str:
    """COM object の表示名を返す。"""
    for attr_name in ("Name", "TaggedName", "TypeName", "name"):
        value = getattr(obj, attr_name, None)
        if isinstance(value, str) and value:
            return value
    return "<unknown>"


def get_component_collection_names(collection: Any) -> list[str]:
    """Component collection から成分名一覧を返す。"""
    names = [component_object_name(component) for component in iter_collection_items(collection)]
    return [name for name in names if name]


def get_component_names(stream: Any, flowsheet: Any) -> list[str]:
    """stream または fluid package から成分名一覧を取得する。"""
    stream_component_names = coerce_name_list(getattr(stream, "ComponentNames", None))
    if stream_component_names:
        return stream_component_names

    fluid_package = getattr(flowsheet, "FluidPackage", None)
    names = get_component_collection_names(getattr(fluid_package, "Components", None))
    if names:
        return names

    raise RuntimeError("成分名一覧を取得できませんでした。")


def reactor_component_flow(component_name: str, stream: ReactorStream) -> float:
    """HYSYS 成分名に対応する反応器出口流量を返す。"""
    field_name = HYSYS_COMPONENT_TO_REACTOR_FIELD.get(normalized_component_name(component_name))
    if field_name is None:
        raise RuntimeError(f"HYSYS 成分 {component_name} を反応器成分へ対応付けできませんでした。")
    return float(getattr(stream, field_name))


def set_quantity(stream: Any, attr_name: str, value: float, units: Sequence[str]) -> None:
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
    """成分モル流量を HYSYS stream へ書き込む。"""
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


def set_component_molar_flows_from_mapping(
    stream: Any,
    component_names: Sequence[str],
    component_flows_kmol_h: dict[str, float],
) -> None:
    """成分モル流量 mapping を HYSYS stream へ書き込む。"""
    validate_component_flow_mapping(component_names=component_names, component_flows_kmol_h=component_flows_kmol_h)
    normalized_flows = normalized_component_flow_mapping(component_flows_kmol_h)
    values = [
        component_flow_for_hysys_component(component_name=name, normalized_flows=normalized_flows)
        for name in component_names
    ]
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


def validate_component_flow_mapping(
    component_names: Sequence[str],
    component_flows_kmol_h: dict[str, float],
) -> None:
    """書き込み成分が HYSYS 成分名へ対応できることを確認する。"""
    unmatched_keys = [
        key
        for key in component_flows_kmol_h
        if not any(component_key_matches_hysys_component(key, component_name) for component_name in component_names)
    ]
    if unmatched_keys:
        raise RuntimeError(f"HYSYS 成分へ対応できない書き込み成分があります: {', '.join(unmatched_keys)}")


def component_key_matches_hysys_component(component_key: str, hysys_component_name: str) -> bool:
    """Python 側成分キーが HYSYS 成分に対応するか判定する。"""
    normalized_key = normalized_component_name(component_key)
    normalized_hysys_name = normalized_component_name(hysys_component_name)
    if normalized_key == normalized_hysys_name:
        return True
    reactor_field = HYSYS_COMPONENT_TO_REACTOR_FIELD.get(normalized_hysys_name)
    return reactor_field == normalized_key


def normalized_component_flow_mapping(component_flows_kmol_h: dict[str, float]) -> dict[str, float]:
    """成分流量 mapping の key を正規化する。"""
    return {
        normalized_component_name(component_name): float(flow_kmol_h)
        for component_name, flow_kmol_h in component_flows_kmol_h.items()
    }


def component_flow_for_hysys_component(component_name: str, normalized_flows: dict[str, float]) -> float:
    """HYSYS 成分名に対応する書き込み流量を返す。"""
    normalized_name = normalized_component_name(component_name)
    direct_value = normalized_flows.get(normalized_name)
    if direct_value is not None:
        return direct_value
    reactor_field = HYSYS_COMPONENT_TO_REACTOR_FIELD.get(normalized_name)
    if reactor_field is None:
        return 0.0
    return normalized_flows.get(reactor_field, 0.0)


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


def get_vapor_fraction(stream: Any) -> float | None:
    """material stream の vapor fraction を読み取る。"""
    return get_quantity(stream, "VapourFraction", ("", "fraction"))


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


def component_value_map(component_names: Sequence[str], component_values: list[float] | None) -> dict[str, float]:
    """成分名と値の一覧を辞書化する。"""
    if component_values is None or len(component_names) != len(component_values):
        return {}
    return dict(zip(component_names, component_values, strict=True))


def read_material_stream_record(flowsheet: Any, stream_name: str) -> PlantStreamRecord:
    """HYSYS material stream を PlantStreamRecord に変換する。"""
    stream = get_material_stream(flowsheet, stream_name)
    component_names = get_component_names(stream, flowsheet)
    return PlantStreamRecord(
        name=stream_name,
        temperature_c=get_quantity(stream, "Temperature", ("C", "degC")),
        pressure_kpa=get_quantity(stream, "Pressure", ("kPa",)),
        total_molar_flow_kmol_h=get_quantity(stream, "MolarFlow", ("kgmole/h", "kmol/h")),
        component_molar_flow_kmol_h=component_value_map(component_names, get_component_molar_flows(stream)),
        component_molar_fraction=component_value_map(component_names, get_component_molar_fractions(stream)),
    )


def write_full_material_stream_spec(flowsheet: Any, spec: "FullMaterialStreamWriteSpec") -> None:
    """Material stream へ組成、温度、圧力を書き込む。"""
    stream = get_material_stream(flowsheet, spec.stream_name)
    component_names = get_component_names(stream, flowsheet)
    set_quantity(stream, "Temperature", spec.temperature_c, ("C", "degC"))
    set_quantity(stream, "Pressure", spec.pressure_kpa, ("kPa",))
    set_component_molar_flows_from_mapping(
        stream=stream,
        component_names=component_names,
        component_flows_kmol_h=spec.component_molar_flow.values,
    )


def write_pressure_material_stream_spec(flowsheet: Any, spec: "PressureMaterialStreamWriteSpec") -> None:
    """Material stream へ圧力だけを書き込む。"""
    stream = get_material_stream(flowsheet, spec.stream_name)
    set_quantity(stream, "Pressure", spec.pressure_kpa, ("kPa",))


def write_temperature_material_stream_spec(flowsheet: Any, spec: "TemperatureMaterialStreamWriteSpec") -> None:
    """Material stream へ温度だけを書き込む。"""
    stream = get_material_stream(flowsheet, spec.stream_name)
    set_quantity(stream, "Temperature", spec.temperature_c, ("C", "degC"))


def write_operation_spec(flowsheet: Any, spec: "OperationWriteSpec") -> None:
    """HYSYS operation へ単一操作変数を書き込む。"""
    operation = get_operation(flowsheet, spec.operation_name)
    set_quantity(operation, spec.variable_name, spec.value, (spec.unit,))


def write_distillation_reflux_ratio_spec(
    flowsheet: Any,
    spec: "DistillationRefluxRatioWriteSpec",
) -> None:
    """蒸留塔 Reflux Ratio spec の GoalValue を書き込む。"""
    reflux_spec = get_distillation_reflux_ratio_spec(flowsheet=flowsheet, operation_name=spec.operation_name)
    try:
        setattr(reflux_spec, REFLUX_RATIO_GOAL_ATTR_NAME, spec.reflux_ratio)
    except Exception as exc:
        raise RuntimeError(
            f"{spec.operation_name}.{REFLUX_RATIO_SPEC_NAME}.{REFLUX_RATIO_GOAL_ATTR_NAME} "
            f"を書き込めませんでした: {exc}"
        ) from exc


def get_distillation_reflux_ratio_spec(flowsheet: Any, operation_name: str) -> Any:
    """蒸留塔 operation から Reflux Ratio spec を取得する。"""
    operation = get_operation(flowsheet, operation_name)
    column_flowsheet = getattr(operation, "ColumnFlowsheet", None)
    if column_flowsheet is None:
        raise RuntimeError(f"{operation_name}.ColumnFlowsheet を取得できませんでした。")
    specifications = getattr(column_flowsheet, "Specifications", None)
    if specifications is None:
        raise RuntimeError(f"{operation_name}.ColumnFlowsheet.Specifications を取得できませんでした。")
    for specification in iter_collection_items(specifications):
        if object_name(specification) == REFLUX_RATIO_SPEC_NAME:
            return specification
    names = ", ".join(object_name(specification) for specification in iter_collection_items(specifications))
    raise RuntimeError(f"{operation_name} の {REFLUX_RATIO_SPEC_NAME} spec を取得できませんでした: {names}")


def read_distillation_reflux_ratio(flowsheet: Any, operation_name: str) -> float:
    """蒸留塔 ColumnFlowsheet の還流比を読む。"""
    operation = get_operation(flowsheet, operation_name)
    column_flowsheet = getattr(operation, "ColumnFlowsheet", None)
    if column_flowsheet is None:
        raise RuntimeError(f"{operation_name}.ColumnFlowsheet を取得できませんでした。")
    value = getattr(column_flowsheet, "RefluxRatio", None)
    if isinstance(value, (int, float)):
        return float(value)
    read_value = get_quantity(column_flowsheet, "RefluxRatio", ("",))
    if read_value is None:
        raise RuntimeError(f"{operation_name}.ColumnFlowsheet.RefluxRatio を読み取れませんでした。")
    return read_value


def apply_hysys_control_plan(
    simulation_case: Any,
    plan: "HysysControlPlan",
) -> dict[str, PlantStreamRecord]:
    """HYSYS case へ操作条件を書き込み、readback 検証結果を返す。"""
    flowsheet = get_flowsheet(simulation_case)
    for spec in plan.full_material_streams:
        write_full_material_stream_spec(flowsheet=flowsheet, spec=spec)
    for spec in plan.pressure_material_streams:
        write_pressure_material_stream_spec(flowsheet=flowsheet, spec=spec)
    for spec in plan.temperature_material_streams:
        write_temperature_material_stream_spec(flowsheet=flowsheet, spec=spec)
    for spec in plan.operations:
        write_operation_spec(flowsheet=flowsheet, spec=spec)
    for spec in plan.distillation_reflux_ratios:
        write_distillation_reflux_ratio_spec(flowsheet=flowsheet, spec=spec)

    wait_for_hysys_calculation(simulation_case)
    readback = readback_hysys_control_plan(simulation_case=simulation_case, plan=plan)
    validate_hysys_control_readback(plan=plan, readback=readback)
    validate_distillation_reflux_ratio_readback(simulation_case=simulation_case, plan=plan)
    return readback


def readback_hysys_control_plan(
    simulation_case: Any,
    plan: "HysysControlPlan",
) -> dict[str, PlantStreamRecord]:
    """書き込み対象 stream を HYSYS から読み直す。"""
    flowsheet = get_flowsheet(simulation_case)
    stream_names = sorted(
        {
            spec.stream_name
            for spec in (
                *plan.full_material_streams,
                *plan.pressure_material_streams,
                *plan.temperature_material_streams,
            )
        }
    )
    return {
        stream_name: read_material_stream_record(flowsheet=flowsheet, stream_name=stream_name)
        for stream_name in stream_names
    }


def validate_hysys_control_readback(
    plan: "HysysControlPlan",
    readback: dict[str, PlantStreamRecord],
) -> None:
    """書き込み plan と readback の一致を確認する。"""
    for spec in plan.full_material_streams:
        record = require_readback_stream(readback=readback, stream_name=spec.stream_name)
        validate_temperature(
            actual=record.temperature_c,
            expected=spec.temperature_c,
            label=f"{spec.stream_name} temperature",
        )
        validate_pressure(
            actual=record.pressure_kpa,
            expected=spec.pressure_kpa,
            label=f"{spec.stream_name} pressure",
        )
        validate_component_molar_flow_readback(
            record=record,
            expected_flows=spec.component_molar_flow.values,
        )
    for spec in plan.pressure_material_streams:
        record = require_readback_stream(readback=readback, stream_name=spec.stream_name)
        validate_pressure(
            actual=record.pressure_kpa,
            expected=spec.pressure_kpa,
            label=f"{spec.stream_name} pressure",
        )
    for spec in plan.temperature_material_streams:
        record = require_readback_stream(readback=readback, stream_name=spec.stream_name)
        validate_temperature(
            actual=record.temperature_c,
            expected=spec.temperature_c,
            label=f"{spec.stream_name} temperature",
        )


def validate_distillation_reflux_ratio_readback(
    simulation_case: Any,
    plan: "HysysControlPlan",
) -> None:
    """蒸留塔還流比 readback の一致を確認する。"""
    if not plan.distillation_reflux_ratios:
        return
    flowsheet = get_flowsheet(simulation_case)
    for spec in plan.distillation_reflux_ratios:
        actual = read_distillation_reflux_ratio(flowsheet=flowsheet, operation_name=spec.operation_name)
        if abs(actual - spec.reflux_ratio) > REFLUX_RATIO_READBACK_ABS_TOLERANCE:
            raise RuntimeError(
                f"{spec.operation_name} reflux ratio readback mismatch: "
                f"expected={spec.reflux_ratio}, actual={actual}"
            )


def require_readback_stream(
    readback: dict[str, PlantStreamRecord],
    stream_name: str,
) -> PlantStreamRecord:
    """readback された必須 stream を返す。"""
    record = readback.get(stream_name)
    if record is None:
        raise RuntimeError(f"{stream_name} readback is missing")
    return record


def validate_temperature(actual: float | None, expected: float, label: str) -> None:
    """温度 readback の一致を確認する。"""
    if actual is None:
        raise RuntimeError(f"{label} readback is missing")
    if abs(actual - expected) > TEMPERATURE_READBACK_ABS_TOLERANCE_C:
        raise RuntimeError(f"{label} readback mismatch: expected={expected}, actual={actual}")


def validate_pressure(actual: float | None, expected: float, label: str) -> None:
    """圧力 readback の一致を確認する。"""
    if actual is None:
        raise RuntimeError(f"{label} readback is missing")
    if abs(actual - expected) > PRESSURE_READBACK_ABS_TOLERANCE_KPA:
        raise RuntimeError(f"{label} readback mismatch: expected={expected}, actual={actual}")


def validate_component_molar_flow_readback(
    record: PlantStreamRecord,
    expected_flows: dict[str, float],
) -> None:
    """成分モル流量 readback の一致を確認する。"""
    normalized_expected = normalized_component_flow_mapping(expected_flows)
    for component_name, actual_flow in record.component_molar_flow_kmol_h.items():
        expected_flow = component_flow_for_hysys_component(
            component_name=component_name,
            normalized_flows=normalized_expected,
        )
        if not flows_close(actual=actual_flow, expected=expected_flow):
            raise RuntimeError(
                f"{record.name} {component_name} flow readback mismatch: "
                f"expected={expected_flow}, actual={actual_flow}"
            )


def flows_close(actual: float, expected: float) -> bool:
    """成分モル流量の一致判定を返す。"""
    tolerance = FLOW_READBACK_ABS_TOLERANCE_KMOL_H + FLOW_READBACK_REL_TOLERANCE * abs(expected)
    return abs(actual - expected) <= tolerance


def write_reactor_outlet(
    flowsheet: Any,
    stream_name: str,
    reactor_stream: ReactorStream,
    temperature_c: float,
    pressure_kpa: float,
) -> None:
    """反応器出口を HYSYS 側の入口 stream に書き込む。"""
    stream = get_material_stream(flowsheet, stream_name)
    component_names = get_component_names(stream, flowsheet)
    set_quantity(stream, "Temperature", temperature_c, ("C", "degC"))
    set_quantity(stream, "Pressure", pressure_kpa, ("kPa",))
    set_component_molar_flows(stream, component_names, reactor_stream)


def wait_for_hysys_calculation(simulation_case: Any) -> None:
    """HYSYS の計算更新を促す。完了判定は HYSYS 側 API の範囲に留める。"""
    solver = getattr(simulation_case, "Solver", None)
    if solver is None:
        return

    can_solve = getattr(solver, "CanSolve", None)
    if isinstance(can_solve, bool) and not can_solve:
        try:
            solver.CanSolve = True
        except Exception:
            pass

    for method_name in ("Solve", "Run"):
        method = getattr(solver, method_name, None)
        if callable(method):
            try:
                method()
                break
            except Exception:
                pass

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        is_solving = getattr(solver, "IsSolving", None)
        if not isinstance(is_solving, bool) or not is_solving:
            return
        time.sleep(0.2)


@contextmanager
def hysys_case(case_path: Path, visible: bool) -> Generator[tuple[Any, Any, str]]:
    """HYSYS case を開いて、終了時に閉じる。"""
    pythoncom.CoInitialize()
    app: Any | None = None
    simulation_case: Any | None = None
    try:
        hysys_app, prog_id = connect_hysys()
        app = hysys_app
        try:
            hysys_app.Visible = visible
        except Exception:
            pass

        simulation_case = open_case(hysys_app, case_path)
        yield hysys_app, simulation_case, prog_id
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


def run_hysys_separation_once(
    case_path: Path,
    reactor_stream: ReactorStream,
    temperature_c: float,
    pressure_kpa: float,
    inlet_stream_name: str = "reactor_outlet",
    output_stream_names: Sequence[str] = PLANT_STREAM_NAMES,
    visible: bool = True,
) -> tuple[dict[str, PlantStreamRecord], dict[str, Any]]:
    """反応器出口を書き込み、固定 stream の記録を返す。"""
    resolved_case_path = case_path.resolve()
    with hysys_case(resolved_case_path, visible=visible) as (_, simulation_case, prog_id):
        return run_hysys_separation_with_open_case(
            simulation_case=simulation_case,
            prog_id=prog_id,
            case_path=resolved_case_path,
            reactor_stream=reactor_stream,
            temperature_c=temperature_c,
            pressure_kpa=pressure_kpa,
            inlet_stream_name=inlet_stream_name,
            output_stream_names=output_stream_names,
        )


def run_hysys_separation_with_open_case(
    simulation_case: Any,
    prog_id: str,
    case_path: Path,
    reactor_stream: ReactorStream,
    temperature_c: float,
    pressure_kpa: float,
    inlet_stream_name: str = "reactor_outlet",
    output_stream_names: Sequence[str] = PLANT_STREAM_NAMES,
) -> tuple[dict[str, PlantStreamRecord], dict[str, Any]]:
    """開いている HYSYS case に反応器出口を書き込み、固定 stream の記録を返す。"""
    resolved_case_path = case_path.resolve()
    flowsheet = get_flowsheet(simulation_case)
    write_reactor_outlet(
        flowsheet=flowsheet,
        stream_name=inlet_stream_name,
        reactor_stream=reactor_stream,
        temperature_c=temperature_c,
        pressure_kpa=pressure_kpa,
    )
    wait_for_hysys_calculation(simulation_case)
    records = {
        stream_name: read_material_stream_record(flowsheet, stream_name)
        for stream_name in output_stream_names
    }
    metadata = {
        "prog_id": prog_id,
        "hysys_case_path": str(resolved_case_path),
        "hysys_inlet_stream": inlet_stream_name,
    }
    return records, metadata


class HysysSeparationSession:
    """HYSYS case を開いたまま複数回の分離計算に再利用する。"""

    def __init__(
        self,
        case_path: Path,
        visible: bool = False,
        inlet_stream_name: str = "reactor_outlet",
        output_stream_names: Sequence[str] = PLANT_STREAM_NAMES,
    ) -> None:
        self.case_path = case_path.resolve()
        self.visible = visible
        self.inlet_stream_name = inlet_stream_name
        self.output_stream_names = tuple(output_stream_names)
        self._case_context: AbstractContextManager[tuple[Any, Any, str]] | None = None
        self._simulation_case: Any | None = None
        self._prog_id: str | None = None

    def __enter__(self) -> HysysSeparationSession:
        """HYSYS case を開く。"""
        self._case_context = hysys_case(self.case_path, visible=self.visible)
        _, simulation_case, prog_id = self._case_context.__enter__()
        self._simulation_case = simulation_case
        self._prog_id = prog_id
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """HYSYS case を閉じる。"""
        if self._case_context is None:
            return None
        try:
            return self._case_context.__exit__(exc_type, exc, traceback)
        finally:
            self._case_context = None
            self._simulation_case = None
            self._prog_id = None

    def run(
        self,
        reactor_stream: ReactorStream,
        temperature_c: float,
        pressure_kpa: float,
    ) -> tuple[dict[str, PlantStreamRecord], dict[str, Any]]:
        """開いている HYSYS case で1回分の分離計算を行う。"""
        if self._simulation_case is None or self._prog_id is None:
            raise RuntimeError("HYSYS session is not open")
        records, metadata = run_hysys_separation_with_open_case(
            simulation_case=self._simulation_case,
            prog_id=self._prog_id,
            case_path=self.case_path,
            reactor_stream=reactor_stream,
            temperature_c=temperature_c,
            pressure_kpa=pressure_kpa,
            inlet_stream_name=self.inlet_stream_name,
            output_stream_names=self.output_stream_names,
        )
        return records, {**metadata, "hysys_session_reused": True}

    @property
    def simulation_case(self) -> Any:
        """開いている HYSYS case を application boundary 内で返す。"""
        if self._simulation_case is None:
            raise RuntimeError("HYSYS session is not open")
        return self._simulation_case
