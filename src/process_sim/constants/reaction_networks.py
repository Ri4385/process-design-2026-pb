"""反応ネットワーク定義。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArrheniusTerm:
    """アレニウス式 k = A exp(-E/RT) のパラメータ。"""

    pre_exponential: float
    activation_energy_j_per_mol: float
    partial_pressure_orders: dict[str, float]


@dataclass(frozen=True)
class ReactionDefinition:
    """単一反応の定義。"""

    reaction_id: str
    name: str
    stoichiometry: dict[str, float]
    rate: ArrheniusTerm


@dataclass(frozen=True)
class ReversibleReactionDefinition:
    """正逆反応を正味速度として扱う反応の定義。"""

    reaction_id: str
    name: str
    stoichiometry: dict[str, float]
    forward_rate: ArrheniusTerm
    backward_rate: ArrheniusTerm


ReactionNetworkItem = ReactionDefinition | ReversibleReactionDefinition


@dataclass(frozen=True)
class ReactionNetwork:
    """反応ネットワーク。"""

    name: str
    source: str
    reactions: tuple[ReactionNetworkItem, ...]


STYRENE_SIX_REACTION_NETWORK = ReactionNetwork(
    name="styrene_six_reaction_chem_contest",
    source="data/chem_contest.md 5-2 反応モデル",
    reactions=(
        ReversibleReactionDefinition(
            reaction_id="r1",
            name="EB ⇆ SM + H2",
            stoichiometry={"eb": -1.0, "styrene": 1.0, "hydrogen": 1.0},
            forward_rate=ArrheniusTerm(
                pre_exponential=0.0473,
                activation_energy_j_per_mol=90_981.0,
                partial_pressure_orders={"eb": 1.0},
            ),
            backward_rate=ArrheniusTerm(
                pre_exponential=5.58e-8,
                activation_energy_j_per_mol=61_127.0,
                partial_pressure_orders={"styrene": 1.0, "hydrogen": 1.0},
            ),
        ),
        ReactionDefinition(
            reaction_id="r2",
            name="EB -> BZ + C2H4",
            stoichiometry={"eb": -1.0, "benzene": 1.0, "ethylene": 1.0},
            rate=ArrheniusTerm(
                pre_exponential=8_267.0,
                activation_energy_j_per_mol=207_989.0,
                partial_pressure_orders={"eb": 1.0},
            ),
        ),
        ReactionDefinition(
            reaction_id="r3",
            name="EB + H2 -> TL + CH4",
            stoichiometry={"eb": -1.0, "hydrogen": -1.0, "toluene": 1.0, "methane": 1.0},
            rate=ArrheniusTerm(
                pre_exponential=4.0385e-7,
                activation_energy_j_per_mol=91_515.0,
                partial_pressure_orders={"eb": 1.0, "hydrogen": 1.0},
            ),
        ),
        ReactionDefinition(
            reaction_id="r4",
            name="2H2O + C2H4 -> 2CO + 4H2",
            stoichiometry={"steam": -2.0, "ethylene": -1.0, "co": 2.0, "hydrogen": 4.0},
            rate=ArrheniusTerm(
                pre_exponential=1.1535e-5,
                activation_energy_j_per_mol=103_997.0,
                partial_pressure_orders={"steam": 1.0, "ethylene": 0.5},
            ),
        ),
        ReactionDefinition(
            reaction_id="r5",
            name="H2O + CH4 -> CO + 3H2",
            stoichiometry={"steam": -1.0, "methane": -1.0, "co": 1.0, "hydrogen": 3.0},
            rate=ArrheniusTerm(
                pre_exponential=4.314e-9,
                activation_energy_j_per_mol=65_723.0,
                partial_pressure_orders={"steam": 1.0, "methane": 1.0},
            ),
        ),
        ReactionDefinition(
            reaction_id="r6",
            name="H2O + CO -> CO2 + H2",
            stoichiometry={"steam": -1.0, "co": -1.0, "co2": 1.0, "hydrogen": 1.0},
            rate=ArrheniusTerm(
                pre_exponential=8.059e-4,
                activation_energy_j_per_mol=73_638.0,
                partial_pressure_orders={"steam": 1.0, "co": 1.0},
            ),
        ),
    ),
)
