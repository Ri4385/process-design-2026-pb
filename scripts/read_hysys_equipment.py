"""既定 HYSYS case から分離系機器を読み取り、標準出力へ表示する。"""

from __future__ import annotations

from process_sim.plant.const import DEFAULT_HYSYS_CASE_PATH
from process_sim.separator.equipment_log import format_process_equipment_log
from process_sim.separator.equipment_reader.process_equipment import read_process_equipment
from process_sim.separator.hysys_io import hysys_case


def main() -> None:
    """既定 case の equipment 読み取り確認を実行する。"""
    with hysys_case(DEFAULT_HYSYS_CASE_PATH.resolve(), visible=True) as (
        _app,
        simulation_case,
        _prog_id,
    ):
        equipment = read_process_equipment(simulation_case)
    print(format_process_equipment_log(equipment))


if __name__ == "__main__":
    main()
