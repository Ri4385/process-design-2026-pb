"""HYSYS COM IO for the separation section."""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any, Generator, Sequence

import pythoncom
import pywintypes
import win32com.client

from process_sim.plant.models import PLANT_STREAM_NAMES, PlantStreamRecord
from process_sim.reactor.core.stream import ReactorStream


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
                return
            except Exception:
                pass


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
