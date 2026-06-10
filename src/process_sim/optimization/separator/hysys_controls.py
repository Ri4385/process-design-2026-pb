"""分離器操作条件を HYSYS 書き込み plan へ変換する。"""

from __future__ import annotations

from process_sim.optimization.separator.parameters import SeparatorOperatingCandidate
from process_sim.plant.hysys_controls import (
    DistillationRefluxRatioWriteSpec,
    HysysControlPlan,
    TemperatureMaterialStreamWriteSpec,
)


SEPARATOR_FEED_STREAM_NAME = "separator_feed"
SM_COLUMN_ID = "sm_column"
SM_COLUMN_OPERATION_NAME = "T-1"


def build_separator_control_plan(candidate: SeparatorOperatingCandidate) -> HysysControlPlan:
    """分離器操作候補から HYSYS 書き込み plan を作る。"""
    return HysysControlPlan(
        temperature_material_streams=(
            TemperatureMaterialStreamWriteSpec(
                stream_name=SEPARATOR_FEED_STREAM_NAME,
                temperature_c=candidate.decanter_1_temperature_c,
            ),
        ),
        distillation_reflux_ratios=(
            DistillationRefluxRatioWriteSpec(
                column_id=SM_COLUMN_ID,
                operation_name=SM_COLUMN_OPERATION_NAME,
                reflux_ratio=candidate.sm_column_reflux_ratio,
            ),
        ),
    )


def merge_hysys_control_plans(*plans: HysysControlPlan) -> HysysControlPlan:
    """複数の HYSYS 書き込み plan を結合する。"""
    return HysysControlPlan(
        full_material_streams=tuple(
            spec for plan in plans for spec in plan.full_material_streams
        ),
        pressure_material_streams=tuple(
            spec for plan in plans for spec in plan.pressure_material_streams
        ),
        temperature_material_streams=tuple(
            spec for plan in plans for spec in plan.temperature_material_streams
        ),
        operations=tuple(spec for plan in plans for spec in plan.operations),
        distillation_reflux_ratios=tuple(
            spec for plan in plans for spec in plan.distillation_reflux_ratios
        ),
    )
