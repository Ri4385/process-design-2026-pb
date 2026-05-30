"""分離系機器モデルの確認用ログを整形する。"""

from __future__ import annotations

from process_sim.separator.equipment import (
    Cooler,
    Compressor,
    Decanter,
    DistillationColumn,
    Heater,
    ProcessEquipment,
    Pump,
)


def format_process_equipment_log(equipment: ProcessEquipment) -> str:
    """分離系機器一式を標準出力向けに整形する。"""
    lines = [
        "HYSYS equipment 読み取り確認",
        "",
        "機器数",
        f"- 蒸留塔: {len(equipment.distillation_columns)}",
        f"- デカンター: {len(equipment.decanters)}",
        f"- 冷却器: {len(equipment.coolers)}",
        f"- 加熱器: {len(equipment.heaters)}",
        f"- ポンプ: {len(equipment.pumps)}",
        f"- コンプレッサー: {len(equipment.compressors)}",
        "",
        "デカンター",
    ]

    if equipment.decanters:
        for decanter in equipment.decanters:
            lines.extend(format_decanter_lines(decanter))
            lines.append("")
    else:
        lines.append("- 読み取り結果なし")
        lines.append("")

    lines.append("冷却器")
    if equipment.coolers:
        for cooler in equipment.coolers:
            lines.extend(format_cooler_lines(cooler))
            lines.append("")
    else:
        lines.append("- 読み取り結果なし")
        lines.append("")

    lines.append("加熱器")
    if equipment.heaters:
        for heater in equipment.heaters:
            lines.extend(format_heater_lines(heater))
            lines.append("")
    else:
        lines.append("- 読み取り結果なし")
        lines.append("")

    lines.append("蒸留塔")

    if not equipment.distillation_columns:
        lines.append("- 読み取り結果なし")
        return "\n".join(lines)

    for column in equipment.distillation_columns:
        lines.extend(format_distillation_column_lines(column))
        lines.append("")

    lines.append("ポンプ")
    if equipment.pumps:
        for pump in equipment.pumps:
            lines.extend(format_pump_lines(pump))
            lines.append("")
    else:
        lines.append("- 読み取り結果なし")
        lines.append("")

    lines.append("コンプレッサー")
    if equipment.compressors:
        for compressor in equipment.compressors:
            lines.extend(format_compressor_lines(compressor))
            lines.append("")
    else:
        lines.append("- 読み取り結果なし")
        lines.append("")

    return "\n".join(lines).rstrip()


def format_decanter_lines(decanter: Decanter) -> list[str]:
    """デカンター1基の読み取り結果を整形する。"""
    return [
        f"{decanter.display_name} ({decanter.spreadsheet_name})",
        f"- id: {decanter.id}",
        f"- 半径: {decanter.radius_m:.3f} m",
        f"- 長さ: {decanter.length_m:.3f} m",
        f"- 体積: {decanter.volume_m3:.3f} m3",
    ]


def format_cooler_lines(cooler: Cooler) -> list[str]:
    """冷却器1基の読み取り結果を整形する。"""
    return [
        f"{cooler.display_name} ({cooler.energy_name})",
        f"- id: {cooler.id}",
        f"- duty: {cooler.duty_kw:.3f} kW",
        f"- 入口温度: {cooler.inlet_temperature_c:.3f} degC",
        f"- 出口温度: {cooler.outlet_temperature_c:.3f} degC",
    ]


def format_heater_lines(heater: Heater) -> list[str]:
    """加熱器1基の読み取り結果を整形する。"""
    return [
        f"{heater.display_name} ({heater.energy_name})",
        f"- id: {heater.id}",
        f"- duty: {heater.duty_kw:.3f} kW",
        f"- 入口温度: {heater.inlet_temperature_c:.3f} degC",
        f"- 出口温度: {heater.outlet_temperature_c:.3f} degC",
    ]


def format_pump_lines(pump: Pump) -> list[str]:
    """ポンプ1基の読み取り結果を整形する。"""
    return [
        f"{pump.display_name} ({pump.energy_name})",
        f"- id: {pump.id}",
        f"- power: {pump.power_kw:.3f} kW",
    ]


def format_compressor_lines(compressor: Compressor) -> list[str]:
    """コンプレッサー1基の読み取り結果を整形する。"""
    return [
        f"{compressor.display_name} ({compressor.energy_name})",
        f"- id: {compressor.id}",
        f"- power: {compressor.power_kw:.3f} kW",
    ]


def format_distillation_column_lines(column: DistillationColumn) -> list[str]:
    """蒸留塔1基の読み取り結果を整形する。"""
    return [
        f"{column.display_name} ({column.operation_name})",
        f"- id: {column.id}",
        f"- 段数: {column.stage_count}",
        f"- feed 段: {column.feed_stage}",
        f"- 塔径: {column.diameter_m:.3f} m",
        f"- 塔高さ: {column.height_m:.3f} m",
        f"- 還流比: {column.reflux_ratio:.6g}",
        f"- 塔頂温度: {column.top_temperature_c:.3f} degC",
        f"- 塔底温度: {column.bottom_temperature_c:.3f} degC",
        (
            f"- condenser: {column.condenser_energy_name}, "
            f"duty {column.condenser_duty_kw:.3f} kW"
        ),
        (
            f"- reboiler: {column.reboiler_energy_name}, "
            f"duty {column.reboiler_duty_kw:.3f} kW"
        ),
        f"- 最大蒸気負荷段: {column.max_vapor_load_stage}",
        f"- 最大蒸気質量流量: {column.max_vapor_mass_flow_kg_s:.3f} kg/s",
    ]
