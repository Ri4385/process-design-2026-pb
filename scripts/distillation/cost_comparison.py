"""蒸留分離シーケンスのコスト比較図を作成する。"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import japanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt
from pydantic import BaseModel


SCRIPT_DIR = Path(__file__).resolve().parent
MEDIA_DIR = SCRIPT_DIR / "media"

TOTAL_FIGURE_PATH = MEDIA_DIR / "sequence_cost_comparison.png"


class ColumnCost(BaseModel):
    """蒸留塔1基の最適化後コスト。"""

    label: str
    stage_count: int
    feed_stage: int
    equipment_oku_yen_per_year: float
    utility_oku_yen_per_year: float

    @property
    def total_oku_yen_per_year(self) -> float:
        """年間総コストを億円/yearで返す。"""
        return self.equipment_oku_yen_per_year + self.utility_oku_yen_per_year


class SequenceCost(BaseModel):
    """蒸留分離シーケンス1案のコスト。"""

    label: str
    columns: tuple[ColumnCost, ...]

    @property
    def equipment_oku_yen_per_year(self) -> float:
        """装置コスト合計を億円/yearで返す。"""
        return sum(column.equipment_oku_yen_per_year for column in self.columns)

    @property
    def utility_oku_yen_per_year(self) -> float:
        """用役コスト合計を億円/yearで返す。"""
        return sum(column.utility_oku_yen_per_year for column in self.columns)

    @property
    def total_oku_yen_per_year(self) -> float:
        """評価関数合計を億円/yearで返す。"""
        return self.equipment_oku_yen_per_year + self.utility_oku_yen_per_year


SEQUENCES: tuple[SequenceCost, ...] = (
    SequenceCost(
        label="シーケンス1",
        columns=(
            ColumnCost(
                label="SM分離塔",
                stage_count=106,
                feed_stage=73,
                equipment_oku_yen_per_year=2.1913,
                utility_oku_yen_per_year=4.3482,
            ),
            ColumnCost(
                label="EB回収塔",
                stage_count=64,
                feed_stage=23,
                equipment_oku_yen_per_year=0.2951,
                utility_oku_yen_per_year=0.6725,
            ),
            ColumnCost(
                label="BZ/TL分離塔",
                stage_count=31,
                feed_stage=15,
                equipment_oku_yen_per_year=0.0673,
                utility_oku_yen_per_year=0.0335,
            ),
        ),
    ),
    SequenceCost(
        label="シーケンス3",
        columns=(
            ColumnCost(
                label="蒸留塔1",
                stage_count=106,
                feed_stage=21,
                equipment_oku_yen_per_year=0.8259,
                utility_oku_yen_per_year=1.9338,
            ),
            ColumnCost(
                label="SMEB分離塔",
                stage_count=106,
                feed_stage=72,
                equipment_oku_yen_per_year=2.1418,
                utility_oku_yen_per_year=3.9650,
            ),
            ColumnCost(
                label="BZ/TL分離塔",
                stage_count=30,
                feed_stage=15,
                equipment_oku_yen_per_year=0.0670,
                utility_oku_yen_per_year=0.0372,
            ),
        ),
    ),
)


def configure_axes(top_ticks: bool = True, bottom_ticks: bool = True) -> None:
    """グラフの目盛と枠線を設定する。"""
    axes = plt.gca()
    axes.grid(False)
    axes.tick_params(
        direction="in",
        top=top_ticks,
        right=True,
        bottom=bottom_ticks,
        left=True,
    )


def write_total_cost_figure(sequences: Sequence[SequenceCost]) -> Path:
    """シーケンス別の塔ごとの総コスト比較図を保存する。"""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    x_positions = list(range(len(sequences)))
    total_values = [sequence.total_oku_yen_per_year for sequence in sequences]
    labels = tuple(dict.fromkeys(column.label for sequence in sequences for column in sequence.columns))
    bottoms = [0.0 for _ in sequences]

    plt.figure(figsize=(7, 5))
    configure_axes(top_ticks=False, bottom_ticks=False)
    for label in labels:
        values = [
            next(
                (
                    column.total_oku_yen_per_year
                    for column in sequence.columns
                    if column.label == label
                ),
                0.0,
            )
            for sequence in sequences
        ]
        plt.bar(
            x_positions,
            values,
            bottom=bottoms,
            label=label,
            alpha=0.85,
        )
        bottoms = [bottom + value for bottom, value in zip(bottoms, values, strict=True)]

    axes = plt.gca()
    for x_position, value in zip(x_positions, total_values, strict=True):
        axes.text(
            x_position,
            value,
            f"{value:.2f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    plt.xticks(x_positions, [sequence.label for sequence in sequences])
    plt.ylabel("コスト [億円/year]")
    plt.ylim(top=max(total_values) * 1.15)
    plt.legend()
    plt.tight_layout()
    plt.savefig(TOTAL_FIGURE_PATH, dpi=200)
    plt.close()
    return TOTAL_FIGURE_PATH


def print_summary(sequences: Sequence[SequenceCost]) -> None:
    """シーケンス比較のsummaryを標準出力へ表示する。"""
    for sequence in sequences:
        print(
            f"[sequence] name={sequence.label} "
            f"J={sequence.total_oku_yen_per_year:.4f} "
            f"equipment={sequence.equipment_oku_yen_per_year:.4f} "
            f"utility={sequence.utility_oku_yen_per_year:.4f} "
            "oku-yen/year"
        )
        for column in sequence.columns:
            print(
                f"[sequence-column] name={sequence.label} "
                f"tower={column.label} "
                f"N={column.stage_count} "
                f"feed={column.feed_stage} "
                f"J={column.total_oku_yen_per_year:.4f} "
                f"equipment={column.equipment_oku_yen_per_year:.4f} "
                f"utility={column.utility_oku_yen_per_year:.4f} "
                "oku-yen/year"
            )

    best = min(sequences, key=lambda sequence: sequence.total_oku_yen_per_year)
    print(f"[done] best_sequence={best.label} J={best.total_oku_yen_per_year:.4f} oku-yen/year")


def main() -> None:
    """定数化したコストからシーケンス比較図を作成する。"""
    total_figure_path = write_total_cost_figure(SEQUENCES)
    print_summary(SEQUENCES)
    print(f"saved: {total_figure_path}")


if __name__ == "__main__":
    main()
