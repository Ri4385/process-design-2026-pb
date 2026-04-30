"""反応器で扱う成分流量。"""

from __future__ import annotations

from dataclasses import dataclass


COMPONENT_ORDER: tuple[str, ...] = (
    "eb",
    "steam",
    "styrene",
    "hydrogen",
    "benzene",
    "toluene",
    "co2",
    "ethylene",
    "methane",
    "co",
)


@dataclass(frozen=True)
class ReactorStream:
    """反応器内外で扱う成分流量。単位は kmol/h。"""

    eb: float
    steam: float
    styrene: float = 0.0
    hydrogen: float = 0.0
    benzene: float = 0.0
    toluene: float = 0.0
    co2: float = 0.0
    ethylene: float = 0.0
    methane: float = 0.0
    co: float = 0.0

    def total_flow_kmol_h(self) -> float:
        """総モル流量を返す。"""
        return sum(self.to_component_flows_kmol_h().values())

    def total_flow_kmol_s(self) -> float:
        """総モル流量を kmol/s で返す。"""
        return self.total_flow_kmol_h() / 3600.0

    def to_component_flows_kmol_h(self) -> dict[str, float]:
        """成分名と kmol/h 流量の辞書を返す。"""
        return {name: float(getattr(self, name)) for name in COMPONENT_ORDER}

    def to_vector_kmol_s(self) -> list[float]:
        """内部計算順の kmol/s ベクトルへ変換する。"""
        flows = self.to_component_flows_kmol_h()
        return [flows[name] / 3600.0 for name in COMPONENT_ORDER]

    @classmethod
    def from_vector_kmol_s(cls, values: list[float]) -> ReactorStream:
        """内部計算順ベクトルから流量モデルへ変換する。"""
        values_kmol_h = {name: value * 3600.0 for name, value in zip(COMPONENT_ORDER, values, strict=True)}
        return cls(**values_kmol_h)


ReactorFeed = ReactorStream
