#!/usr/bin/env python3
"""Create an isolated 80 mm V18 staging context without touching live runtime data."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from kma_forecast_v18 import KST, atomic_write_json, latlon_to_grid, normalize_next_day_forecast
from prepare_guidance_context_v18 import build_guidance_context, read_json, resolve


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "kma_trigger_v18.json"
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "kma_vilage_fcst_80mm.json"
DEFAULT_OUTPUT = ROOT / "data" / "staging" / "guidance_context_v18_80mm.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    config_path = args.config.resolve()
    config = read_json(config_path)
    root = config_path.parents[1]
    fixture = read_json(args.fixture.resolve())
    base = datetime(2026, 8, 25, 5, 0, tzinfo=KST)
    now = datetime(2026, 8, 25, 6, 0, tzinfo=KST)
    field = read_json(resolve(root, config["inputs"]["field"]))
    longitude, latitude = field["derived_metrics"]["centre_wgs84"]
    nx, ny = latlon_to_grid(latitude, longitude)
    forecast = normalize_next_day_forecast(
        fixture,
        base,
        nx,
        ny,
        now,
        source_mode="fixture",
        required_hour_count=config["kma"]["required_hour_count"],
    )
    context = build_guidance_context(
        config,
        field,
        read_json(resolve(root, config["inputs"]["inundation"])),
        forecast,
        read_json(resolve(root, config["inputs"]["hydrology"])),
        read_json(resolve(root, config["inputs"]["guidance"])),
        read_json(resolve(root, config["inputs"]["shelter_route"])),
        {"schema_version": "1.0", "events": []},
        now,
    )
    if context["status"] != "ready" or not context["trigger"]["should_generate_video"]:
        raise RuntimeError("The staging fixture did not produce a ready V18 context")
    if context["forecast"]["source"]["mode"] != "fixture":
        raise RuntimeError("A staging context must retain source_mode=fixture")
    output = args.output.resolve()
    atomic_write_json(output, context)
    print(json.dumps({
        "status": "ready",
        "context_id": context["context_id"],
        "source_mode": "fixture",
        "rain_24h_mm": context["trigger"]["rain_condition"]["value_mm"],
        "field_affected_percent": context["inundation"]["field_affected_percent"],
        "output": str(output),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
