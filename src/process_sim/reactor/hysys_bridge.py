"""反応器計算のI/O境界。

本モジュールは HYSYS に依存しない。
将来、全体最適化で HYSYS と連結する場合は、
この `ValueAccess` プロトコルを実装した別アダプタを用意して接続する。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from process_sim.constants import DEFAULT_REACTOR_CONFIG
from process_sim.reactor.models import HysysTagSet, ReactorFeed, ReactorRunConditions
from process_sim.reactor.simulator import StyreneReactorModel


class ValueAccess(Protocol):
    """外部シミュレータと値をやり取りするための最小インターフェース。"""

    def get_value(self, tag: str) -> float:
        ...

    def set_value(self, tag: str, value: float) -> None:
        ...


@dataclass
class DictValueAccess:
    """ローカル検証用の簡易 I/O。"""

    values: dict[str, float]

    def get_value(self, tag: str) -> float:
        if tag not in self.values:
            raise KeyError(f"Tag not found: {tag}")
        return float(self.values[tag])

    def set_value(self, tag: str, value: float) -> None:
        self.values[tag] = float(value)


@dataclass
class ReactorService:
    """外部I/Oと反応器モデルをつなぐサービス。"""

    access: ValueAccess
    tags: HysysTagSet

    def run_once(self) -> None:
        model = StyreneReactorModel(config=DEFAULT_REACTOR_CONFIG)

        feed = ReactorFeed(
            eb=self.access.get_value(self.tags.eb_feed_kmol_h),
            steam=self.access.get_value(self.tags.steam_feed_kmol_h),
            styrene=0.0,
            hydrogen=0.0,
            benzene=0.0,
            toluene=0.0,
            co2=0.0,
        )

        conditions = ReactorRunConditions(
            pressure_kpa=self.access.get_value(self.tags.pressure_kpa),
            temperature_c=self.access.get_value(self.tags.temperature_c),
            reactor_volume_m3=DEFAULT_REACTOR_CONFIG.operation.reactor_volume_m3,
            steps=DEFAULT_REACTOR_CONFIG.operation.integration_steps,
        )

        result = model.run(feed=feed, conditions=conditions)

        self.access.set_value(self.tags.eb_out_kmol_h, result.outlet.eb)
        self.access.set_value(self.tags.steam_out_kmol_h, result.outlet.steam)
        self.access.set_value(self.tags.styrene_out_kmol_h, result.outlet.styrene)
        self.access.set_value(self.tags.hydrogen_out_kmol_h, result.outlet.hydrogen)
        self.access.set_value(self.tags.benzene_out_kmol_h, result.outlet.benzene)
        self.access.set_value(self.tags.toluene_out_kmol_h, result.outlet.toluene)
        self.access.set_value(self.tags.co2_out_kmol_h, result.outlet.co2)
        self.access.set_value(self.tags.conversion_out, result.eb_conversion)
