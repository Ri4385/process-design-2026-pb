"""分離器込み全体最適化の探索範囲。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from process_sim.optimization.models import ParameterRange


DECANTER_1_TEMPERATURE_RANGE_C = ParameterRange(lower=55.0, upper=80.0)
SM_COLUMN_REFLUX_RATIO_RANGE = ParameterRange(lower=6.3, upper=8.5)


class SeparatorOperatingCandidate(BaseModel):
    """分離器操作条件の候補。"""

    model_config = ConfigDict(frozen=True)

    decanter_1_temperature_c: float
    sm_column_reflux_ratio: float
