"""最適化の共通モデル。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParameterRange:
    """連続値の探索範囲。"""

    # 探索範囲の下限値。
    lower: float
    # 探索範囲の上限値。
    upper: float

    def __post_init__(self) -> None:
        """探索範囲そのものの整合性を検証する。"""
        if self.lower >= self.upper:
            raise ValueError("lower must be smaller than upper")
