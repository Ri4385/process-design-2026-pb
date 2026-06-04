"""収束後に HYSYS へ書き込む操作条件モデル。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from process_sim.plant.convergence import PlantConvergenceResult
from process_sim.plant.feed import FreshFeed
from process_sim.plant.models import PlantStreamRecord
from process_sim.reactor.cases.styrene_default import ReactorCase
from process_sim.reactor.cases.styrene_radial_default import RadialReactorCase


FRESH_EB_TEMPERATURE_C = 30.0
FRESH_EB_PRESSURE_KPA = 101.3
FRESH_EB_MOL_FRACTION = 0.995
FRESH_EB_BENZENE_MOL_FRACTION = 0.005
FRESH_WATER_TEMPERATURE_C = 30.0
FRESH_WATER_PRESSURE_KPA = 300.0


class ComponentMolarFlowSpec(BaseModel):
    """HYSYS stream へ書き込む成分モル流量。"""

    model_config = ConfigDict(frozen=True)

    values: dict[str, float]


class FullMaterialStreamWriteSpec(BaseModel):
    """Material stream へ組成、温度、圧力を書き込む条件。"""

    model_config = ConfigDict(frozen=True)

    stream_name: str
    temperature_c: float
    pressure_kpa: float
    component_molar_flow: ComponentMolarFlowSpec


class PressureMaterialStreamWriteSpec(BaseModel):
    """Material stream へ圧力だけを書き込む条件。"""

    model_config = ConfigDict(frozen=True)

    stream_name: str
    pressure_kpa: float


class TemperatureMaterialStreamWriteSpec(BaseModel):
    """Material stream へ温度だけを書き込む条件。"""

    model_config = ConfigDict(frozen=True)

    stream_name: str
    temperature_c: float


class OperationWriteSpec(BaseModel):
    """HYSYS operation への書き込み条件。"""

    model_config = ConfigDict(frozen=True)

    operation_name: str
    variable_name: str
    value: float
    unit: str


class HysysControlPlan(BaseModel):
    """収束後に HYSYS case へ適用する操作条件一式。"""

    model_config = ConfigDict(frozen=True)

    full_material_streams: tuple[FullMaterialStreamWriteSpec, ...] = ()
    pressure_material_streams: tuple[PressureMaterialStreamWriteSpec, ...] = ()
    temperature_material_streams: tuple[TemperatureMaterialStreamWriteSpec, ...] = ()
    operations: tuple[OperationWriteSpec, ...] = ()


class InletConditionSettings(BaseModel):
    """入口加熱系へ書き込む設計条件。"""

    model_config = ConfigDict(frozen=True)

    reactor_inlet_temperature_c: float
    reactor_inlet_pressure_kpa: float
    pump_discharge_margin_kpa: float = 20.0


def build_inlet_control_plan(
    convergence_result: PlantConvergenceResult,
    base_reactor_case: ReactorCase | RadialReactorCase,
) -> HysysControlPlan:
    """収束結果と反応器条件から入口加熱系の HYSYS 書き込み plan を作る。"""
    inlet_settings = inlet_condition_settings_from_reactor_case(base_reactor_case)
    final_streams = convergence_result.final_iteration.plant_record.streams
    eb_recycle = require_stream(final_streams.get("eb_recycle"), "eb_recycle")
    water_recycle = require_stream(final_streams.get("water_recycle"), "water_recycle")
    pump_discharge_pressure_kpa = (
        inlet_settings.reactor_inlet_pressure_kpa + inlet_settings.pump_discharge_margin_kpa
    )
    return HysysControlPlan(
        full_material_streams=(
            fresh_eb_write_spec(convergence_result.feed_plan.steady_fresh_feed),
            recycle_write_spec(stream_name="eb_recycle_to_mixer", source=eb_recycle),
            fresh_water_write_spec(convergence_result.feed_plan.steady_fresh_feed),
            recycle_write_spec(stream_name="water_recycle_to_mixer", source=water_recycle),
        ),
        pressure_material_streams=(
            PressureMaterialStreamWriteSpec(stream_name="eb2", pressure_kpa=pump_discharge_pressure_kpa),
            PressureMaterialStreamWriteSpec(stream_name="water2", pressure_kpa=pump_discharge_pressure_kpa),
        ),
        temperature_material_streams=(
            TemperatureMaterialStreamWriteSpec(
                stream_name="reactor_inlet",
                temperature_c=inlet_settings.reactor_inlet_temperature_c,
            ),
        ),
    )


def inlet_condition_settings_from_reactor_case(
    reactor_case: ReactorCase | RadialReactorCase,
) -> InletConditionSettings:
    """反応器 case から入口温度と入口圧力を書き込み条件へ変換する。"""
    if isinstance(reactor_case, RadialReactorCase):
        if len(reactor_case.conditions.stage_inlet_temperatures_k) == 0:
            raise ValueError("radial reactor stage inlet temperatures are empty")
        return InletConditionSettings(
            reactor_inlet_temperature_c=reactor_case.conditions.stage_inlet_temperatures_k[0] - 273.15,
            reactor_inlet_pressure_kpa=reactor_case.conditions.inlet_pressure_pa / 1000.0,
        )
    if len(reactor_case.conditions.stage_inlet_temperatures_c) == 0:
        raise ValueError("reactor stage inlet temperatures are empty")
    return InletConditionSettings(
        reactor_inlet_temperature_c=reactor_case.conditions.stage_inlet_temperatures_c[0],
        reactor_inlet_pressure_kpa=reactor_case.conditions.pressure_kpa,
    )


def fresh_eb_write_spec(fresh_feed: FreshFeed) -> FullMaterialStreamWriteSpec:
    """fresh EB stream の書き込み条件を作る。"""
    return FullMaterialStreamWriteSpec(
        stream_name="fresh_eb",
        temperature_c=FRESH_EB_TEMPERATURE_C,
        pressure_kpa=FRESH_EB_PRESSURE_KPA,
        component_molar_flow=ComponentMolarFlowSpec(
            values={
                "eb": fresh_feed.hydrocarbon_kmol_h * FRESH_EB_MOL_FRACTION,
                "benzene": fresh_feed.hydrocarbon_kmol_h * FRESH_EB_BENZENE_MOL_FRACTION,
            }
        ),
    )


def fresh_water_write_spec(fresh_feed: FreshFeed) -> FullMaterialStreamWriteSpec:
    """fresh water stream の書き込み条件を作る。"""
    return FullMaterialStreamWriteSpec(
        stream_name="fresh_water",
        temperature_c=FRESH_WATER_TEMPERATURE_C,
        pressure_kpa=FRESH_WATER_PRESSURE_KPA,
        component_molar_flow=ComponentMolarFlowSpec(values={"steam": fresh_feed.steam_kmol_h}),
    )


def recycle_write_spec(stream_name: str, source: PlantStreamRecord) -> FullMaterialStreamWriteSpec:
    """recycle stream の記録から入口 mixer への書き込み条件を作る。"""
    temperature_c = require_value(source.temperature_c, f"{source.name} temperature")
    pressure_kpa = require_value(source.pressure_kpa, f"{source.name} pressure")
    if not source.component_molar_flow_kmol_h:
        raise ValueError(f"{source.name} component molar flows are missing")
    return FullMaterialStreamWriteSpec(
        stream_name=stream_name,
        temperature_c=temperature_c,
        pressure_kpa=pressure_kpa,
        component_molar_flow=ComponentMolarFlowSpec(values=dict(source.component_molar_flow_kmol_h)),
    )


def require_stream(stream: PlantStreamRecord | None, stream_name: str) -> PlantStreamRecord:
    """必須 stream を取得する。"""
    if stream is None:
        raise ValueError(f"{stream_name} stream is missing")
    return stream


def require_value(value: float | None, label: str) -> float:
    """必須数値を取得する。"""
    if value is None:
        raise ValueError(f"{label} is missing")
    return value


def format_hysys_control_readback(
    plan: HysysControlPlan,
    readback: dict[str, PlantStreamRecord],
) -> str:
    """HYSYS 操作条件の書き込み plan と readback 結果を整形する。"""
    lines = ["[Post Convergence HYSYS Controls]"]
    lines.append("material streams")
    for spec in plan.full_material_streams:
        record = readback[spec.stream_name]
        lines.append(
            f"  {spec.stream_name:<24} "
            f"T={format_float(record.temperature_c)} C "
            f"P={format_float(record.pressure_kpa)} kPa "
            f"total={format_float(record.total_molar_flow_kmol_h)} kmol/h"
        )
    for spec in plan.pressure_material_streams:
        record = readback[spec.stream_name]
        lines.append(f"  {spec.stream_name:<24} P={format_float(record.pressure_kpa)} kPa")
    for spec in plan.temperature_material_streams:
        record = readback[spec.stream_name]
        lines.append(f"  {spec.stream_name:<24} T={format_float(record.temperature_c)} C")
    if plan.operations:
        lines.append("")
        lines.append("operations")
        for spec in plan.operations:
            lines.append(f"  {spec.operation_name:<24} {spec.variable_name}={spec.value:g} {spec.unit}")
    return "\n".join(lines)


def format_float(value: float | None) -> str:
    """ログ用の数値表現を返す。"""
    if value is None:
        return "missing"
    return f"{value:.6g}"
