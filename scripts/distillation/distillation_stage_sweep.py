"""蒸留塔の段数 case ごとに feed 段を sweep して部分最適化する。

探索順:
1. case を開く
2. base feed を評価する
3. base から下方向へ連続探索する
4. timeout などで不安定になったら、その方向の探索を打ち切る
5. case を開き直す
6. base から上方向へ連続探索する
7. 結果を結合して最良 feed 段を選ぶ

評価関数:
J = 装置コスト + 用役コスト

装置コスト:
蒸留塔本体 + コンデンサ + リボイラを7年償却

用役コスト:
既存の製品冷却・EB recycle加熱
+ 蒸留塔コンデンサ冷却用役
+ 蒸留塔リボイラ加熱用役
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal, Sequence, TypeVar

import japanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt
from pydantic import BaseModel, ConfigDict

from process_sim.plant.const import HOURS_PER_YEAR, HYSYS_INVALID_SENTINEL
from process_sim.plant.economics import (
    cooling_utility_cost_yen_per_year,
    cooling_water_cost_yen_per_year,
    steam_heating_cost_yen_per_year,
)
from process_sim.separator.hysys_io import (
    get_energy_stream,
    get_flowsheet,
    get_material_stream,
    get_operation,
    get_quantity,
    hysys_case,
    iter_collection_items,
)

raise NotImplementedError("これは蒸留塔以外のコストも考えている(製品冷却やリサイクル加熱)のでv2を使ってください。")

TargetTower = Literal["tower1", "tower2", "tower3"]
GridLevel = Literal["coarse", "fine"]
SweepDirection = Literal["base_lower", "upper"]
T = TypeVar("T")

TARGET_TOWER: TargetTower = "tower2"
GRID_LEVEL: GridLevel = "coarse"

DETAILED_FEED_LOG = True
VERBOSE = True
VISIBLE_HYSYS = False

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
HYSYS_DIR = SCRIPT_DIR / "hysys"
MEDIA_DIR = SCRIPT_DIR / "media"
LOG_PATH = REPO_ROOT / "logs" / "distillation_stage_sweep.log"

TOWER_OPERATION_NAMES: dict[TargetTower, str] = {
    "tower1": "T-1",
    "tower2": "T-2",
    "tower3": "T-3",
}

TOWER_PRODUCT_COOLERS: dict[TargetTower, tuple[str, ...]] = {
    "tower1": ("C-3",),
    "tower2": (),
    "tower3": ("C-4", "C-5"),
}

TOWER_COLUMN_ENERGY_STREAMS: dict[TargetTower, dict[str, str]] = {
    "tower1": {"condenser": "TQ-11", "reboiler": "TQ-12"},
    "tower2": {"condenser": "TQ-21", "reboiler": "TQ-22"},
    "tower3": {"condenser": "TQ-31", "reboiler": "TQ-32"},
}

YEN_PER_OKU_YEN = 1.0e8
DEPRECIATION_YEARS = 7.0

SOUDFERS_BROWN_SF = 0.8
SOUDFERS_BROWN_K_M_S = 0.05
GAS_CONSTANT_FACTOR = 8.314 * 1000.0

TRAY_SPACING_M = 0.6
TOP_ALLOWANCE_M = 2.0
BOTTOM_ALLOWANCE_M = 4.0
FEED_STAGE_ALLOWANCE_M = 1.0
LD_WARNING_LIMIT = 15.0

CONDENSER_U_W_M2_K = 1000.0
REBOILER_U_W_M2_K = 1500.0
HEAT_EXCHANGER_COST_FACTOR_YEN = 1_500_000.0
COLUMN_SHELL_COST_FACTOR_YEN = 1_500_000.0

CONDENSER_CW_INLET_C = 30.0
CONDENSER_CW_OUTLET_C = 45.0

LOW_PRESSURE_STEAM_C = 130.0
MEDIUM_PRESSURE_STEAM_C = 250.0
REBOILER_STEAM_SWITCH_C = 120.0

LOW_PRESSURE_STEAM_YEN_PER_MJ = 1.0
MEDIUM_PRESSURE_STEAM_YEN_PER_MJ = 1.4

PRODUCT_TARGET_TEMPERATURE_C = 38.0
COOLING_WATER_PROCESS_LIMIT_C = 50.0
COOLING_WATER_INLET_C = 30.0
COOLING_WATER_OUTLET_C = 45.0
COOLING_WATER_YEN_PER_TON = 10.0
WATER_CP_KJ_KG_K = 4.184
PROPYLENE_REFRIGERANT_YEN_PER_MJ = 0.8

EB_RECYCLE_STREAM_NAME = "eb_recycle"
EB_RECYCLE_TARGET_TEMPERATURE_C = 200.0

TOWER1_MAX_BOTTOM_TEMPERATURE_C = 100.0

HYSYS_READ_RETRY_COUNT = 5
HYSYS_READ_RETRY_WAIT_S = 0.8

FEED_TIMEOUT_S = 8.0
COLUMN_POST_SOLVE_WAIT_S = 1.0

STOP_DIRECTION_ON_UNSTABLE_INVALID = True
UNSTABLE_INVALID_KEYWORDS: tuple[str, ...] = (
    "timeout",
    "収束",
    "conver",
    "condenser duty",
    "reboiler duty",
    "取得できません",
)

FEED_STAGE_ATTR_NAMES: tuple[str, ...] = (
    "StageNumberValue",
    "StageNumber",
    "StageValue",
    "Stage",
    "TrayNumberValue",
    "TrayNumber",
    "TrayValue",
    "Tray",
    "Value",
)


class ColumnRefs(BaseModel):
    """HYSYS の塔参照。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    flowsheet: Any
    tower: Any
    column_flowsheet: Any


class ColumnHydraulics(BaseModel):
    """塔径計算に使う蒸留塔 profile 値。"""

    design_stage_index: int
    vapor_mass_flow: float
    liquid_mass_flow: float
    vapor_molar_flow: float
    temperature_c: float
    pressure_kpa: float
    liquid_volume_flow: float
    vapor_volume_flow: float
    vapor_density: float
    liquid_density: float
    allowable_mass_velocity: float
    diameter_m: float
    height_m: float
    ld_ratio: float


class ColumnHeatExchangerCost(BaseModel):
    """コンデンサーとリボイラーの装置費。"""

    condenser_stream_name: str
    reboiler_stream_name: str
    condenser_duty_kw: float
    reboiler_duty_kw: float
    top_temperature_c: float
    bottom_temperature_c: float
    condenser_area_m2: float
    reboiler_area_m2: float
    condenser_capital_cost_yen: float
    reboiler_capital_cost_yen: float


class FeedStageResult(BaseModel):
    """feed 段 1 点の評価結果。"""

    case_name: str
    sweep_direction: SweepDirection
    stage_count: int
    feed_stage: int
    actual_feed_stage: int | None = None
    valid: bool
    invalid_reason: str = ""
    equipment_cost_yen_per_year: float | None = None
    utility_cost_yen_per_year: float | None = None
    objective_yen_per_year: float | None = None
    diameter_m: float | None = None
    height_m: float | None = None
    ld_ratio: float | None = None
    ld_warning: bool = False
    bottom_temperature_c: float | None = None
    top_temperature_c: float | None = None
    condenser_duty_kw: float | None = None
    reboiler_duty_kw: float | None = None
    condenser_stream_name: str | None = None
    reboiler_stream_name: str | None = None


class CaseSweepResult(BaseModel):
    """HYSYS case 1 ファイルの最良 feed 段結果。"""

    case_name: str
    case_path: str
    stage_count: int | None
    valid: bool
    invalid_reason: str = ""
    best_feed_stage: int | None = None
    equipment_cost_yen_per_year: float | None = None
    utility_cost_yen_per_year: float | None = None
    objective_yen_per_year: float | None = None
    diameter_m: float | None = None
    height_m: float | None = None
    ld_ratio: float | None = None
    ld_warning: bool = False


def log(message: str) -> None:
    """進行状況を表示する。"""
    if VERBOSE:
        print(message, flush=True)


def log_file(message: str) -> None:
    """summary ログをファイルに追記する。"""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(f"{message}\n")


def log_summary(message: str) -> None:
    """標準出力と summary ログファイルへ出力する。"""
    log(message)
    log_file(message)


def log_step(
    case_name: str,
    feed_stage: int,
    step: str,
    detail: str = "",
) -> None:
    """feed 段ごとの途中経過を表示する。"""
    suffix = f" {detail}" if detail else ""
    log(f"[feed-step] file={case_name} feed={feed_stage} step={step}{suffix}")


def retry(label: str, func: Callable[[], T]) -> T:
    """COM 読み取りをリトライする。"""
    last_error: Exception | None = None
    for attempt in range(1, HYSYS_READ_RETRY_COUNT + 1):
        try:
            return func()
        except Exception as exc:
            last_error = exc
            log(
                f"[retry] label={label} "
                f"attempt={attempt}/{HYSYS_READ_RETRY_COUNT} "
                f"error={exc}"
            )
            if attempt < HYSYS_READ_RETRY_COUNT:
                time.sleep(HYSYS_READ_RETRY_WAIT_S)

    if last_error is None:
        raise RuntimeError(f"{label} failed without exception")
    raise last_error


def is_valid_number(value: float | None) -> bool:
    """HYSYS sentinel を除いた有効な数値か判定する。"""
    return (
        value is not None
        and math.isfinite(value)
        and not math.isclose(value, HYSYS_INVALID_SENTINEL)
    )


def required_number(value: float | None, name: str) -> float:
    """必須数値を取り出す。"""
    if not is_valid_number(value):
        raise RuntimeError(f"{name} を取得できませんでした")
    return float(value)


def cost_to_oku_yen_per_year(value: float | None) -> float:
    """円/year を億円/year に変換する。"""
    if value is None:
        return math.nan
    return value / YEN_PER_OKU_YEN


def object_name(obj: Any) -> str:
    """COM object の名前を返す。"""
    for attr_name in ("Name", "TaggedName", "TypeName"):
        value = getattr(obj, attr_name, None)
        if isinstance(value, str) and value:
            return value
    return ""


def object_type_name(obj: Any) -> str:
    """COM object の型名を返す。"""
    for attr_name in ("TypeName", "ObjectType"):
        value = getattr(obj, attr_name, None)
        if isinstance(value, str) and value:
            return value.lower()
    return type(obj).__name__.lower()


def numeric_values(obj: Any, attr_name: str) -> list[float]:
    """COM 属性から数値配列を取得する。"""
    value = getattr(obj, attr_name, None)
    if value is None:
        raise RuntimeError(f"{attr_name} がありません")
    try:
        return [float(item) for item in value]
    except TypeError as exc:
        raise RuntimeError(f"{attr_name} を配列として読めませんでした") from exc


def collection_count(collection: Any) -> int | None:
    """COM collection の Count を返す。"""
    try:
        return int(collection.Count)
    except Exception:
        return None


def collection_item_by_name(collection: Any, name: str) -> Any | None:
    """COM collection から名前一致の item を返す。"""
    if collection is None:
        return None

    item_method = getattr(collection, "Item", None)
    if callable(item_method):
        try:
            return item_method(name)
        except Exception:
            pass

    for item in iter_collection_items(collection):
        if object_name(item) == name:
            return item

    return None


def call_com_method_if_exists(obj: Any, method_names: Sequence[str]) -> bool:
    """COM object に存在する計算系 method を順に呼ぶ。"""
    for method_name in method_names:
        method = getattr(obj, method_name, None)
        if callable(method):
            try:
                method()
                return True
            except Exception as exc:
                log(f"[column-solve] method={method_name} error={exc}")
    return False


def stop_solver(simulation_case: Any) -> None:
    """HYSYS solver を止める。"""
    solver = getattr(simulation_case, "Solver", None)
    if solver is None:
        return
    try:
        solver.CanSolve = False
    except Exception:
        pass


def wait_for_hysys_calculation_limited(
    simulation_case: Any,
    timeout_s: float,
) -> None:
    """指定秒数だけ HYSYS の計算完了を待つ。"""
    solver = getattr(simulation_case, "Solver", None)
    if solver is None:
        return

    can_solve = getattr(solver, "CanSolve", None)
    if isinstance(can_solve, bool) and not can_solve:
        try:
            solver.CanSolve = True
        except Exception:
            pass

    for method_name in ("Solve", "Run"):
        method = getattr(solver, method_name, None)
        if callable(method):
            try:
                method()
                break
            except Exception:
                pass

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        is_solving = getattr(solver, "IsSolving", None)
        if not isinstance(is_solving, bool) or not is_solving:
            return
        time.sleep(0.2)

    stop_solver(simulation_case)
    raise TimeoutError(f"HYSYS calculation timeout after {timeout_s:.1f} s")


def fresh_column_refs(simulation_case: Any, target_tower: TargetTower) -> ColumnRefs:
    """flowsheet、tower、ColumnFlowsheet を毎回取り直す。"""
    flowsheet = get_flowsheet(simulation_case)
    tower = get_operation(flowsheet, TOWER_OPERATION_NAMES[target_tower])
    column_flowsheet = getattr(tower, "ColumnFlowsheet", None)
    if column_flowsheet is None:
        raise RuntimeError(
            f"{TOWER_OPERATION_NAMES[target_tower]}.ColumnFlowsheet を取得できませんでした"
        )
    return ColumnRefs(
        flowsheet=flowsheet,
        tower=tower,
        column_flowsheet=column_flowsheet,
    )


def available_energy_stream_names(collection: Any) -> list[str]:
    """energy stream collection の名前一覧を返す。"""
    return [object_name(item) for item in iter_collection_items(collection)]


def stage_count_from_column(column_flowsheet: Any) -> int:
    """ColumnFlowsheet から実トレイ数を読む。"""
    column_stages = getattr(column_flowsheet, "ColumnStages", None)
    count = collection_count(column_stages)
    if count is not None and count > 2:
        return count - 2
    if count is not None and count > 0:
        return count

    temperatures = numeric_values(column_flowsheet, "TemperaturesValue")
    if len(temperatures) > 2:
        return len(temperatures) - 2
    if temperatures:
        return len(temperatures)

    raise RuntimeError("ColumnStages から段数を取得できませんでした")


def find_traysection(column_flowsheet: Any) -> Any:
    """ColumnFlowsheet 内の traysection を取得する。"""
    operations = iter_collection_items(getattr(column_flowsheet, "Operations", None))
    for operation in operations:
        type_name = object_type_name(operation)
        name = object_name(operation).lower()
        if type_name == "traysection" or "tray" in type_name or name == "main tower":
            return operation
    raise RuntimeError("ColumnFlowsheet.Operations から traysection を取得できませんでした")


def first_feed_item(traysection: Any) -> Any:
    """traysection の最初の feed stream を返す。"""
    for attr_name in ("TraySectionFeeds", "Feeds", "MaterialFeeds", "AttachedFeeds"):
        items = iter_collection_items(getattr(traysection, attr_name, None))
        if items:
            return items[0]
    raise RuntimeError("traysection の feed stream を取得できませんでした")


def set_feed_stage(traysection: Any, feed_item: Any, feed_stage: int) -> None:
    """traysection の feed 段を指定する。"""
    method = getattr(traysection, "SpecifyFeedLocation", None)
    if not callable(method):
        raise RuntimeError("traysection.SpecifyFeedLocation が見つかりません")
    method(feed_item, feed_stage)


def set_solver_can_solve(simulation_case: Any, can_solve: bool) -> None:
    """HYSYS solver の CanSolve を設定する。"""
    solver = getattr(simulation_case, "Solver", None)
    if solver is None:
        return
    try:
        solver.CanSolve = can_solve
    except Exception:
        pass


def read_feed_stage_from_item(item: Any) -> int | None:
    """FeedColumnStages の item から feed 段を読む。"""
    for attr_name in FEED_STAGE_ATTR_NAMES:
        value = getattr(item, attr_name, None)
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    return None


def current_feed_stage(column_flowsheet: Any) -> int | None:
    """ColumnFlowsheet から現在の主 feed 段を読む。"""
    feed_stages = iter_collection_items(getattr(column_flowsheet, "FeedColumnStages", None))
    for item in feed_stages:
        stage = read_feed_stage_from_item(item)
        if stage is not None:
            return stage
    return None


def solve_column_after_feed_change(
    simulation_case: Any,
    target_tower: TargetTower,
    case_name: str,
    feed_stage: int,
) -> None:
    """feed 段変更後に column 側の再計算を明示的に促す。"""
    refs = fresh_column_refs(simulation_case, target_tower)

    log_step(case_name, feed_stage, "column-solve-start")

    call_com_method_if_exists(
        refs.column_flowsheet,
        ("Run", "Solve", "Calculate", "Recalculate"),
    )
    call_com_method_if_exists(
        refs.tower,
        ("Run", "Solve", "Calculate", "Recalculate"),
    )

    column_solver = getattr(refs.column_flowsheet, "Solver", None)
    if column_solver is not None:
        try:
            column_solver.CanSolve = True
        except Exception:
            pass
        call_com_method_if_exists(
            column_solver,
            ("Solve", "Run", "Calculate", "Recalculate"),
        )

    tower_solver = getattr(refs.tower, "Solver", None)
    if tower_solver is not None:
        try:
            tower_solver.CanSolve = True
        except Exception:
            pass
        call_com_method_if_exists(
            tower_solver,
            ("Solve", "Run", "Calculate", "Recalculate"),
        )

    wait_for_hysys_calculation_limited(simulation_case, FEED_TIMEOUT_S)
    time.sleep(COLUMN_POST_SOLVE_WAIT_S)

    log_step(case_name, feed_stage, "column-solve-done")


def apply_feed_stage(
    simulation_case: Any,
    case_name: str,
    target_tower: TargetTower,
    feed_stage: int,
) -> int | None:
    """指定 feed 段を必ず HYSYS に書き込んで、反映後の段を返す。"""
    log_step(case_name, feed_stage, "refresh-before-set")
    refs = fresh_column_refs(simulation_case, target_tower)

    before_stage = current_feed_stage(refs.column_flowsheet)
    log_step(case_name, feed_stage, "before-set", f"current_feed={before_stage}")

    traysection = find_traysection(refs.column_flowsheet)
    feed_item = first_feed_item(traysection)

    log_step(
        case_name,
        feed_stage,
        "set-feed",
        f"traysection={object_name(traysection)} feed_item={object_name(feed_item)}",
    )

    set_solver_can_solve(simulation_case, False)
    try:
        set_feed_stage(traysection, feed_item, feed_stage)
    finally:
        set_solver_can_solve(simulation_case, True)

    log_step(case_name, feed_stage, "case-solve-start")
    wait_for_hysys_calculation_limited(simulation_case, FEED_TIMEOUT_S)
    log_step(case_name, feed_stage, "case-solve-done")

    solve_column_after_feed_change(
        simulation_case=simulation_case,
        target_tower=target_tower,
        case_name=case_name,
        feed_stage=feed_stage,
    )

    refs = fresh_column_refs(simulation_case, target_tower)
    actual_stage = current_feed_stage(refs.column_flowsheet)
    log_step(case_name, feed_stage, "after-set", f"actual_feed={actual_stage}")

    return actual_stage


def column_height_m(stage_count: int) -> float:
    """段数から塔高さを計算する。"""
    return (
        TRAY_SPACING_M * (stage_count - 1)
        + TOP_ALLOWANCE_M
        + BOTTOM_ALLOWANCE_M
        + FEED_STAGE_ALLOWANCE_M
    )


def column_hydraulics(column_flowsheet: Any, stage_count: int) -> ColumnHydraulics:
    """ColumnFlowsheet profile から塔径と L/D を計算する。"""
    vapor_mass_flows = numeric_values(column_flowsheet, "NetMassVapourFlowsValue")
    liquid_mass_flows = numeric_values(column_flowsheet, "NetMassLiquidFlowsValue")
    vapor_molar_flows = numeric_values(column_flowsheet, "NetMolarVapourFlowsValue")
    temperatures = numeric_values(column_flowsheet, "TemperaturesValue")
    pressures = numeric_values(column_flowsheet, "PressuresValue")
    liquid_volume_flows = numeric_values(column_flowsheet, "NetLiqVolLiquidFlowsValue")

    required_lengths = {
        "NetMassVapourFlowsValue": len(vapor_mass_flows),
        "NetMassLiquidFlowsValue": len(liquid_mass_flows),
        "NetMolarVapourFlowsValue": len(vapor_molar_flows),
        "TemperaturesValue": len(temperatures),
        "PressuresValue": len(pressures),
        "NetLiqVolLiquidFlowsValue": len(liquid_volume_flows),
    }
    min_length = min(required_lengths.values())
    if min_length <= 0:
        raise RuntimeError(f"profile 配列が空です: {required_lengths}")

    candidates = [
        (index, value)
        for index, value in enumerate(vapor_mass_flows[:min_length])
        if is_valid_number(value)
    ]
    if not candidates:
        raise RuntimeError("有効な蒸気質量流量がありません")

    design_stage_index, vapor_mass_flow = max(candidates, key=lambda item: item[1])

    liquid_mass_flow = liquid_mass_flows[design_stage_index]
    vapor_molar_flow = vapor_molar_flows[design_stage_index]
    temperature_c = temperatures[design_stage_index]
    pressure_kpa = pressures[design_stage_index]
    liquid_volume_flow = liquid_volume_flows[design_stage_index]

    for name, value in (
        ("液質量流量", liquid_mass_flow),
        ("蒸気モル流量", vapor_molar_flow),
        ("温度", temperature_c),
        ("圧力", pressure_kpa),
        ("液体体積流量", liquid_volume_flow),
    ):
        required_number(value, f"design stage {design_stage_index + 1} {name}")

    if pressure_kpa <= 0.0:
        raise RuntimeError("圧力が 0 以下です")
    if liquid_volume_flow <= 0.0:
        raise RuntimeError("液体体積流量が 0 以下です")

    vapor_volume_flow = (
        vapor_molar_flow
        * GAS_CONSTANT_FACTOR
        * (273.15 + temperature_c)
        / (pressure_kpa * 1000.0)
    )
    if vapor_volume_flow <= 0.0:
        raise RuntimeError("蒸気体積流量が 0 以下です")

    vapor_density = vapor_mass_flow / vapor_volume_flow
    liquid_density = liquid_mass_flow / liquid_volume_flow
    if liquid_density <= vapor_density:
        raise RuntimeError(
            f"液密度 <= 蒸気密度です: rho_l={liquid_density}, rho_v={vapor_density}"
        )

    allowable_mass_velocity = (
        SOUDFERS_BROWN_SF
        * SOUDFERS_BROWN_K_M_S
        * math.sqrt(vapor_density * (liquid_density - vapor_density))
    )
    if allowable_mass_velocity <= 0.0:
        raise RuntimeError("許容質量速度が 0 以下です")

    diameter_m = math.sqrt(4.0 * vapor_mass_flow / (math.pi * allowable_mass_velocity))
    height_m = column_height_m(stage_count)
    ld_ratio = height_m / diameter_m

    return ColumnHydraulics(
        design_stage_index=design_stage_index,
        vapor_mass_flow=vapor_mass_flow,
        liquid_mass_flow=liquid_mass_flow,
        vapor_molar_flow=vapor_molar_flow,
        temperature_c=temperature_c,
        pressure_kpa=pressure_kpa,
        liquid_volume_flow=liquid_volume_flow,
        vapor_volume_flow=vapor_volume_flow,
        vapor_density=vapor_density,
        liquid_density=liquid_density,
        allowable_mass_velocity=allowable_mass_velocity,
        diameter_m=diameter_m,
        height_m=height_m,
        ld_ratio=ld_ratio,
    )


def read_quantity_as_kw(obj: Any, attr_names: Sequence[str], label: str) -> float:
    """HeatFlow/Duty 系の quantity を kW として読む。"""
    errors: list[str] = []

    for attr_name in attr_names:
        quantity = getattr(obj, attr_name, None)
        if quantity is not None:
            for unit, factor in (
                ("kW", 1.0),
                ("W", 1.0e-3),
                ("J/s", 1.0e-3),
                ("kJ/h", 1.0 / 3600.0),
            ):
                try:
                    value = float(quantity.GetValue(unit)) * factor
                    if is_valid_number(value):
                        return value
                except Exception as exc:
                    errors.append(f"{attr_name}.GetValue({unit}): {exc}")

            try:
                value = float(quantity.Value)
                if is_valid_number(value):
                    return value
            except Exception as exc:
                errors.append(f"{attr_name}.Value: {exc}")

        scalar_attr_name = f"{attr_name}Value"
        scalar_value = getattr(obj, scalar_attr_name, None)
        if isinstance(scalar_value, (int, float)):
            value = float(scalar_value)
            if is_valid_number(value):
                return value

    object_label = object_name(obj) or type(obj).__name__
    raise RuntimeError(
        f"{label} を取得できませんでした: object={object_label}, errors={errors[:5]}"
    )


def heat_flow_kw(energy_stream: Any, name: str) -> float:
    """energy stream の heat flow を kW で読む。"""
    return read_quantity_as_kw(
        energy_stream,
        ("HeatFlow", "Duty", "EnergyFlow"),
        name,
    )


def column_energy_streams_from_column_flowsheet(
    column_flowsheet: Any,
    target_tower: TargetTower,
) -> tuple[Any, Any]:
    """ColumnFlowsheet から condenser/reboiler energy stream を名前指定で読む。"""
    energy_streams = getattr(column_flowsheet, "EnergyStreams", None)
    stream_names = TOWER_COLUMN_ENERGY_STREAMS[target_tower]

    condenser = collection_item_by_name(energy_streams, stream_names["condenser"])
    reboiler = collection_item_by_name(energy_streams, stream_names["reboiler"])

    if condenser is None or reboiler is None:
        available = available_energy_stream_names(energy_streams)
        raise RuntimeError(
            "column flowsheet の energy stream 名が一致しません: "
            f"required={stream_names}, available={available}"
        )

    return condenser, reboiler


def column_energy_streams_from_main_flowsheet(
    flowsheet: Any,
    target_tower: TargetTower,
) -> tuple[Any, Any]:
    """main flowsheet から condenser/reboiler energy stream を名前指定で読む。"""
    stream_names = TOWER_COLUMN_ENERGY_STREAMS[target_tower]

    try:
        condenser = get_energy_stream(flowsheet, stream_names["condenser"])
        reboiler = get_energy_stream(flowsheet, stream_names["reboiler"])
    except Exception as exc:
        available = available_energy_stream_names(
            getattr(flowsheet, "EnergyStreams", None)
        )
        raise RuntimeError(
            "main flowsheet の energy stream 名が一致しません: "
            f"required={stream_names}, available={available}"
        ) from exc

    return condenser, reboiler


def column_energy_streams(
    refs: ColumnRefs,
    target_tower: TargetTower,
) -> tuple[Any, Any, str]:
    """main flowsheet と ColumnFlowsheet の両方から energy stream を探す。"""
    errors: list[str] = []

    try:
        condenser, reboiler = column_energy_streams_from_column_flowsheet(
            refs.column_flowsheet,
            target_tower,
        )
        return condenser, reboiler, "column_flowsheet"
    except Exception as exc:
        errors.append(f"column_flowsheet: {exc}")

    try:
        condenser, reboiler = column_energy_streams_from_main_flowsheet(
            refs.flowsheet,
            target_tower,
        )
        return condenser, reboiler, "main_flowsheet"
    except Exception as exc:
        errors.append(f"main_flowsheet: {exc}")

    raise RuntimeError("; ".join(errors))


def condenser_lmtd_k(top_temperature_c: float) -> float:
    """塔頂凝縮と冷却水 30→45 ℃の対数平均温度差を計算する。"""
    if top_temperature_c <= CONDENSER_CW_OUTLET_C:
        raise RuntimeError(
            f"T_top={top_temperature_c:.3f} C は冷却水出口 "
            f"{CONDENSER_CW_OUTLET_C:.1f} C 以下です"
        )

    delta_t_hot = top_temperature_c - CONDENSER_CW_INLET_C
    delta_t_cold = top_temperature_c - CONDENSER_CW_OUTLET_C

    if math.isclose(delta_t_hot, delta_t_cold):
        return delta_t_hot
    return (delta_t_hot - delta_t_cold) / math.log(delta_t_hot / delta_t_cold)


def column_heat_exchanger_cost_once(
    simulation_case: Any,
    target_tower: TargetTower,
) -> ColumnHeatExchangerCost:
    """塔付属の condenser/reboiler 装置費を1回読む。"""
    refs = fresh_column_refs(simulation_case, target_tower)

    temperatures = numeric_values(refs.column_flowsheet, "TemperaturesValue")
    if not temperatures:
        raise RuntimeError("TemperaturesValue が空です")

    top_temperature_c = temperatures[0]
    bottom_temperature_c = temperatures[-1]

    condenser_stream, reboiler_stream, source = column_energy_streams(refs, target_tower)
    condenser_stream_name = object_name(condenser_stream)
    reboiler_stream_name = object_name(reboiler_stream)

    log(
        f"[duty-source] source={source} "
        f"cond={condenser_stream_name} reb={reboiler_stream_name}"
    )

    condenser_duty_kw = heat_flow_kw(condenser_stream, "condenser duty")
    reboiler_duty_kw = heat_flow_kw(reboiler_stream, "reboiler duty")

    condenser_delta_t_k = condenser_lmtd_k(top_temperature_c)
    condenser_area_m2 = abs(condenser_duty_kw) * 1000.0 / (
        CONDENSER_U_W_M2_K * condenser_delta_t_k
    )

    steam_temperature_c = (
        LOW_PRESSURE_STEAM_C
        if bottom_temperature_c < REBOILER_STEAM_SWITCH_C
        else MEDIUM_PRESSURE_STEAM_C
    )
    reboiler_delta_t_k = steam_temperature_c - bottom_temperature_c
    if reboiler_delta_t_k <= 0.0:
        raise RuntimeError(
            f"reboiler ΔT が 0 以下です: steam={steam_temperature_c:.3f} C, "
            f"bottom={bottom_temperature_c:.3f} C"
        )

    reboiler_area_m2 = abs(reboiler_duty_kw) * 1000.0 / (
        REBOILER_U_W_M2_K * reboiler_delta_t_k
    )

    condenser_capital_cost_yen = HEAT_EXCHANGER_COST_FACTOR_YEN * condenser_area_m2**0.65
    reboiler_capital_cost_yen = (
        HEAT_EXCHANGER_COST_FACTOR_YEN * reboiler_area_m2**0.65 * 2.0
    )

    return ColumnHeatExchangerCost(
        condenser_stream_name=condenser_stream_name,
        reboiler_stream_name=reboiler_stream_name,
        condenser_duty_kw=condenser_duty_kw,
        reboiler_duty_kw=reboiler_duty_kw,
        top_temperature_c=top_temperature_c,
        bottom_temperature_c=bottom_temperature_c,
        condenser_area_m2=condenser_area_m2,
        reboiler_area_m2=reboiler_area_m2,
        condenser_capital_cost_yen=condenser_capital_cost_yen,
        reboiler_capital_cost_yen=reboiler_capital_cost_yen,
    )


def column_heat_exchanger_cost(
    simulation_case: Any,
    target_tower: TargetTower,
) -> ColumnHeatExchangerCost:
    """塔付属の condenser/reboiler 装置費をリトライ付きで読む。"""
    return retry(
        "column_heat_exchanger_cost",
        lambda: column_heat_exchanger_cost_once(simulation_case, target_tower),
    )


def reboiler_steam_yen_per_mj(bottom_temperature_c: float) -> float:
    """塔底温度からリボイラ用スチーム単価を返す。"""
    if bottom_temperature_c < REBOILER_STEAM_SWITCH_C:
        return LOW_PRESSURE_STEAM_YEN_PER_MJ
    return MEDIUM_PRESSURE_STEAM_YEN_PER_MJ


def column_reboiler_utility_cost_yen_per_year(
    heat_exchanger: ColumnHeatExchangerCost,
) -> float:
    """蒸留塔リボイラのスチーム用役費を計算する。"""
    return steam_heating_cost_yen_per_year(
        duty_kw=abs(heat_exchanger.reboiler_duty_kw),
        steam_yen_per_mj=reboiler_steam_yen_per_mj(
            heat_exchanger.bottom_temperature_c
        ),
        hours_per_year=HOURS_PER_YEAR,
    )


def column_condenser_utility_cost_yen_per_year(
    heat_exchanger: ColumnHeatExchangerCost,
) -> float:
    """蒸留塔コンデンサの冷却用役費を計算する。"""
    duty_kw = abs(heat_exchanger.condenser_duty_kw)

    if heat_exchanger.top_temperature_c > CONDENSER_CW_OUTLET_C:
        return cooling_water_cost_yen_per_year(
            duty_kw=duty_kw,
            cp_water_kj_kg_k=WATER_CP_KJ_KG_K,
            cooling_water_delta_t_k=CONDENSER_CW_OUTLET_C - CONDENSER_CW_INLET_C,
            cooling_water_yen_per_ton=COOLING_WATER_YEN_PER_TON,
            hours_per_year=HOURS_PER_YEAR,
        )

    return cooling_utility_cost_yen_per_year(
        duty_kw=duty_kw,
        refrigerant_yen_per_mj=PROPYLENE_REFRIGERANT_YEN_PER_MJ,
        hours_per_year=HOURS_PER_YEAR,
    )


def column_utility_cost_yen_per_year(
    heat_exchanger: ColumnHeatExchangerCost,
) -> float:
    """蒸留塔リボイラ・コンデンサの用役費を合算する。"""
    return (
        column_reboiler_utility_cost_yen_per_year(heat_exchanger)
        + column_condenser_utility_cost_yen_per_year(heat_exchanger)
    )


def column_shell_capital_cost_yen(diameter_m: float, height_m: float) -> float:
    """塔胴体の装置費を計算する。"""
    if diameter_m <= 0.0 or height_m <= 0.0:
        raise ValueError("diameter_m and height_m must be positive")
    return COLUMN_SHELL_COST_FACTOR_YEN * diameter_m**1.066 * height_m**0.82


def cooling_duty_split_kw(
    total_duty_kw: float,
    inlet_temperature_c: float,
) -> tuple[float, float]:
    """製品冷却 duty を冷却水分とプロピレン冷媒分に分ける。"""
    total = abs(total_duty_kw)
    if inlet_temperature_c <= PRODUCT_TARGET_TEMPERATURE_C or total <= 0.0:
        return 0.0, 0.0

    total_delta_t = inlet_temperature_c - PRODUCT_TARGET_TEMPERATURE_C
    cw_delta_t = max(inlet_temperature_c - COOLING_WATER_PROCESS_LIMIT_C, 0.0)
    cooling_water_duty_kw = total * cw_delta_t / total_delta_t
    propylene_duty_kw = total - cooling_water_duty_kw
    return cooling_water_duty_kw, propylene_duty_kw


def product_cooling_utility_cost_yen_per_year(
    flowsheet: Any,
    cooler_names: Sequence[str],
) -> float:
    """C-3/C-4/C-5 の製品冷却用役費を計算する。"""
    total_cost = 0.0

    for cooler_name in cooler_names:
        cooler = get_operation(flowsheet, cooler_name)
        duty_kw = required_number(
            get_quantity(cooler, "Duty", ("kW", "kJ/h")),
            f"{cooler_name} Duty",
        )
        inlet_temperature_c = required_number(
            get_quantity(cooler, "FeedTemperature", ("C", "degC")),
            f"{cooler_name} FeedTemperature",
        )
        product_temperature_c = required_number(
            get_quantity(cooler, "ProductTemperature", ("C", "degC")),
            f"{cooler_name} ProductTemperature",
        )

        if not math.isclose(
            product_temperature_c,
            PRODUCT_TARGET_TEMPERATURE_C,
            abs_tol=1.0e-6,
        ):
            raise RuntimeError(
                f"{cooler_name} ProductTemperature={product_temperature_c:.3f} C で、"
                "38 C ではありません"
            )

        cooling_water_duty_kw, propylene_duty_kw = cooling_duty_split_kw(
            duty_kw,
            inlet_temperature_c,
        )
        total_cost += cooling_water_cost_yen_per_year(
            duty_kw=cooling_water_duty_kw,
            cp_water_kj_kg_k=WATER_CP_KJ_KG_K,
            cooling_water_delta_t_k=COOLING_WATER_OUTLET_C - COOLING_WATER_INLET_C,
            cooling_water_yen_per_ton=COOLING_WATER_YEN_PER_TON,
            hours_per_year=HOURS_PER_YEAR,
        )
        total_cost += cooling_utility_cost_yen_per_year(
            duty_kw=propylene_duty_kw,
            refrigerant_yen_per_mj=PROPYLENE_REFRIGERANT_YEN_PER_MJ,
            hours_per_year=HOURS_PER_YEAR,
        )

    return total_cost


def stream_mass_heat_capacity_kj_kg_k(stream: Any, stream_name: str) -> float:
    """material stream の質量基準熱容量を読む。"""
    for attr_name in ("MassHeatCapacity", "MassCp", "MassSpecificHeat", "MassSpecHeat"):
        value = get_quantity(stream, attr_name, ("kJ/kg-C", "kJ/kg-K", "kJ/kg/degC"))
        if is_valid_number(value) and value > 0.0:
            return float(value)
    raise RuntimeError(f"{stream_name} の質量基準熱容量を取得できませんでした")


def eb_recycle_heating_cost_yen_per_year(flowsheet: Any) -> float:
    """EB recycle を 200 ℃まで加熱する概算用役費を計算する。"""
    stream = get_material_stream(flowsheet, EB_RECYCLE_STREAM_NAME)
    temperature_c = required_number(
        get_quantity(stream, "Temperature", ("C", "degC")),
        f"{EB_RECYCLE_STREAM_NAME} Temperature",
    )
    mass_flow_kg_h = required_number(
        get_quantity(stream, "MassFlow", ("kg/h",)),
        f"{EB_RECYCLE_STREAM_NAME} MassFlow",
    )
    cp_kj_kg_k = stream_mass_heat_capacity_kj_kg_k(stream, EB_RECYCLE_STREAM_NAME)
    duty_kw = (
        mass_flow_kg_h
        * cp_kj_kg_k
        * max(EB_RECYCLE_TARGET_TEMPERATURE_C - temperature_c, 0.0)
        / 3600.0
    )
    return steam_heating_cost_yen_per_year(
        duty_kw=duty_kw,
        steam_yen_per_mj=MEDIUM_PRESSURE_STEAM_YEN_PER_MJ,
        hours_per_year=HOURS_PER_YEAR,
    )


def external_utility_cost_yen_per_year(flowsheet: Any, target_tower: TargetTower) -> float:
    """対象塔に対応する外部用役費を計算する。"""
    if target_tower == "tower2":
        return eb_recycle_heating_cost_yen_per_year(flowsheet)

    return product_cooling_utility_cost_yen_per_year(
        flowsheet,
        TOWER_PRODUCT_COOLERS[target_tower],
    )


def total_utility_cost_yen_per_year(
    flowsheet: Any,
    target_tower: TargetTower,
    heat_exchanger: ColumnHeatExchangerCost,
) -> float:
    """外部用役と蒸留塔用役を合算する。"""
    return external_utility_cost_yen_per_year(
        flowsheet,
        target_tower,
    ) + column_utility_cost_yen_per_year(heat_exchanger)


def tower1_constraint_reason(
    heat_exchanger: ColumnHeatExchangerCost,
    target_tower: TargetTower,
) -> str:
    """tower1 の SM 重合防止制約違反理由を返す。"""
    if target_tower != "tower1":
        return ""
    if heat_exchanger.bottom_temperature_c <= TOWER1_MAX_BOTTOM_TEMPERATURE_C:
        return ""
    return (
        f"tower1 bottom temperature {heat_exchanger.bottom_temperature_c:.3f} C "
        f"> {TOWER1_MAX_BOTTOM_TEMPERATURE_C:.1f} C"
    )


def evaluate_feed_stage(
    simulation_case: Any,
    case_name: str,
    sweep_direction: SweepDirection,
    stage_count: int,
    feed_stage: int,
    target_tower: TargetTower,
) -> FeedStageResult:
    """指定 feed 段で solve して評価する。"""
    actual_feed_stage: int | None = None

    try:
        log_step(case_name, feed_stage, "evaluate-start", f"direction={sweep_direction}")

        actual_feed_stage = apply_feed_stage(
            simulation_case=simulation_case,
            case_name=case_name,
            target_tower=target_tower,
            feed_stage=feed_stage,
        )

        refs = fresh_column_refs(simulation_case, target_tower)
        if actual_feed_stage != feed_stage:
            raise RuntimeError(
                f"feed段が反映されていません: requested={feed_stage}, "
                f"actual={actual_feed_stage}"
            )

        log_step(case_name, feed_stage, "hydraulics-start")
        hydraulics = column_hydraulics(refs.column_flowsheet, stage_count)
        log_step(
            case_name,
            feed_stage,
            "hydraulics-done",
            f"D={hydraulics.diameter_m:.6g} H={hydraulics.height_m:.6g}",
        )

        log_step(case_name, feed_stage, "duty-read-start")
        heat_exchanger = column_heat_exchanger_cost(simulation_case, target_tower)
        log_step(
            case_name,
            feed_stage,
            "duty-read-done",
            f"cond={heat_exchanger.condenser_stream_name} "
            f"reb={heat_exchanger.reboiler_stream_name} "
            f"Qcond={heat_exchanger.condenser_duty_kw:.6g} "
            f"Qreb={heat_exchanger.reboiler_duty_kw:.6g}",
        )

        shell_capital_cost_yen = column_shell_capital_cost_yen(
            hydraulics.diameter_m,
            hydraulics.height_m,
        )
        equipment_cost_yen_per_year = (
            shell_capital_cost_yen
            + heat_exchanger.condenser_capital_cost_yen
            + heat_exchanger.reboiler_capital_cost_yen
        ) / DEPRECIATION_YEARS

        log_step(case_name, feed_stage, "utility-start")
        refs = fresh_column_refs(simulation_case, target_tower)
        utility_cost_yen_per_year = total_utility_cost_yen_per_year(
            flowsheet=refs.flowsheet,
            target_tower=target_tower,
            heat_exchanger=heat_exchanger,
        )
        objective_yen_per_year = equipment_cost_yen_per_year + utility_cost_yen_per_year

        log_step(
            case_name,
            feed_stage,
            "utility-done",
            f"equipment={cost_to_oku_yen_per_year(equipment_cost_yen_per_year):.4f} "
            f"utility={cost_to_oku_yen_per_year(utility_cost_yen_per_year):.4f} "
            f"J={cost_to_oku_yen_per_year(objective_yen_per_year):.4f} oku-yen/year",
        )

        constraint_reason = tower1_constraint_reason(heat_exchanger, target_tower)
        valid = constraint_reason == ""

        return FeedStageResult(
            case_name=case_name,
            sweep_direction=sweep_direction,
            stage_count=stage_count,
            feed_stage=feed_stage,
            actual_feed_stage=actual_feed_stage,
            valid=valid,
            invalid_reason=constraint_reason,
            equipment_cost_yen_per_year=equipment_cost_yen_per_year if valid else None,
            utility_cost_yen_per_year=utility_cost_yen_per_year if valid else None,
            objective_yen_per_year=objective_yen_per_year if valid else None,
            diameter_m=hydraulics.diameter_m,
            height_m=hydraulics.height_m,
            ld_ratio=hydraulics.ld_ratio,
            ld_warning=hydraulics.ld_ratio > LD_WARNING_LIMIT,
            bottom_temperature_c=heat_exchanger.bottom_temperature_c,
            top_temperature_c=heat_exchanger.top_temperature_c,
            condenser_duty_kw=heat_exchanger.condenser_duty_kw,
            reboiler_duty_kw=heat_exchanger.reboiler_duty_kw,
            condenser_stream_name=heat_exchanger.condenser_stream_name,
            reboiler_stream_name=heat_exchanger.reboiler_stream_name,
        )
    except Exception as exc:
        log_step(case_name, feed_stage, "evaluate-error", str(exc))
        return FeedStageResult(
            case_name=case_name,
            sweep_direction=sweep_direction,
            stage_count=stage_count,
            feed_stage=feed_stage,
            actual_feed_stage=actual_feed_stage,
            valid=False,
            invalid_reason=str(exc),
        )


def should_stop_direction(result: FeedStageResult) -> bool:
    """この結果で方向探索を打ち切るべきか判定する。"""
    if result.valid or not STOP_DIRECTION_ON_UNSTABLE_INVALID:
        return False

    reason = result.invalid_reason.lower()
    return any(keyword.lower() in reason for keyword in UNSTABLE_INVALID_KEYWORDS)


def value_text(value: float | None) -> str:
    """ログ用数値を整形する。"""
    if value is None or not math.isfinite(value):
        return "nan"
    return f"{value:.3f}"


def log_feed_result(result: FeedStageResult) -> None:
    """feed 段ごとの詳細ログを表示する。"""
    if not DETAILED_FEED_LOG:
        return

    status = "valid" if result.valid else f"invalid: {result.invalid_reason}"
    ld_text = "nan" if result.ld_ratio is None else f"{result.ld_ratio:.3f}"
    warning = " ld_warning" if result.ld_warning else ""
    actual_feed = "nan" if result.actual_feed_stage is None else str(result.actual_feed_stage)
    condenser_name = result.condenser_stream_name or "nan"
    reboiler_name = result.reboiler_stream_name or "nan"

    log(
        f"[feed] file={result.case_name} direction={result.sweep_direction} "
        f"N={result.stage_count} feed={result.feed_stage} actual_feed={actual_feed} "
        f"D={value_text(result.diameter_m)} H={value_text(result.height_m)} "
        f"L/D={ld_text}{warning} "
        f"Ttop={value_text(result.top_temperature_c)} "
        f"Tbottom={value_text(result.bottom_temperature_c)} "
        f"Qcond={value_text(result.condenser_duty_kw)} "
        f"Qreb={value_text(result.reboiler_duty_kw)} "
        f"cond={condenser_name} reb={reboiler_name} "
        f"equipment={cost_to_oku_yen_per_year(result.equipment_cost_yen_per_year):.4f} "
        f"utility={cost_to_oku_yen_per_year(result.utility_cost_yen_per_year):.4f} "
        f"J={cost_to_oku_yen_per_year(result.objective_yen_per_year):.4f} "
        f"{status}"
    )


def best_valid_feed_result(results: Sequence[FeedStageResult]) -> FeedStageResult | None:
    """有効な feed 段結果のうち評価関数が最小のものを返す。"""
    valid_results = [
        result
        for result in results
        if result.valid and result.objective_yen_per_year is not None
    ]
    if not valid_results:
        return None
    return min(valid_results, key=lambda result: result.objective_yen_per_year or math.inf)


def inspect_case_basis(
    simulation_case: Any,
    target_tower: TargetTower,
) -> tuple[int, int | None]:
    """case の段数と base feed 段を読む。"""
    refs = fresh_column_refs(simulation_case, target_tower)
    stage_count = stage_count_from_column(refs.column_flowsheet)
    base_feed_stage = current_feed_stage(refs.column_flowsheet)
    return stage_count, base_feed_stage


def run_feed_direction(
    simulation_case: Any,
    case_name: str,
    target_tower: TargetTower,
    sweep_direction: SweepDirection,
    stage_count: int,
    candidates: Sequence[int],
) -> list[FeedStageResult]:
    """開いている case で一方向の feed 段探索を行う。"""
    results: list[FeedStageResult] = []

    for feed_index, feed_stage in enumerate(candidates, start=1):
        log(
            f"[feed-start] file={case_name} direction={sweep_direction} "
            f"N={stage_count} {feed_index}/{len(candidates)} "
            f"requested_feed={feed_stage}"
        )

        result = evaluate_feed_stage(
            simulation_case=simulation_case,
            case_name=case_name,
            sweep_direction=sweep_direction,
            stage_count=stage_count,
            feed_stage=feed_stage,
            target_tower=target_tower,
        )
        results.append(result)
        log_feed_result(result)

        if should_stop_direction(result):
            log(
                f"[direction-stop] file={case_name} direction={sweep_direction} "
                f"feed={feed_stage} reason={result.invalid_reason}"
            )
            break

    return results


def directional_feed_stage_candidates(
    stage_count: int,
    base_stage: int | None,
) -> tuple[list[int], list[int]]:
    """下方向探索用と上方向探索用の feed 段候補を返す。"""
    if base_stage is None or base_stage < 1 or base_stage > stage_count:
        return list(range(1, stage_count + 1)), []

    base_lower = [base_stage, *range(base_stage - 1, 0, -1)]
    upper = list(range(base_stage + 1, stage_count + 1))
    return base_lower, upper


def sweep_case(
    case_path: Path,
    target_tower: TargetTower,
    case_index: int,
    total_cases: int,
) -> CaseSweepResult:
    """HYSYS case 1 ファイルについて feed 段を方向別に sweep する。"""
    try:
        all_feed_results: list[FeedStageResult] = []

        with hysys_case(case_path.resolve(), visible=VISIBLE_HYSYS) as (
            _,
            simulation_case,
            _,
        ):
            stage_count, base_feed_stage = inspect_case_basis(
                simulation_case,
                target_tower,
            )
            log(
                f"[case] file={case_path.name} "
                f"base_feed_stage={base_feed_stage}"
            )

            base_lower_candidates, upper_candidates = directional_feed_stage_candidates(
                stage_count,
                base_feed_stage,
            )

            log(
                f"[direction-start] file={case_path.name} "
                f"direction=base_lower count={len(base_lower_candidates)}"
            )
            all_feed_results.extend(
                run_feed_direction(
                    simulation_case=simulation_case,
                    case_name=case_path.name,
                    target_tower=target_tower,
                    sweep_direction="base_lower",
                    stage_count=stage_count,
                    candidates=base_lower_candidates,
                )
            )

        if upper_candidates:
            log(
                f"[case-reopen] file={case_path.name} "
                "reason=upper_direction_start"
            )
            with hysys_case(case_path.resolve(), visible=VISIBLE_HYSYS) as (
                _,
                simulation_case,
                _,
            ):
                reopened_stage_count, reopened_base_feed_stage = inspect_case_basis(
                    simulation_case,
                    target_tower,
                )
                log(
                    f"[case] file={case_path.name} reopened_base_feed_stage="
                    f"{reopened_base_feed_stage}"
                )

                if reopened_stage_count != stage_count:
                    raise RuntimeError(
                        f"reopened stage_count changed: "
                        f"before={stage_count}, after={reopened_stage_count}"
                    )

                log(
                    f"[direction-start] file={case_path.name} "
                    f"direction=upper count={len(upper_candidates)}"
                )
                all_feed_results.extend(
                    run_feed_direction(
                        simulation_case=simulation_case,
                        case_name=case_path.name,
                        target_tower=target_tower,
                        sweep_direction="upper",
                        stage_count=stage_count,
                        candidates=upper_candidates,
                    )
                )

        best = best_valid_feed_result(all_feed_results)
        if best is None:
            invalid_reason = "; ".join(
                sorted(
                    {
                        result.invalid_reason
                        for result in all_feed_results
                        if result.invalid_reason
                    }
                )
            )
            log_summary(
                f"[case] {case_index}/{total_cases} file={case_path.name} "
                f"N={stage_count} invalid: {invalid_reason}"
            )
            return CaseSweepResult(
                case_name=case_path.name,
                case_path=str(case_path.resolve()),
                stage_count=stage_count,
                valid=False,
                invalid_reason=invalid_reason,
            )

        ld_warning = " ld_warning" if best.ld_warning else ""
        log_summary(
            f"[case] {case_index}/{total_cases} file={case_path.name} "
            f"N={stage_count} best_feed={best.feed_stage} "
            f"L/D={best.ld_ratio:.3f}{ld_warning} "
            f"equipment={cost_to_oku_yen_per_year(best.equipment_cost_yen_per_year):.4f} "
            f"utility={cost_to_oku_yen_per_year(best.utility_cost_yen_per_year):.4f} "
            f"J={cost_to_oku_yen_per_year(best.objective_yen_per_year):.4f} "
            "oku-yen/year valid"
        )

        return CaseSweepResult(
            case_name=case_path.name,
            case_path=str(case_path.resolve()),
            stage_count=stage_count,
            valid=True,
            best_feed_stage=best.feed_stage,
            equipment_cost_yen_per_year=best.equipment_cost_yen_per_year,
            utility_cost_yen_per_year=best.utility_cost_yen_per_year,
            objective_yen_per_year=best.objective_yen_per_year,
            diameter_m=best.diameter_m,
            height_m=best.height_m,
            ld_ratio=best.ld_ratio,
            ld_warning=best.ld_warning,
        )
    except Exception as exc:
        log_summary(
            f"[case] {case_index}/{total_cases} file={case_path.name} "
            f"invalid: {exc}"
        )
        return CaseSweepResult(
            case_name=case_path.name,
            case_path=str(case_path.resolve()),
            stage_count=None,
            valid=False,
            invalid_reason=str(exc),
        )


def configure_axes() -> None:
    """グラフの目盛と枠線を設定する。"""
    axes = plt.gca()
    axes.grid(False)
    axes.tick_params(direction="in", top=True, right=True, bottom=True, left=True)


def write_figure(target_tower: TargetTower, results: Sequence[CaseSweepResult]) -> Path:
    """塔ごとのコスト summary 図を保存する。"""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    valid_results = [
        result
        for result in results
        if result.valid
        and result.stage_count is not None
        and result.objective_yen_per_year is not None
    ]
    figure_path = MEDIA_DIR / f"{target_tower}_{GRID_LEVEL}_cost_summary.png"

    plt.figure()
    configure_axes()

    if valid_results:
        sorted_results = sorted(valid_results, key=lambda result: result.stage_count or 0)
        stages = [result.stage_count or 0 for result in sorted_results]

        plt.plot(
            stages,
            [
                cost_to_oku_yen_per_year(result.equipment_cost_yen_per_year)
                for result in sorted_results
            ],
            marker="o",
            label="装置コスト",
        )
        plt.plot(
            stages,
            [
                cost_to_oku_yen_per_year(result.utility_cost_yen_per_year)
                for result in sorted_results
            ],
            marker="o",
            label="用役コスト",
        )
        plt.plot(
            stages,
            [
                cost_to_oku_yen_per_year(result.objective_yen_per_year)
                for result in sorted_results
            ],
            marker="o",
            label="評価関数",
        )

    plt.xlabel("段数 [-]")
    plt.ylabel("コスト [億円/year]")
    plt.ylim(bottom=0)
    plt.legend()
    plt.tight_layout()
    plt.savefig(figure_path, dpi=200)
    plt.close()
    return figure_path


def target_case_paths(target_tower: TargetTower, grid_level: GridLevel) -> tuple[Path, ...]:
    """対象ディレクトリ内の HYSYS case 一覧を返す。"""
    case_dir = HYSYS_DIR / target_tower / grid_level
    if not case_dir.exists():
        raise FileNotFoundError(case_dir)

    case_paths = tuple(sorted(case_dir.glob("*.hsc")))
    if not case_paths:
        raise FileNotFoundError(f"{case_dir} に .hsc がありません")

    return case_paths


def print_summary(
    target_tower: TargetTower,
    results: Sequence[CaseSweepResult],
    figure_path: Path,
) -> None:
    """最終 summary を表示する。"""
    candidates = [
        result
        for result in results
        if result.valid and result.objective_yen_per_year is not None
    ]
    if not candidates:
        log_summary(f"[done] tower={target_tower} no valid case figure={figure_path}")
        return

    log_summary(f"[summary] tower={target_tower} valid_cases={len(candidates)}")
    for result in sorted(candidates, key=lambda item: item.stage_count or 0):
        ld_warning = " ld_warning" if result.ld_warning else ""
        log_summary(
            f"[summary-case] tower={target_tower} "
            f"file={result.case_name} "
            f"N={result.stage_count} "
            f"best_feed={result.best_feed_stage} "
            f"D={value_text(result.diameter_m)} "
            f"H={value_text(result.height_m)} "
            f"L/D={value_text(result.ld_ratio)}{ld_warning} "
            f"equipment={cost_to_oku_yen_per_year(result.equipment_cost_yen_per_year):.4f} "
            f"utility={cost_to_oku_yen_per_year(result.utility_cost_yen_per_year):.4f} "
            f"J={cost_to_oku_yen_per_year(result.objective_yen_per_year):.4f} "
            "oku-yen/year"
        )

    best = min(candidates, key=lambda result: result.objective_yen_per_year or math.inf)
    ld_warning = " ld_warning" if best.ld_warning else ""
    log_summary(
        f"[done] tower={target_tower} "
        f"file={best.case_name} "
        f"best_N={best.stage_count} "
        f"best_feed={best.best_feed_stage} "
        f"D={value_text(best.diameter_m)} "
        f"H={value_text(best.height_m)} "
        f"L/D={value_text(best.ld_ratio)}{ld_warning} "
        f"equipment={cost_to_oku_yen_per_year(best.equipment_cost_yen_per_year):.4f} "
        f"utility={cost_to_oku_yen_per_year(best.utility_cost_yen_per_year):.4f} "
        f"J={cost_to_oku_yen_per_year(best.objective_yen_per_year):.4f} "
        f"oku-yen/year figure={figure_path}"
    )


def main() -> None:
    """蒸留塔部分最適化 sweep を実行する。"""
    case_paths = target_case_paths(TARGET_TOWER, GRID_LEVEL)
    log_summary("")
    log_summary(
        f"[run] started_at={datetime.now().isoformat(timespec='seconds')} "
        f"log_path={LOG_PATH}"
    )
    log_summary(
        f"[start] tower={TARGET_TOWER} grid={GRID_LEVEL} "
        f"cases={len(case_paths)} visible_hysys={VISIBLE_HYSYS} "
        f"detailed_feed_log={DETAILED_FEED_LOG}"
    )
    log_summary(f"[start] hysys_dir={HYSYS_DIR / TARGET_TOWER / GRID_LEVEL}")

    results = [
        sweep_case(case_path, TARGET_TOWER, index, len(case_paths))
        for index, case_path in enumerate(case_paths, start=1)
    ]

    figure_path = write_figure(TARGET_TOWER, results)
    print_summary(TARGET_TOWER, results, figure_path)


if __name__ == "__main__":
    main()
