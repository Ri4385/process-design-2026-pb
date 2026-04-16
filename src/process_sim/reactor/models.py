"""反応器計算で使うモデル。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReactorFeed:
    """反応器入口流量。単位は kmol/h。"""

    eb: float
    steam: float
    styrene: float = 0.0
    hydrogen: float = 0.0
    benzene: float = 0.0
    toluene: float = 0.0
    co2: float = 0.0


@dataclass(frozen=True)
class ReactorState:
    """反応器内の状態。"""

    volume_m3: float
    eb: float
    steam: float
    styrene: float
    hydrogen: float
    benzene: float
    toluene: float
    co2: float


@dataclass(frozen=True)
class ReactorResult:
    """反応器出口結果。"""

    outlet: ReactorState
    eb_conversion: float
    styrene_selectivity: float


@dataclass(frozen=True)
class HysysTagSet:
    """HYSYS から読み書きするタグ名。"""

    eb_feed_kmol_h: str
    steam_feed_kmol_h: str
    pressure_kpa: str
    temperature_c: str

    eb_out_kmol_h: str
    steam_out_kmol_h: str
    styrene_out_kmol_h: str
    hydrogen_out_kmol_h: str
    benzene_out_kmol_h: str
    toluene_out_kmol_h: str
    co2_out_kmol_h: str
    conversion_out: str


@dataclass(frozen=True)
class ReactorRunConditions:
    """シミュレーション条件。"""

    pressure_kpa: float
    temperature_c: float
    reactor_volume_m3: float
    steps: int
