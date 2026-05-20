"""ラジアルフロー反応器の幾何計算。"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RadialBedGeometry:
    """環状触媒層の幾何を表す。"""

    inner_radius_m: float
    bed_height_m: float
    bed_thickness_m: float
    catalyst_bulk_density_kg_m3: float

    def __post_init__(self) -> None:
        """幾何パラメータの正値を確認する。"""
        if self.inner_radius_m <= 0.0:
            raise ValueError("inner_radius_m must be positive")
        if self.bed_height_m <= 0.0:
            raise ValueError("bed_height_m must be positive")
        if self.bed_thickness_m <= 0.0:
            raise ValueError("bed_thickness_m must be positive")
        if self.catalyst_bulk_density_kg_m3 <= 0.0:
            raise ValueError("catalyst_bulk_density_kg_m3 must be positive")

    @property
    def outer_radius_m(self) -> float:
        """触媒床外半径を返す。"""
        return self.inner_radius_m + self.bed_thickness_m

    def radius_at(self, bed_fraction: float) -> float:
        """触媒層厚み方向の無次元位置から半径を返す。"""
        if bed_fraction < 0.0 or bed_fraction > 1.0:
            raise ValueError("bed_fraction must be between 0 and 1")
        return self.inner_radius_m + self.bed_thickness_m * bed_fraction

    def flow_area_m2(self, radius_m: float) -> float:
        """ラジアル流れに垂直な円筒面積を返す。"""
        if radius_m <= 0.0:
            raise ValueError("radius_m must be positive")
        return 2.0 * math.pi * radius_m * self.bed_height_m

    @property
    def catalyst_volume_m3(self) -> float:
        """触媒体積を返す。"""
        return math.pi * self.bed_height_m * (self.outer_radius_m**2 - self.inner_radius_m**2)

    @property
    def catalyst_mass_kg(self) -> float:
        """触媒質量を返す。"""
        return self.catalyst_bulk_density_kg_m3 * self.catalyst_volume_m3
