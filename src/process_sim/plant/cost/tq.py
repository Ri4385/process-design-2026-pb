"""T-Q 線図用 process stream データの生成。"""

from __future__ import annotations

from process_sim.plant.cost.equipment import cooler_outlet_temperature_for_cost
from process_sim.plant.cost.models import (
    ExternalUtilityLoad,
    HeatRecoveryResult,
    TQStream,
)
from process_sim.plant.cost.utility import (
    column_condenser_uses_cooling_water,
    cooler_uses_cooling_water,
    selected_heater_steam_name,
    selected_reboiler_steam_name,
)
from process_sim.reactor.core.models import ReactorResult
from process_sim.separator.equipment import ProcessEquipment


def build_tq_streams_no_heat_recovery(
    equipment: ProcessEquipment,
    reactor_result: ReactorResult,
) -> tuple[TQStream, ...]:
    """熱回収しない場合の T-Q process stream を作る。"""
    streams: list[TQStream] = []
    streams.extend(cooler_tq_streams(equipment, case_name="no heat recovery"))
    streams.extend(heater_tq_streams(equipment, case_name="no heat recovery"))
    streams.extend(column_tq_streams(equipment, case_name="no heat recovery"))
    streams.extend(
        reactor_reheat_tq_streams(reactor_result, case_name="no heat recovery")
    )
    return tuple(streams)


def build_tq_streams_with_heat_recovery(
    equipment: ProcessEquipment,
    reactor_result: ReactorResult,
    heat_recovery: HeatRecoveryResult,
) -> tuple[TQStream, ...]:
    """C-11 と H-22 の熱回収を反映した T-Q process stream を作る。"""
    streams: list[TQStream] = [
        TQStream(
            case_name="with heat recovery",
            stream_type="hot",
            role="recovery",
            id=heat_recovery.hot_equipment_id,
            inlet_temperature_c=heat_recovery.hot_inlet_c,
            outlet_temperature_c=heat_recovery.hot_outlet_c,
            duty_kw=heat_recovery.recovered_duty_kw,
        ),
        TQStream(
            case_name="with heat recovery",
            stream_type="cold",
            role="recovery",
            id=heat_recovery.cold_equipment_id,
            inlet_temperature_c=heat_recovery.cold_inlet_c,
            outlet_temperature_c=heat_recovery.cold_outlet_c,
            duty_kw=heat_recovery.recovered_duty_kw,
        ),
    ]

    streams.extend(
        cooler_tq_streams(
            equipment, case_name="with heat recovery", heat_recovery=heat_recovery
        )
    )
    streams.extend(
        heater_tq_streams(
            equipment, case_name="with heat recovery", heat_recovery=heat_recovery
        )
    )
    streams.extend(column_tq_streams(equipment, case_name="with heat recovery"))
    streams.extend(
        reactor_reheat_tq_streams(reactor_result, case_name="with heat recovery")
    )
    return tuple(streams)


def build_external_utility_loads_with_heat_recovery(
    equipment: ProcessEquipment,
    reactor_result: ReactorResult,
    heat_recovery: HeatRecoveryResult,
) -> tuple[ExternalUtilityLoad, ...]:
    """熱回収後に外部 utility が担当する duty を作る。"""
    loads: list[ExternalUtilityLoad] = []

    for cooler in equipment.coolers:
        duty = residual_cooler_duty_kw(cooler, heat_recovery)
        if duty <= 0.0:
            continue
        if cooler_uses_cooling_water(cooler):
            loads.append(
                ExternalUtilityLoad(
                    utility="cooling water",
                    target_id=cooler.id,
                    inlet_temperature_c=30.0,
                    outlet_temperature_c=45.0,
                    duty_kw=duty,
                )
            )
        else:
            loads.append(
                ExternalUtilityLoad(
                    utility="propylene",
                    target_id=cooler.id,
                    inlet_temperature_c=0.0,
                    outlet_temperature_c=0.0,
                    duty_kw=duty,
                )
            )

    for heater in equipment.heaters:
        duty = residual_heater_duty_kw(heater, heat_recovery)
        if duty <= 0.0:
            continue
        if heater.id in {
            "steam_inlet_heater1",
            "steam_inlet_heater2",
            "steam_inlet_heater3",
            "reactor_trim_heater",
        }:
            loads.append(
                ExternalUtilityLoad(
                    utility="furnace",
                    target_id=heater.id,
                    inlet_temperature_c=None,
                    outlet_temperature_c=None,
                    duty_kw=duty,
                )
            )
            continue
        steam_name = selected_heater_steam_name(heater)
        loads.append(
            ExternalUtilityLoad(
                utility=steam_name,
                target_id=heater.id,
                inlet_temperature_c=steam_temperature_c(steam_name),
                outlet_temperature_c=steam_temperature_c(steam_name),
                duty_kw=duty,
            )
        )

    for column in equipment.distillation_columns:
        if column_condenser_uses_cooling_water(column.top_temperature_c):
            loads.append(
                ExternalUtilityLoad(
                    utility="cooling water",
                    target_id=f"{column.id}_condenser",
                    inlet_temperature_c=30.0,
                    outlet_temperature_c=45.0,
                    duty_kw=abs(column.condenser_duty_kw),
                )
            )
        else:
            loads.append(
                ExternalUtilityLoad(
                    utility="propylene",
                    target_id=f"{column.id}_condenser",
                    inlet_temperature_c=0.0,
                    outlet_temperature_c=0.0,
                    duty_kw=abs(column.condenser_duty_kw),
                )
            )
        steam_name = selected_reboiler_steam_name(column.bottom_temperature_c)
        loads.append(
            ExternalUtilityLoad(
                utility=steam_name,
                target_id=f"{column.id}_reboiler",
                inlet_temperature_c=steam_temperature_c(steam_name),
                outlet_temperature_c=steam_temperature_c(steam_name),
                duty_kw=abs(column.reboiler_duty_kw),
            )
        )

    for stream in reactor_reheat_tq_streams(
        reactor_result, case_name="with heat recovery"
    ):
        loads.append(
            ExternalUtilityLoad(
                utility="furnace",
                target_id=stream.id,
                inlet_temperature_c=None,
                outlet_temperature_c=None,
                duty_kw=stream.duty_kw,
            )
        )
    return tuple(loads)


def cooler_tq_streams(
    equipment: ProcessEquipment,
    case_name: str,
    heat_recovery: HeatRecoveryResult | None = None,
) -> tuple[TQStream, ...]:
    """cooler を hot stream として T-Q stream 化する。"""
    streams: list[TQStream] = []
    for cooler in equipment.coolers:
        if heat_recovery is not None and cooler.id == heat_recovery.hot_equipment_id:
            if heat_recovery.hot_residual_cooling_kw <= 0.0:
                continue
            streams.append(
                TQStream(
                    case_name=case_name,
                    stream_type="hot",
                    role="external",
                    id=cooler.id,
                    inlet_temperature_c=heat_recovery.hot_outlet_c,
                    outlet_temperature_c=cooler_outlet_temperature_for_cost(cooler),
                    duty_kw=heat_recovery.hot_residual_cooling_kw,
                )
            )
            continue

        streams.append(
            TQStream(
                case_name=case_name,
                stream_type="hot",
                role="external",
                id=cooler.id,
                inlet_temperature_c=cooler.inlet_temperature_c,
                outlet_temperature_c=cooler_outlet_temperature_for_cost(cooler),
                duty_kw=abs(cooler.duty_kw),
            )
        )
    return tuple(streams)


def heater_tq_streams(
    equipment: ProcessEquipment,
    case_name: str,
    heat_recovery: HeatRecoveryResult | None = None,
) -> tuple[TQStream, ...]:
    """heater を cold stream として T-Q stream 化する。"""
    streams: list[TQStream] = []
    for heater in equipment.heaters:
        if heat_recovery is not None and heater.id == heat_recovery.cold_equipment_id:
            if heat_recovery.cold_residual_heating_kw <= 0.0:
                continue
            streams.append(
                TQStream(
                    case_name=case_name,
                    stream_type="cold",
                    role="external",
                    id=heater.id,
                    inlet_temperature_c=heat_recovery.cold_inlet_c,
                    outlet_temperature_c=heat_recovery.cold_outlet_c,
                    duty_kw=heat_recovery.cold_residual_heating_kw,
                )
            )
            continue

        streams.append(
            TQStream(
                case_name=case_name,
                stream_type="cold",
                role="external",
                id=heater.id,
                inlet_temperature_c=heater.inlet_temperature_c,
                outlet_temperature_c=heater.outlet_temperature_c,
                duty_kw=abs(heater.duty_kw),
            )
        )
    return tuple(streams)


def column_tq_streams(
    equipment: ProcessEquipment, case_name: str
) -> tuple[TQStream, ...]:
    """蒸留塔 condenser/reboiler を T-Q stream 化する。"""
    streams: list[TQStream] = []
    for column in equipment.distillation_columns:
        streams.append(
            TQStream(
                case_name=case_name,
                stream_type="hot",
                role="external",
                id=f"{column.id}_condenser",
                inlet_temperature_c=column.top_temperature_c,
                outlet_temperature_c=column.top_temperature_c,
                duty_kw=abs(column.condenser_duty_kw),
            )
        )
        streams.append(
            TQStream(
                case_name=case_name,
                stream_type="cold",
                role="external",
                id=f"{column.id}_reboiler",
                inlet_temperature_c=column.bottom_temperature_c,
                outlet_temperature_c=column.bottom_temperature_c,
                duty_kw=abs(column.reboiler_duty_kw),
            )
        )
    return tuple(streams)


def reactor_reheat_tq_streams(
    reactor_result: ReactorResult, case_name: str
) -> tuple[TQStream, ...]:
    """反応器段間再加熱を cold stream として T-Q stream 化する。"""
    streams: list[TQStream] = []
    stage_logs = reactor_result.log.stage_logs
    for index, stage_log in enumerate(stage_logs[:-1]):
        reheat_duty_mw = stage_log.reheat_duty_mw
        if reheat_duty_mw is None or reheat_duty_mw <= 0.0:
            continue
        next_stage = stage_logs[index + 1]
        streams.append(
            TQStream(
                case_name=case_name,
                stream_type="cold",
                role="external",
                id=f"reactor_reheat_{stage_log.stage_index}_to_{next_stage.stage_index}",
                inlet_temperature_c=stage_log.outlet_temperature_c,
                outlet_temperature_c=next_stage.inlet_temperature_c,
                duty_kw=reheat_duty_mw * 1000.0,
            )
        )
    return tuple(streams)


def residual_cooler_duty_kw(cooler: object, heat_recovery: HeatRecoveryResult) -> float:
    """熱回収後に外部冷却へ残る duty を返す。"""
    cooler_id = getattr(cooler, "id")
    duty_kw = abs(float(getattr(cooler, "duty_kw")))
    if cooler_id == heat_recovery.hot_equipment_id:
        return heat_recovery.hot_residual_cooling_kw
    return duty_kw


def residual_heater_duty_kw(heater: object, heat_recovery: HeatRecoveryResult) -> float:
    """熱回収後に外部加熱へ残る duty を返す。"""
    heater_id = getattr(heater, "id")
    duty_kw = abs(float(getattr(heater, "duty_kw")))
    if heater_id == heat_recovery.cold_equipment_id:
        return heat_recovery.cold_residual_heating_kw
    return duty_kw


def steam_temperature_c(steam_name: str) -> float:
    """steam 名から代表温度を返す。"""
    if steam_name == "steam_130c":
        return 130.0
    if steam_name == "steam_160c":
        return 160.0
    if steam_name == "steam_250c":
        return 250.0
    raise ValueError(f"unknown steam name: {steam_name}")
