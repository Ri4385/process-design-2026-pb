"""反応ネットワークの評価。"""

from __future__ import annotations

from dataclasses import dataclass

from process_sim.constants.reaction_networks import ReactionNetwork, ReversibleReactionDefinition
from process_sim.constants.universal import UniversalConstants
from process_sim.reactor.core.kinetics import reaction_rate_from_partial_pressures


@dataclass(frozen=True)
class ReactionRate:
    """単一反応の正味速度。"""

    reaction_id: str
    rate_kmol_per_s_m3: float


def reaction_rates(
    network: ReactionNetwork,
    temperature_k: float,
    partial_pressures_pa: dict[str, float],
    universal: UniversalConstants,
) -> tuple[ReactionRate, ...]:
    """反応ネットワークの正味速度を返す。"""
    rates: list[ReactionRate] = []
    for reaction in network.reactions:
        if isinstance(reaction, ReversibleReactionDefinition):
            forward = reaction_rate_from_partial_pressures(
                temperature_k=temperature_k,
                partial_pressures_pa=partial_pressures_pa,
                term=reaction.forward_rate,
                universal=universal,
            )
            backward = reaction_rate_from_partial_pressures(
                temperature_k=temperature_k,
                partial_pressures_pa=partial_pressures_pa,
                term=reaction.backward_rate,
                universal=universal,
            )
            rate = forward - backward
        else:
            rate = reaction_rate_from_partial_pressures(
                temperature_k=temperature_k,
                partial_pressures_pa=partial_pressures_pa,
                term=reaction.rate,
                universal=universal,
            )
        rates.append(ReactionRate(reaction_id=reaction.reaction_id, rate_kmol_per_s_m3=rate))
    return tuple(rates)
