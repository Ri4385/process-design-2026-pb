"""HYSYS COM 接続を最小限で確認する。"""

from __future__ import annotations

from pathlib import Path
import json
from typing import Any

import pythoncom
import pywintypes
import win32com.client


REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = REPO_ROOT / "data" / "hysys" / "decanter.hsc"
PROG_IDS: tuple[str, ...] = (
    "HYSYS.Application.NewInstance.V14.0",
    "HYSYS.Application.V14.0",
    "HYSYS.Application.NewInstance",
    "HYSYS.Application",
)


def connect_hysys() -> tuple[Any, str]:
    """HYSYS COM アプリケーションへ接続する。"""
    errors: list[str] = []
    for prog_id in PROG_IDS:
        try:
            app = win32com.client.Dispatch(prog_id)
            return app, prog_id
        except pywintypes.com_error as exc:
            errors.append(f"{prog_id}: {exc}")
    joined = "\n".join(errors)
    raise RuntimeError(f"HYSYS に接続できませんでした。\n{joined}")


def open_case(app: Any, case_path: Path) -> Any:
    """HYSYS ケースを開く。"""
    simulation_cases = getattr(app, "SimulationCases", None)
    if simulation_cases is None:
        raise RuntimeError("SimulationCases を取得できませんでした。")

    errors: list[str] = []
    for candidate in (
        lambda: simulation_cases.Open(str(case_path)),
        lambda: simulation_cases.Open(case_path),
        lambda: simulation_cases.Open(str(case_path), False),
    ):
        try:
            return candidate()
        except Exception as exc:
            errors.append(str(exc))

    joined = "\n".join(errors)
    raise RuntimeError(f"ケースを開けませんでした: {case_path}\n{joined}")


def main() -> None:
    """接続確認を実行して結果を JSON 出力する。"""
    pythoncom.CoInitialize()
    app: Any | None = None
    simulation_case: Any | None = None
    try:
        app, prog_id = connect_hysys()
        try:
            app.Visible = True
        except Exception:
            pass

        simulation_case = open_case(app=app, case_path=CASE_PATH.resolve())
        flowsheet = getattr(simulation_case, "Flowsheet", None)
        stream_count = None
        if flowsheet is not None:
            material_streams = getattr(flowsheet, "MaterialStreams", None)
            if material_streams is not None:
                try:
                    stream_count = int(material_streams.Count)
                except Exception:
                    stream_count = None

        result = {
            "connected": True,
            "prog_id": prog_id,
            "case_opened": True,
            "case_path": str(CASE_PATH.resolve()),
            "material_stream_count": stream_count,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        if simulation_case is not None:
            close_method = getattr(simulation_case, "Close", None)
            if callable(close_method):
                try:
                    close_method(False)
                except Exception:
                    try:
                        close_method()
                    except Exception:
                        pass
        if app is not None:
            quit_method = getattr(app, "Quit", None)
            if callable(quit_method):
                try:
                    quit_method()
                except Exception:
                    pass
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
