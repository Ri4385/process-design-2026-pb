"""反応器計算で使うモデル。"""

from __future__ import annotations

from dataclasses import dataclass


INTERNAL_COMPONENT_ORDER = (
    "styrene",
    "eb",
    "toluene",
    "steam",
    "benzene",
    "co2",
    "ethylene",
    "methane",
    "co",
    "hydrogen",
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
        return (
            self.eb
            + self.steam
            + self.styrene
            + self.hydrogen
            + self.benzene
            + self.toluene
            + self.co2
            + self.ethylene
            + self.methane
            + self.co
        )

    def total_flow_kmol_s(self) -> float:
        """総モル流量を kmol/s で返す。"""
        return self.total_flow_kmol_h() / 3600.0

    def to_internal_vector_kmol_s(self) -> list[float]:
        """内部計算順のベクトルへ変換する。"""
        values_kmol_h = {
            "eb": self.eb,
            "steam": self.steam,
            "styrene": self.styrene,
            "hydrogen": self.hydrogen,
            "benzene": self.benzene,
            "toluene": self.toluene,
            "co2": self.co2,
            "ethylene": self.ethylene,
            "methane": self.methane,
            "co": self.co,
        }
        return [values_kmol_h[name] / 3600.0 for name in INTERNAL_COMPONENT_ORDER]

    @classmethod
    def from_internal_vector_kmol_s(cls, values: list[float]) -> ReactorStream:
        """内部計算順ベクトルから流量モデルへ変換する。"""
        values_kmol_h = {name: value * 3600.0 for name, value in zip(INTERNAL_COMPONENT_ORDER, values, strict=True)}
        return cls(
            eb=values_kmol_h["eb"],
            steam=values_kmol_h["steam"],
            styrene=values_kmol_h["styrene"],
            hydrogen=values_kmol_h["hydrogen"],
            benzene=values_kmol_h["benzene"],
            toluene=values_kmol_h["toluene"],
            co2=values_kmol_h["co2"],
            ethylene=values_kmol_h["ethylene"],
            methane=values_kmol_h["methane"],
            co=values_kmol_h["co"],
        )


ReactorFeed = ReactorStream


@dataclass(frozen=True)
class ReactorRunConditions:
    """3段断熱反応器列のシミュレーション条件。"""

    pressure_kpa: float
    stage_inlet_temperatures_c: tuple[float, float, float]
    stage_lengths_m: tuple[float, float, float]
    inlet_superficial_velocity_m_per_s: float
    segments_per_stage: int
    profile_points_per_stage: int


@dataclass(frozen=True)
class ReactorState:
    """反応器列中の状態。"""

    stage_index: int
    axial_position_m: float
    cumulative_length_m: float
    temperature_c: float
    pressure_kpa: float
    stream: ReactorStream


@dataclass(frozen=True)
class ReactorProfilePoint:
    """軸方向プロファイルの記録点。"""

    stage_index: int
    axial_position_m: float
    cumulative_length_m: float
    temperature_c: float
    eb_conversion: float
    styrene_selectivity: float
    stream: ReactorStream


@dataclass(frozen=True)
class ReactorStageLog:
    """各段の要約ログ。"""

    stage_index: int
    inlet_temperature_c: float
    outlet_temperature_c: float
    stage_length_m: float
    inlet_superficial_velocity_m_per_s: float
    outlet_superficial_velocity_m_per_s: float
    eb_conversion: float
    styrene_selectivity: float
    reheat_duty_mw: float | None
    inlet: ReactorStream
    outlet: ReactorStream


@dataclass(frozen=True)
class ReactorRunLog:
    """反応器列全体のログ。"""

    cross_section_area_m2: float
    inlet_volumetric_flow_m3_s: float
    stage_logs: tuple[ReactorStageLog, ...]
    profile: tuple[ReactorProfilePoint, ...]


@dataclass(frozen=True)
class ReactorResult:
    """反応器列の計算結果。"""

    outlet: ReactorState
    eb_conversion: float
    styrene_selectivity: float
    log: ReactorRunLog
