#!/usr/bin/env python3
"""Fetch KMA 05 KST forecast, build V18 context, and optionally record a trigger."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path

from kma_forecast_v18 import (
    KST,
    KmaForecastClient,
    atomic_write_json,
    latlon_to_grid,
    load_env_value,
    normalize_next_day_forecast,
    select_morning_base,
)
from prepare_guidance_context_v18 import (
    build_guidance_context,
    load_inputs,
    parse_datetime,
    read_json,
    resolve,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "kma_trigger_v18.json"


def parse_base(base_date, base_time):
    value = datetime.strptime(f"{base_date}{base_time}", "%Y%m%d%H%M")
    return value.replace(tzinfo=KST)


def record_trigger(history_path, context, now):
    if not context["trigger"]["should_generate_video"]:
        raise RuntimeError("Cannot record a trigger when should_generate_video is false")
    history = read_json(history_path, default={"schema_version": "1.0", "events": []})
    raw_id = f"{context['context_id']}:{now.isoformat()}"
    event = {
        "event_id": hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:20],
        "field_id": context["field"]["field_id"],
        "target_date": context["trigger"]["target_date"],
        "dispatched_at": now.isoformat(),
        "status": "triggered",
        "context_id": context["context_id"],
    }
    history.setdefault("schema_version", "1.0")
    history.setdefault("events", []).append(event)
    atomic_write_json(history_path, history)
    return event


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--fixture", type=Path, help="Official-shape KMA JSON fixture; skips network")
    parser.add_argument("--base-date", help="YYYYMMDD; defaults to the latest available 05 KST release")
    parser.add_argument("--base-time", help="HHMM; defaults to configured 0500")
    parser.add_argument("--now", help="ISO-8601 KST time for deterministic checks")
    parser.add_argument(
        "--record-trigger",
        action="store_true",
        help="Start the 48-hour cooldown. Use only after the downstream job accepted the trigger.",
    )
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = read_json(config_path)
    root = config_path.parents[1]
    now = parse_datetime(args.now) if args.now else datetime.now(KST)
    base_time = args.base_time or config["kma"]["base_time"]
    base = (
        parse_base(args.base_date, base_time)
        if args.base_date
        else select_morning_base(now, base_time, config["kma"]["availability_delay_minutes"])
    )
    field = read_json(resolve(root, config["inputs"]["field"]))
    longitude, latitude = field["derived_metrics"]["centre_wgs84"]
    nx, ny = latlon_to_grid(latitude, longitude)
    try:
        if args.fixture:
            document = read_json(args.fixture)
            source_mode = "fixture"
        else:
            service_key = load_env_value(config["kma"]["service_key_env"])
            client = KmaForecastClient(config["kma"]["api_url"], service_key)
            document = client.fetch(base, nx, ny)
            source_mode = "live"
        forecast = normalize_next_day_forecast(
            document,
            base,
            nx,
            ny,
            now,
            source_mode=source_mode,
            required_hour_count=config["kma"]["required_hour_count"],
        )
    except (RuntimeError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "status": "unavailable",
            "should_generate_video": False,
            "reason_codes": ["KMA_FORECAST_FETCH_FAILED"],
            "detail": str(exc),
            "grid": {"nx": nx, "ny": ny},
        }, ensure_ascii=False, indent=2))
        return 2
    forecast_path = resolve(root, config["outputs"]["forecast"])
    atomic_write_json(forecast_path, forecast)
    loaded = load_inputs(config_path, forecast_path)
    context = build_guidance_context(
        config,
        loaded["field"],
        loaded["inundation"],
        forecast,
        loaded["hydrology"],
        loaded["guidance"],
        loaded["shelter_route"],
        loaded["history"],
        now,
    )
    context_path = resolve(root, config["outputs"]["context"])
    atomic_write_json(context_path, context)
    recorded = None
    if args.record_trigger:
        recorded = record_trigger(resolve(root, config["outputs"]["dispatch_history"]), context, now)
    summary = {
        "status": context["status"],
        "source_mode": source_mode,
        "base_datetime": forecast["base_datetime"],
        "target_date": forecast["target_date"],
        "grid": forecast["grid"],
        "coverage": forecast["coverage"],
        "rain_24h": forecast["rain_24h"],
        "field_affected_percent": context["inundation"]["field_affected_percent"],
        "should_generate_video": context["trigger"]["should_generate_video"],
        "reason_codes": context["trigger"]["reason_codes"],
        "forecast_path": str(forecast_path),
        "context_path": str(context_path),
        "recorded_event": recorded,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 2 if context["status"] == "unavailable" else 0


if __name__ == "__main__":
    raise SystemExit(main())
