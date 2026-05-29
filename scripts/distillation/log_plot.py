"""貼り付けた蒸留塔 sweep summary ログから cost summary 図を作る。"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Sequence

import japanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt
from pydantic import BaseModel


PASTE_LOG = """
[summary-case] tower=tower3 file=T3_20.hsc N=20 best_feed=11 J=0.1171 equipment=0.0698 utility=0.0473 shell=0.0278 cond_eq=0.0121 reb_eq=0.0298 cond_util=0.0062 reb_util=0.0411 D=0.499 H=18.400 L/D=36.852 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_30.hsc N=30 best_feed=15 J=0.0969 equipment=0.0631 utility=0.0338 shell=0.0294 cond_eq=0.0096 reb_eq=0.0241 cond_util=0.0043 reb_util=0.0295 D=0.423 H=24.400 L/D=57.677 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_40.hsc N=40 best_feed=20 J=0.0981 equipment=0.0663 utility=0.0318 shell=0.0341 cond_eq=0.0092 reb_eq=0.0231 cond_util=0.0041 reb_util=0.0277 D=0.410 H=30.400 L/D=74.139 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_50.hsc N=50 best_feed=25 J=0.1027 equipment=0.0713 utility=0.0314 shell=0.0392 cond_eq=0.0091 reb_eq=0.0229 cond_util=0.0040 reb_util=0.0274 D=0.408 H=36.400 L/D=89.256 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_60.hsc N=60 best_feed=30 J=0.1078 equipment=0.0765 utility=0.0314 shell=0.0444 cond_eq=0.0091 reb_eq=0.0229 cond_util=0.0040 reb_util=0.0274 D=0.407 H=42.400 L/D=104.057 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_70.hsc N=70 best_feed=35 J=0.1129 equipment=0.0815 utility=0.0313 shell=0.0495 cond_eq=0.0091 reb_eq=0.0229 cond_util=0.0040 reb_util=0.0274 D=0.407 H=48.400 L/D=118.797 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_80.hsc N=80 best_feed=40 J=0.1179 equipment=0.0865 utility=0.0313 shell=0.0545 cond_eq=0.0091 reb_eq=0.0229 cond_util=0.0040 reb_util=0.0274 D=0.407 H=54.400 L/D=133.526 ld_warning oku-yen/year

"""

SCRIPT_DIR = Path(__file__).resolve().parent
MEDIA_DIR = SCRIPT_DIR / "media"
FIGURE_PATH = MEDIA_DIR / "tmp.png"


class CostPoint(BaseModel):
    """蒸留塔段数 sweep の summary 1 点。"""

    stage_count: int
    equipment_cost_oku_yen_per_year: float
    utility_cost_oku_yen_per_year: float
    objective_oku_yen_per_year: float


def configure_axes() -> None:
    """グラフの目盛と枠線を設定する。"""
    axes = plt.gca()
    axes.grid(False)
    axes.tick_params(direction="in", top=True, right=True, bottom=True, left=True)


def value_by_key(line: str, key: str) -> str | None:
    """ログ行から key=value の value を取り出す。"""
    match = re.search(rf"(?<!\S){re.escape(key)}=([^\s]+)", line)
    if match is None:
        return None
    return match.group(1)


def parse_cost_point(line: str) -> CostPoint | None:
    """ログ1行を cost summary の点へ変換する。"""
    if "[case]" not in line and "[summary-case]" not in line:
        return None
    if "valid" not in line and "[summary-case]" not in line:
        return None

    stage_text = value_by_key(line, "N")
    equipment_text = value_by_key(line, "equipment")
    utility_text = value_by_key(line, "utility")
    objective_text = value_by_key(line, "J")
    if None in (stage_text, equipment_text, utility_text, objective_text):
        return None

    return CostPoint(
        stage_count=int(stage_text or "0"),
        equipment_cost_oku_yen_per_year=float(equipment_text or "nan"),
        utility_cost_oku_yen_per_year=float(utility_text or "nan"),
        objective_oku_yen_per_year=float(objective_text or "nan"),
    )


def parse_cost_points(text: str) -> list[CostPoint]:
    """貼り付けログ全体から cost summary の点を取り出す。"""
    points_by_stage: dict[int, CostPoint] = {}
    for line in text.splitlines():
        point = parse_cost_point(line)
        if point is not None:
            points_by_stage[point.stage_count] = point
    return sorted(points_by_stage.values(), key=lambda point: point.stage_count)


def finite_points(points: Sequence[CostPoint]) -> list[CostPoint]:
    """描画できる数値を持つ点だけを返す。"""
    return [
        point
        for point in points
        if math.isfinite(point.equipment_cost_oku_yen_per_year)
        and math.isfinite(point.utility_cost_oku_yen_per_year)
        and math.isfinite(point.objective_oku_yen_per_year)
    ]


def write_figure(points: Sequence[CostPoint]) -> Path:
    """既存 sweep と同じ cost summary 図を保存する。"""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    valid_points = finite_points(points)

    plt.figure()
    configure_axes()

    if valid_points:
        stages = [point.stage_count for point in valid_points]
        plt.plot(
            stages,
            [point.equipment_cost_oku_yen_per_year for point in valid_points],
            marker="o",
            label="装置コスト",
        )
        plt.plot(
            stages,
            [point.utility_cost_oku_yen_per_year for point in valid_points],
            marker="o",
            label="用役コスト",
        )
        plt.plot(
            stages,
            [point.objective_oku_yen_per_year for point in valid_points],
            marker="o",
            label="評価関数",
        )

    plt.xlabel("段数 [-]")
    plt.ylabel("コスト [億円/year]")
    plt.ylim(bottom=0)
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIGURE_PATH, dpi=200)
    plt.close()
    return FIGURE_PATH


def main() -> None:
    """貼り付けログから cost summary 図を作成する。"""
    points = parse_cost_points(PASTE_LOG)
    if not points:
        raise RuntimeError("PASTE_LOG に描画できる summary ログがありません")

    figure_path = write_figure(points)
    print(f"saved: {figure_path}")


if __name__ == "__main__":
    main()
