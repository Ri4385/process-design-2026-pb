"""最小構成の固定層PFRモデル。"""

from __future__ import annotations

from dataclasses import dataclass

from process_sim.constants import ReactorConfigDefaults
from process_sim.reactor.kinetics import arrhenius_rate_constants
from process_sim.reactor.models import ReactorFeed, ReactorResult, ReactorRunConditions, ReactorState


@dataclass
class StyreneReactorModel:
    """EB 脱水素の単純 PFR モデル。"""

    config: ReactorConfigDefaults

    def run(self, feed: ReactorFeed, conditions: ReactorRunConditions) -> ReactorResult:
        """入口条件から出口状態を計算する。"""
        if conditions.steps <= 0:
            raise ValueError("steps must be positive")

        state = ReactorState(
            volume_m3=0.0,
            eb=max(feed.eb, 1e-12),
            steam=max(feed.steam, 0.0),
            styrene=max(feed.styrene, 0.0),
            hydrogen=max(feed.hydrogen, 0.0),
            benzene=max(feed.benzene, 0.0),
            toluene=max(feed.toluene, 0.0),
            co2=max(feed.co2, 0.0),
        )

        dv = conditions.reactor_volume_m3 / float(conditions.steps)
        temperature_k = conditions.temperature_c + 273.15
        k = arrhenius_rate_constants(
            temperature_k=temperature_k,
            kinetics=self.config.kinetics,
            universal=self.config.universal,
        )

        for idx in range(conditions.steps):
            total = max(
                state.eb
                + state.steam
                + state.styrene
                + state.hydrogen
                + state.benzene
                + state.toluene
                + state.co2,
                1e-12,
            )
            p_atm = conditions.pressure_kpa * self.config.universal.atm_per_kpa
            p_eb = p_atm * state.eb / total
            p_styrene = p_atm * state.styrene / total
            p_h2 = p_atm * state.hydrogen / total

            r1 = max(k.k11 * p_eb - k.k12 * p_styrene * p_h2, 0.0)
            r2 = max(k.k2 * p_eb, 0.0)
            r3 = max(k.k3 * p_eb, 0.0)

            d_eb = -(r1 + r2 + r3) * dv
            feasible_scale = 1.0
            if state.eb + d_eb < 0.0:
                feasible_scale = state.eb / max(-d_eb, 1e-12)

            r1 *= feasible_scale
            r2 *= feasible_scale
            r3 *= feasible_scale

            state = ReactorState(
                volume_m3=(idx + 1) * dv,
                eb=max(state.eb - (r1 + r2 + r3) * dv, 0.0),
                steam=max(state.steam - (4.0 * r2 + 2.0 * r3) * dv, 0.0),
                styrene=state.styrene + r1 * dv,
                hydrogen=state.hydrogen + (r1 + 6.0 * r2 + 3.0 * r3) * dv,
                benzene=state.benzene + r2 * dv,
                toluene=state.toluene + r3 * dv,
                co2=state.co2 + (2.0 * r2 + r3) * dv,
            )

        converted = max(feed.eb - state.eb, 0.0)
        eb_conversion = converted / max(feed.eb, 1e-12)
        styrene_selectivity = (state.styrene - feed.styrene) / max(converted, 1e-12)

        return ReactorResult(
            outlet=state,
            eb_conversion=eb_conversion,
            styrene_selectivity=max(styrene_selectivity, 0.0),
        )
