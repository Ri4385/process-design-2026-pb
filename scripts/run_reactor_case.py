"""最小反応器実行スクリプト（Python完結）。

`python scripts/run_reactor_case.py` でも動くように、
リポジトリ直下の `src/` を import path に追加してから CLI を呼び出す。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from process_sim.cli import run_reactor_case_main


if __name__ == "__main__":
    run_reactor_case_main()
