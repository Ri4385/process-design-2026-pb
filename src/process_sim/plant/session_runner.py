"""HYSYS session を再利用する plant runner。"""

from __future__ import annotations

from dataclasses import asdict
import logging
from pathlib import Path
from types import TracebackType
import time
from typing import TYPE_CHECKING, Any

from process_sim.cli import ReactorModelName
from process_sim.plant.const import DEFAULT_HYSYS_CASE_PATH
from process_sim.plant.models import PlantRunRecord
from process_sim.plant.summary import (
    format_pfr_reactor_report,
    format_plant_run_summary,
    format_radial_reactor_report,
    format_reactor_calculation_summary,
    format_recycle_product_component_summary,
)
from process_sim.reactor.cases.styrene_radial_default import DEFAULT_STYRENE_RADIAL_REACTOR_CASE, RadialReactorCase
from process_sim.reactor.cases.styrene_default import DEFAULT_STYRENE_REACTOR_CASE, ReactorCase
from process_sim.reactor.types.staged_adiabatic_pfr import StagedAdiabaticPfrModel
from process_sim.reactor.types.staged_adiabatic_radial import StagedAdiabaticRadialFlowModel
from process_sim.separator.equipment import ProcessEquipment
from process_sim.separator.equipment_reader.process_equipment import read_process_equipment
from process_sim.separator.hysys_io import HysysSeparationSession, apply_hysys_control_plan

if TYPE_CHECKING:
    from process_sim.plant.hysys_controls import HysysControlPlan


logger = logging.getLogger(__name__)


class OpenHysysPlantRunner:
    """HYSYS case を開いたまま plant run を繰り返す callable runner。"""

    def __init__(
        self,
        case_path: Path = DEFAULT_HYSYS_CASE_PATH,
        reactor_model: ReactorModelName = "radial",
        log_reactor_detail: bool = False,
    ) -> None:
        self.case_path: Path = case_path.resolve()
        self.reactor_model: ReactorModelName = reactor_model
        self.log_reactor_detail: bool = log_reactor_detail
        self._separator_session: HysysSeparationSession | None = None
        self.last_reactor_result: Any | None = None

    def __enter__(self) -> OpenHysysPlantRunner:
        """HYSYS case を非表示で開く。"""
        self._separator_session = HysysSeparationSession(case_path=self.case_path, visible=False)
        self._separator_session.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """HYSYS case を閉じる。"""
        if self._separator_session is None:
            return None
        try:
            return self._separator_session.__exit__(exc_type, exc, traceback)
        finally:
            self._separator_session = None

    def __call__(self, reactor_case: ReactorCase | RadialReactorCase) -> PlantRunRecord:
        """開いている HYSYS session を使って plant run を1回実行する。"""
        if self._separator_session is None:
            raise RuntimeError("OpenHysysPlantRunner is not open")

        selected_model = selected_reactor_model(reactor_case=reactor_case, fallback=self.reactor_model)
        plant_started_at = time.perf_counter()
        logger.info("plant run started")
        logger.info("HYSYS case path: %s", self.case_path)
        logger.info("HYSYS visible: False")
        logger.info("reactor model: %s", selected_model)

        reactor_started_at = time.perf_counter()
        logger.info("reactor run started")
        reactor_result = run_reactor_case(reactor_case=reactor_case, reactor_model=selected_model)
        self.last_reactor_result = reactor_result
        logger.info("reactor run finished in %.2f s", time.perf_counter() - reactor_started_at)
        log_reactor_summary(
            reactor_case=reactor_case,
            reactor_model=selected_model,
            reactor_result=reactor_result,
            log_reactor_detail=self.log_reactor_detail,
        )

        separator_started_at = time.perf_counter()
        logger.info("separator run started")
        streams, hysys_metadata = self._separator_session.run(
            reactor_stream=reactor_result.outlet.stream,
            temperature_c=reactor_result.outlet.temperature_c,
            pressure_kpa=reactor_result.outlet.pressure_kpa,
        )
        logger.info("separator run finished in %.2f s", time.perf_counter() - separator_started_at)
        metadata: dict[str, Any] = {
            **hysys_metadata,
            "reactor_case": asdict(reactor_case),
            "reactor_model": selected_model,
            "reactor_feed": reactor_case.feed.to_component_flows_kmol_h(),
            "reactor_eb_conversion": reactor_result.eb_conversion,
            "reactor_styrene_selectivity": reactor_result.styrene_selectivity,
        }
        record = PlantRunRecord(
            case_path=self.case_path,
            reactor_outlet_temperature_c=reactor_result.outlet.temperature_c,
            reactor_outlet_pressure_kpa=reactor_result.outlet.pressure_kpa,
            streams=streams,
            metadata=metadata,
        )
        logger.info("\n%s", format_recycle_product_component_summary(record))
        logger.info("\n%s", format_plant_run_summary(record))
        logger.info("plant run finished in %.2f s", time.perf_counter() - plant_started_at)
        return record

    def read_process_equipment(self) -> ProcessEquipment:
        """開いている HYSYS case から分離系機器を読み取る。"""
        if self._separator_session is None:
            raise RuntimeError("OpenHysysPlantRunner is not open")
        return read_process_equipment(self._separator_session.simulation_case)

    def apply_post_convergence_controls(self, plan: "HysysControlPlan") -> None:
        """収束後の HYSYS 操作条件を書き込み、readback で確認する。"""
        if self._separator_session is None:
            raise RuntimeError("OpenHysysPlantRunner is not open")
        from process_sim.plant.hysys_controls import format_hysys_control_readback

        readback = apply_hysys_control_plan(
            simulation_case=self._separator_session.simulation_case,
            plan=plan,
        )
        logger.info("\n%s", format_hysys_control_readback(plan=plan, readback=readback))


def selected_reactor_model(
    reactor_case: ReactorCase | RadialReactorCase | None,
    fallback: ReactorModelName,
) -> ReactorModelName:
    """反応器 case から実際に使うモデル名を決める。"""
    if reactor_case is None:
        return fallback
    if isinstance(reactor_case, RadialReactorCase):
        return "radial"
    return "pfr"


def run_reactor_case(
    reactor_case: ReactorCase | RadialReactorCase,
    reactor_model: ReactorModelName,
) -> Any:
    """指定した反応器 case を計算する。"""
    if reactor_model == "radial":
        if not isinstance(reactor_case, RadialReactorCase):
            raise TypeError("radial reactor model requires RadialReactorCase")
        return StagedAdiabaticRadialFlowModel().run(feed=reactor_case.feed, conditions=reactor_case.conditions)

    if not isinstance(reactor_case, ReactorCase):
        raise TypeError("pfr reactor model requires ReactorCase")
    return StagedAdiabaticPfrModel().run(feed=reactor_case.feed, conditions=reactor_case.conditions)


def log_reactor_summary(
    reactor_case: ReactorCase | RadialReactorCase,
    reactor_model: ReactorModelName,
    reactor_result: Any,
    log_reactor_detail: bool,
) -> None:
    """反応器計算結果をログへ出す。"""
    if log_reactor_detail and reactor_model == "radial":
        if not isinstance(reactor_case, RadialReactorCase):
            raise TypeError("radial reactor model requires RadialReactorCase")
        logger.info("\n%s", format_radial_reactor_report(feed=reactor_case.feed, result=reactor_result))
    elif log_reactor_detail and reactor_model == "pfr":
        if not isinstance(reactor_case, ReactorCase):
            raise TypeError("pfr reactor model requires ReactorCase")
        logger.info("\n%s", format_pfr_reactor_report(feed=reactor_case.feed, result=reactor_result))
    else:
        logger.info("\n%s", format_reactor_calculation_summary(feed=reactor_case.feed, result=reactor_result))


def default_reactor_case(reactor_model: ReactorModelName) -> ReactorCase | RadialReactorCase:
    """反応器モデル名に対応する既定 case を返す。"""
    if reactor_model == "radial":
        return DEFAULT_STYRENE_RADIAL_REACTOR_CASE
    return DEFAULT_STYRENE_REACTOR_CASE
