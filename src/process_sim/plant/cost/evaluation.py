"""全体プラントコスト評価の組み立て。"""

from __future__ import annotations

from process_sim.plant.const import DEFAULT_SM_PRODUCT_STYRENE_MOL_FRACTION
from process_sim.plant.convergence import PlantConvergenceResult
from process_sim.plant.cost.constants import LABOR_COST_YEN_PER_YEAR, MAINTENANCE_RATE_PER_YEAR
from process_sim.plant.cost.equipment import evaluate_capital_cost
from process_sim.plant.cost.models import CostBreakdownItem, FixedOperatingCostResult, WholePlantCostResult
from process_sim.plant.cost.revenue import evaluate_raw_material_cost, evaluate_revenue, revenue_warnings
from process_sim.plant.cost.tq import (
    build_external_utility_loads_with_heat_recovery,
    build_tq_streams_no_heat_recovery,
    build_tq_streams_with_heat_recovery,
)
from process_sim.plant.cost.utility import evaluate_utility_cost
from process_sim.separator.equipment import ProcessEquipment


def evaluate_whole_plant_cost(
    convergence_result: PlantConvergenceResult,
    equipment: ProcessEquipment,
) -> WholePlantCostResult:
    """収束済み plant と機器読み取り結果から年間収支を計算する。"""
    final_iteration = convergence_result.final_iteration
    if final_iteration.reactor_result is None:
        raise ValueError("final iteration reactor_result is missing")

    plant_record = final_iteration.plant_record
    revenue = evaluate_revenue(plant_record)
    raw_material = evaluate_raw_material_cost(convergence_result.feed_plan.steady_fresh_feed)
    capital = evaluate_capital_cost(equipment=equipment, reactor_result=final_iteration.reactor_result)
    utility = evaluate_utility_cost(
        plant_record=plant_record,
        equipment=equipment,
        reactor_result=final_iteration.reactor_result,
        heat_recovery=capital.heat_recovery,
    )
    fixed_operating = evaluate_fixed_operating_cost(capital.total_plant_capital_yen)
    annual_profit = (
        revenue.total_yen_per_year
        - raw_material.total_yen_per_year
        - capital.annualized_equipment_yen_per_year
        - utility.total_yen_per_year
        - fixed_operating.total_yen_per_year
    )
    return WholePlantCostResult(
        revenue=revenue,
        raw_material=raw_material,
        capital=capital,
        utility=utility,
        fixed_operating=fixed_operating,
        annual_profit_yen_per_year=annual_profit,
        tq_streams_no_heat_recovery=build_tq_streams_no_heat_recovery(
            equipment=equipment,
            reactor_result=final_iteration.reactor_result,
        ),
        tq_streams_with_heat_recovery=build_tq_streams_with_heat_recovery(
            equipment=equipment,
            reactor_result=final_iteration.reactor_result,
            heat_recovery=capital.heat_recovery,
        ),
        external_utility_loads_with_heat_recovery=build_external_utility_loads_with_heat_recovery(
            equipment=equipment,
            reactor_result=final_iteration.reactor_result,
            heat_recovery=capital.heat_recovery,
        ),
        warnings=cost_warnings(convergence_result),
    )


def evaluate_fixed_operating_cost(total_plant_capital_yen: float) -> FixedOperatingCostResult:
    """人件費と保全費を計算する。"""
    labor = CostBreakdownItem(name="labor", yen_per_year=LABOR_COST_YEN_PER_YEAR)
    maintenance = CostBreakdownItem(
        name="maintenance",
        yen_per_year=total_plant_capital_yen * MAINTENANCE_RATE_PER_YEAR,
        note="3% of total plant capital",
    )
    return FixedOperatingCostResult(
        labor=labor,
        maintenance=maintenance,
        total_yen_per_year=labor.yen_per_year + maintenance.yen_per_year,
    )


def cost_warnings(convergence_result: PlantConvergenceResult) -> tuple[str, ...]:
    """コスト評価で出す警告を作る。"""
    final = convergence_result.final_iteration
    plant_record = final.plant_record
    warnings = list(revenue_warnings(plant_record))
    purity_warning = sm_purity_warning(convergence_result)
    if purity_warning is not None:
        warnings.append(purity_warning)
    return tuple(warnings)


def sm_purity_warning(convergence_result: PlantConvergenceResult) -> str | None:
    """SM product 純度が規定未満の場合に警告を返す。"""
    stream = convergence_result.final_iteration.plant_record.streams.get("sm_product")
    if stream is None:
        return "sm_product stream is missing"
    styrene_fraction = stream.component_molar_fraction.get("Styrene")
    if styrene_fraction is None:
        return "sm_product Styrene mol fraction is missing"
    if styrene_fraction >= DEFAULT_SM_PRODUCT_STYRENE_MOL_FRACTION:
        return None
    return (
        "SM product purity is below target: "
        f"{styrene_fraction:.6f} < {DEFAULT_SM_PRODUCT_STYRENE_MOL_FRACTION:.6f}"
    )
