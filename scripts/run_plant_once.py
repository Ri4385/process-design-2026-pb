"""反応器出口を HYSYS 分離系に渡して、主要 stream 記録を JSON 出力する。"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from process_sim.plant.runner import run_plant_once_main  # noqa: E402


def main() -> None:
    """既定 HYSYS ケースで plant one-pass を実行する。"""
    run_plant_once_main()


if __name__ == "__main__":
    main()
