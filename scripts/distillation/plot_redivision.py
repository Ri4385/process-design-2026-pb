"""貼り付けた蒸留塔 sweep summary ログから、L/D分割補正後の cost summary 図を作る。"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Sequence

import japanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt
from pydantic import BaseModel


PASTE_LOG = """
[summary-case] tower=tower3 file=T3_25.hsc N=25 best_feed=12 J=0.1019 equipment=0.0641 utility=0.0377 shell=0.0280 cond_eq=0.0104 reb_eq=0.0258 cond_util=0.0049 reb_util=0.0329 D=0.447 H=21.400 L/D=47.921 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_26.hsc N=26 best_feed=12 J=0.1012 equipment=0.0641 utility=0.0371 shell=0.0283 cond_eq=0.0102 reb_eq=0.0255 cond_util=0.0048 reb_util=0.0323 D=0.443 H=22.000 L/D=49.693 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_27.hsc N=27 best_feed=13 J=0.0991 equipment=0.0634 utility=0.0358 shell=0.0284 cond_eq=0.0100 reb_eq=0.0249 cond_util=0.0046 reb_util=0.0312 D=0.435 H=22.600 L/D=51.960 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_28.hsc N=28 best_feed=13 J=0.0988 equipment=0.0635 utility=0.0353 shell=0.0289 cond_eq=0.0099 reb_eq=0.0247 cond_util=0.0045 reb_util=0.0308 D=0.432 H=23.200 L/D=53.668 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_29.hsc N=29 best_feed=14 J=0.0976 equipment=0.0631 utility=0.0344 shell=0.0291 cond_eq=0.0097 reb_eq=0.0243 cond_util=0.0044 reb_util=0.0300 D=0.427 H=23.800 L/D=55.755 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_30.hsc N=30 best_feed=15 J=0.0969 equipment=0.0631 utility=0.0338 shell=0.0294 cond_eq=0.0096 reb_eq=0.0241 cond_util=0.0043 reb_util=0.0295 D=0.423 H=24.400 L/D=57.677 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_31.hsc N=31 best_feed=15 J=0.0968 equipment=0.0633 utility=0.0335 shell=0.0298 cond_eq=0.0095 reb_eq=0.0239 cond_util=0.0043 reb_util=0.0292 D=0.421 H=25.000 L/D=59.360 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_32.hsc N=32 best_feed=15 J=0.0970 equipment=0.0636 utility=0.0333 shell=0.0303 cond_eq=0.0095 reb_eq=0.0238 cond_util=0.0043 reb_util=0.0290 D=0.420 H=25.600 L/D=60.979 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_33.hsc N=33 best_feed=16 J=0.0966 equipment=0.0637 utility=0.0329 shell=0.0307 cond_eq=0.0094 reb_eq=0.0236 cond_util=0.0042 reb_util=0.0287 D=0.417 H=26.200 L/D=62.815 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_34.hsc N=34 best_feed=16 J=0.0968 equipment=0.0641 utility=0.0327 shell=0.0312 cond_eq=0.0094 reb_eq=0.0235 cond_util=0.0042 reb_util=0.0285 D=0.416 H=26.800 L/D=64.401 ld_warning oku-yen/year
[summary-case] tower=tower3 file=T3_35.hsc N=35 best_feed=17 J=0.0967 equipment=0.0643 utility=0.0324 shell=0.0316 cond_eq=0.0093 reb_eq=0.0234 cond_util=0.0041 reb_util=0.0283 D=0.414 H=27.400 L/D=66.150 ld_warning oku-yen/year
"""

SCRIPT_DIR = Path(__file__).resolve().parent
MEDIA_DIR = SCRIPT_DIR / "media"
FIGURE_PATH = MEDIA_DIR / "tmp_ld_split.png"

LD_LIMIT = 30.0

COLUMN_SHELL_COST_FACTOR_YEN = 1_500_000.0
DEPRECIATION_YEARS = 7.0
YEN_PER_OKU_YEN = 1.0e8


class CostPoint(BaseModel):
    """蒸留塔段数 sweep の summary 1 点。"""

    stage_count: int
    best_feed_stage: int | None

    equipment_old_oku_yen_per_year: float
    utility_oku_yen_per_year: float
    objective_old_oku_yen_per_year: float

    shell_old_oku_yen_per_year: float
    shell_new_oku_yen_per_year: float

    equipment_new_oku_yen_per_year: float
    objective_new_oku_yen_per_year: float

    diameter_m: float
    height_m: float
    ld_ratio: float

    split_count: int
    split_height_m: float
    split_ld_ratio: float


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


def required_float(line: str, key: str) -> float:
    """ログ行から必須float値を読む。"""
    text = value_by_key(line, key)
    if text is None:
        raise RuntimeError(f"{key}=... がありません: {line}")
    value = float(text)
    if not math.isfinite(value):
        raise RuntimeError(f"{key} が有限値ではありません: {text}")
    return value


def optional_int(line: str, key: str) -> int | None:
    """ログ行から任意int値を読む。"""
    text = value_by_key(line, key)
    if text is None:
        return None
    return int(text)


def column_shell_capital_cost_yen(diameter_m: float, height_m: float) -> float:
    """蒸留塔シェルの機器費を計算する。"""
    if diameter_m <= 0.0 or height_m <= 0.0:
        raise ValueError("diameter_m and height_m must be positive")
    return COLUMN_SHELL_COST_FACTOR_YEN * diameter_m**1.066 * height_m**0.82


def column_shell_annual_cost_oku_yen(diameter_m: float, height_m: float) -> float:
    """蒸留塔シェルの年間装置費を億円/yearで計算する。"""
    capital_cost_yen = column_shell_capital_cost_yen(diameter_m, height_m)
    annual_cost_yen_per_year = 2.5 * capital_cost_yen / DEPRECIATION_YEARS
    return annual_cost_yen_per_year / YEN_PER_OKU_YEN


def split_info(diameter_m: float, height_m: float, ld_ratio: float) -> tuple[int, float, float]:
    """L/D制約から分割数、分割後高さ、分割後L/Dを返す。"""
    split_count = max(1, math.ceil(ld_ratio / LD_LIMIT))
    split_height_m = height_m / split_count
    split_ld_ratio = split_height_m / diameter_m
    return split_count, split_height_m, split_ld_ratio


def parse_cost_point(line: str) -> CostPoint | None:
    """summary-case ログ1行をL/D補正後の点へ変換する。"""
    if "[summary-case]" not in line:
        return None

    stage_count = int(required_float(line, "N"))
    best_feed_stage = optional_int(line, "best_feed")

    equipment_old = required_float(line, "equipment")
    utility = required_float(line, "utility")
    objective_old = required_float(line, "J")

    # ここはログの shell を使う。D,Hから再計算しない。
    shell_old = required_float(line, "shell")

    diameter_m = required_float(line, "D")
    height_m = required_float(line, "H")
    ld_ratio = required_float(line, "L/D")

    split_count, split_height_m, split_ld_ratio = split_info(
        diameter_m=diameter_m,
        height_m=height_m,
        ld_ratio=ld_ratio,
    )

    shell_new = split_count * column_shell_annual_cost_oku_yen(
        diameter_m=diameter_m,
        height_m=split_height_m,
    )

    equipment_new = equipment_old - shell_old + shell_new
    objective_new = equipment_new + utility

    return CostPoint(
        stage_count=stage_count,
        best_feed_stage=best_feed_stage,
        equipment_old_oku_yen_per_year=equipment_old,
        utility_oku_yen_per_year=utility,
        objective_old_oku_yen_per_year=objective_old,
        shell_old_oku_yen_per_year=shell_old,
        shell_new_oku_yen_per_year=shell_new,
        equipment_new_oku_yen_per_year=equipment_new,
        objective_new_oku_yen_per_year=objective_new,
        diameter_m=diameter_m,
        height_m=height_m,
        ld_ratio=ld_ratio,
        split_count=split_count,
        split_height_m=split_height_m,
        split_ld_ratio=split_ld_ratio,
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
        if math.isfinite(point.equipment_new_oku_yen_per_year)
        and math.isfinite(point.utility_oku_yen_per_year)
        and math.isfinite(point.objective_new_oku_yen_per_year)
    ]


def write_figure(points: Sequence[CostPoint]) -> Path:
    """L/D補正後の cost summary 図を保存する。"""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    valid_points = finite_points(points)

    plt.figure()
    configure_axes()

    if valid_points:
        stages = [point.stage_count for point in valid_points]

        plt.plot(
            stages,
            [point.equipment_new_oku_yen_per_year for point in valid_points],
            marker="o",
            label="装置コスト",
        )
        plt.plot(
            stages,
            [point.utility_oku_yen_per_year for point in valid_points],
            marker="o",
            label="用役コスト",
        )
        plt.plot(
            stages,
            [point.objective_new_oku_yen_per_year for point in valid_points],
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


def print_summary(points: Sequence[CostPoint]) -> None:
    """L/D補正後のsummaryをstdoutに表示する。"""
    for point in points:
        feed_text = "nan" if point.best_feed_stage is None else str(point.best_feed_stage)

        print(
            f"[ld-summary] "
            f"N={point.stage_count} "
            f"best_feed={feed_text} "
            f"D={point.diameter_m:.3f} "
            f"H_original={point.height_m:.3f} "
            f"LD_original={point.ld_ratio:.3f} "
            f"split_count={point.split_count} "
            f"H_split={point.split_height_m:.3f} "
            f"LD_split={point.split_ld_ratio:.3f} "
            f"J_old={point.objective_old_oku_yen_per_year:.4f} "
            f"J_new={point.objective_new_oku_yen_per_year:.4f} "
            f"equipment_old={point.equipment_old_oku_yen_per_year:.4f} "
            f"equipment_new={point.equipment_new_oku_yen_per_year:.4f} "
            f"utility={point.utility_oku_yen_per_year:.4f} "
            f"shell_old={point.shell_old_oku_yen_per_year:.4f} "
            f"shell_new={point.shell_new_oku_yen_per_year:.4f} "
            "oku-yen/year"
        )

    if not points:
        return

    best = min(points, key=lambda point: point.objective_new_oku_yen_per_year)
    feed_text = "nan" if best.best_feed_stage is None else str(best.best_feed_stage)

    print(
        f"[ld-done] "
        f"best_N={best.stage_count} "
        f"best_feed={feed_text} "
        f"D={best.diameter_m:.3f} "
        f"H_original={best.height_m:.3f} "
        f"LD_original={best.ld_ratio:.3f} "
        f"split_count={best.split_count} "
        f"H_split={best.split_height_m:.3f} "
        f"LD_split={best.split_ld_ratio:.3f} "
        f"J_old={best.objective_old_oku_yen_per_year:.4f} "
        f"J_new={best.objective_new_oku_yen_per_year:.4f} "
        f"equipment_old={best.equipment_old_oku_yen_per_year:.4f} "
        f"equipment_new={best.equipment_new_oku_yen_per_year:.4f} "
        f"utility={best.utility_oku_yen_per_year:.4f} "
        f"shell_old={best.shell_old_oku_yen_per_year:.4f} "
        f"shell_new={best.shell_new_oku_yen_per_year:.4f} "
        f"figure={FIGURE_PATH}"
    )


def main() -> None:
    """貼り付けログからL/D補正後のcost summary図を作る。"""
    points = parse_cost_points(PASTE_LOG)
    if not points:
        raise RuntimeError("PASTE_LOG に描画できる [summary-case] ログがありません")

    figure_path = write_figure(points)
    print_summary(points)
    print(f"saved: {figure_path}")


if __name__ == "__main__":
    main()