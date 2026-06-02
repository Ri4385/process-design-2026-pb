"""Plant-level feed construction utilities."""

from __future__ import annotations

from dataclasses import dataclass

from process_sim.plant.models import PlantStreamRecord
from process_sim.reactor.core.stream import COMPONENT_ORDER, ReactorFeed


HYSYS_COMPONENT_TO_REACTOR_FIELD: dict[str, str] = {
    "methane": "methane",
    "ethylene": "ethylene",
    "styrene": "styrene",
    "styrenemonomer": "styrene",
    "ebenzene": "eb",
    "ethylbenzene": "eb",
    "eb": "eb",
    "toluene": "toluene",
    "benzene": "benzene",
    "co2": "co2",
    "carbondioxide": "co2",
    "co": "co",
    "carbonmonoxide": "co",
    "h2o": "steam",
    "water": "steam",
    "steam": "steam",
    "hydrogen": "hydrogen",
    "h2": "hydrogen",
}


@dataclass(frozen=True)
class FreshFeedPolicy:
    """fresh 原料から反応器成分流量を作るための設定。"""

    eb_mol_fraction: float = 0.99
    benzene_mol_fraction: float = 0.005
    toluene_mol_fraction: float = 0.005
    steam_to_fresh_eb_ratio: float = 5.0


@dataclass(frozen=True)
class FreshFeed:
    """調整対象にする fresh feed。単位は kmol/h。"""

    hydrocarbon_kmol_h: float
    steam_kmol_h: float


def fresh_feed_from_hydrocarbon_flow(
    hydrocarbon_kmol_h: float,
    policy: FreshFeedPolicy = FreshFeedPolicy(),
) -> FreshFeed:
    """炭化水素 fresh feed 流量から、同時に投入する水流量を決める。"""
    fresh_eb = hydrocarbon_kmol_h * policy.eb_mol_fraction
    return FreshFeed(
        hydrocarbon_kmol_h=hydrocarbon_kmol_h,
        steam_kmol_h=fresh_eb * policy.steam_to_fresh_eb_ratio,
    )


def normalized_component_name(name: str) -> str:
    """成分名比較用に正規化する。"""
    return "".join(character for character in name.lower() if character.isalnum())


def empty_reactor_feed() -> ReactorFeed:
    """全成分 0 の反応器 feed を返す。"""
    return ReactorFeed(**{component: 0.0 for component in COMPONENT_ORDER})


def reactor_feed_from_plant_stream(stream: PlantStreamRecord | None) -> ReactorFeed:
    """HYSYS stream 記録を反応器成分の流量へ変換する。"""
    flows = {component: 0.0 for component in COMPONENT_ORDER}
    if stream is None:
        return ReactorFeed(**flows)

    for component_name, value in stream.component_molar_flow_kmol_h.items():
        field_name = HYSYS_COMPONENT_TO_REACTOR_FIELD.get(normalized_component_name(component_name))
        if field_name is not None:
            flows[field_name] += value
    return ReactorFeed(**flows)


def fresh_feed_to_reactor_feed(
    fresh_feed: FreshFeed,
    policy: FreshFeedPolicy = FreshFeedPolicy(),
) -> ReactorFeed:
    """fresh feed を反応器 feed 成分へ変換する。"""
    return ReactorFeed(
        eb=fresh_feed.hydrocarbon_kmol_h * policy.eb_mol_fraction,
        steam=fresh_feed.steam_kmol_h,
        benzene=fresh_feed.hydrocarbon_kmol_h * policy.benzene_mol_fraction,
        toluene=fresh_feed.hydrocarbon_kmol_h * policy.toluene_mol_fraction,
    )


def add_reactor_feeds(*feeds: ReactorFeed) -> ReactorFeed:
    """複数の反応器 feed を成分ごとに合算する。"""
    values = {
        component: sum(getattr(feed, component) for feed in feeds)
        for component in COMPONENT_ORDER
    }
    return ReactorFeed(**values)


def build_reactor_feed(
    fresh_feed: FreshFeed,
    eb_recycle: ReactorFeed | None = None,
    water_recycle: ReactorFeed | None = None,
    policy: FreshFeedPolicy = FreshFeedPolicy(),
) -> ReactorFeed:
    """fresh feed と recycle から反応器入口 feed を作る。"""
    return add_reactor_feeds(
        fresh_feed_to_reactor_feed(fresh_feed=fresh_feed, policy=policy),
        eb_recycle or empty_reactor_feed(),
        water_recycle or empty_reactor_feed(),
    )
