"""ユーザー定義の feed plan で plant recycle convergence を実行する。"""

from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from process_sim.plant.convergence import (  # noqa: E402
    PlantFeedPlan,
    format_plant_convergence_result,
    run_fixed_feed_convergence,
)
from process_sim.plant.feed import FreshFeed  # noqa: E402
from process_sim.reactor.core.stream import ReactorFeed  # noqa: E402


FEED_PLAN = PlantFeedPlan(
    startup_reactor_feed=ReactorFeed(
        eb=480.0,
        steam=2370.0,
    ),
    steady_fresh_feed=FreshFeed(
        hydrocarbon_kmol_h=265.0 / 0.995,
        steam_kmol_h=28.0,
    ),
)


def main() -> None:
    """固定 feed plan で収束計算を実行する。"""
    result = run_fixed_feed_convergence(feed_plan=FEED_PLAN)
    print(format_plant_convergence_result(result))


if __name__ == "__main__":
    main()
