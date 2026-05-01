"""最小反応器実行スクリプト（Python完結）。

`uv run python scripts/run_reactor_case.py` で CLI を呼び出す。
"""

from __future__ import annotations

from process_sim.cli import run_reactor_case_main


if __name__ == "__main__":
    run_reactor_case_main()
