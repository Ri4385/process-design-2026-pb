"""Plant case model 定義。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from process_sim.reactor.cases.styrene_radial_default import RadialReactorCase


class SeparatorCondition(BaseModel):
    """default case で使う分離器条件。"""

    model_config = ConfigDict(frozen=True)

    decanter_1_temperature_c: float
    sm_column_reflux_ratio: float


class DefaultCase(BaseModel):
    """default 条件として扱う操作条件一式。"""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    steam_to_eb_ratio: float
    reactor: RadialReactorCase
    separator: SeparatorCondition
