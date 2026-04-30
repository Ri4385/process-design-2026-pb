"""反応器出口を HYSYS 分離系に渡して、主要 stream 記録を JSON 出力する。"""

from __future__ import annotations

from process_sim.plant.runner import run_plant_once_main


def main() -> None:
    """既定 HYSYS ケースで plant one-pass を実行する。"""
    run_plant_once_main()


if __name__ == "__main__":
    main()
