"""CLI entry points for process_sim."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from process_sim.reactor import DictValueAccess, HysysTagSet, ReactorService


def build_default_tags() -> HysysTagSet:
    return HysysTagSet(
        eb_feed_kmol_h="RCTR_EB_IN",
        steam_feed_kmol_h="RCTR_H2O_IN",
        pressure_kpa="RCTR_P_IN",
        temperature_c="RCTR_T_IN",
        eb_out_kmol_h="RCTR_EB_OUT",
        steam_out_kmol_h="RCTR_H2O_OUT",
        styrene_out_kmol_h="RCTR_STY_OUT",
        hydrogen_out_kmol_h="RCTR_H2_OUT",
        benzene_out_kmol_h="RCTR_BZ_OUT",
        toluene_out_kmol_h="RCTR_TOL_OUT",
        co2_out_kmol_h="RCTR_CO2_OUT",
        conversion_out="RCTR_X_EB",
    )


def build_default_values(tags: HysysTagSet) -> dict[str, float]:
    return {
        tags.eb_feed_kmol_h: 700.0,
        tags.steam_feed_kmol_h: 3500.0,
        tags.pressure_kpa: 152.0,
        tags.temperature_c: 600.0,
        tags.eb_out_kmol_h: 0.0,
        tags.steam_out_kmol_h: 0.0,
        tags.styrene_out_kmol_h: 0.0,
        tags.hydrogen_out_kmol_h: 0.0,
        tags.benzene_out_kmol_h: 0.0,
        tags.toluene_out_kmol_h: 0.0,
        tags.co2_out_kmol_h: 0.0,
        tags.conversion_out: 0.0,
    }


def apply_input_overrides(values: dict[str, float], input_json: Path | None) -> dict[str, float]:
    if input_json is None:
        return values

    loaded = json.loads(input_json.read_text(encoding="utf-8"))
    for key, val in loaded.items():
        values[key] = float(val)
    return values


def parse_run_reactor_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-json",
        type=Path,
        default=None,
        help="入力値を上書きする JSON ファイルパス",
    )
    return parser.parse_args()


def run_reactor_case_main() -> None:
    args = parse_run_reactor_args()

    tags = build_default_tags()
    values = build_default_values(tags)
    values = apply_input_overrides(values, args.input_json)

    service = ReactorService(access=DictValueAccess(values=values), tags=tags)
    service.run_once()
    print(json.dumps(values, ensure_ascii=False, indent=2))
