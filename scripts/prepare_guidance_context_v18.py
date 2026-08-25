#!/usr/bin/env python3
"""Build the auditable V18 guidance context and day-before trigger decision."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from kma_forecast_v18 import atomic_write_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "kma_trigger_v18.json"
KST = ZoneInfo("Asia/Seoul")


def read_json(path: Path, default=None):
    if not path.is_file():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def parse_datetime(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return result if result.tzinfo else result.replace(tzinfo=KST)


def file_sha256(path: Path):
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def latest_dispatch(history, field_id, now):
    candidates = []
    for event in history.get("events", []):
        if event.get("field_id") != field_id or event.get("status") not in {"triggered", "video_generated", "delivered"}:
            continue
        dispatched_at = parse_datetime(event.get("dispatched_at"))
        if dispatched_at and dispatched_at <= now:
            candidates.append((dispatched_at, event))
    return max(candidates, key=lambda item: item[0]) if candidates else (None, None)


def hydrology_context(state, now, freshness_minutes=30):
    decision = (state or {}).get("decision_station") or {}
    observed = parse_datetime(decision.get("observed_at"))
    age_minutes = (now - observed.astimezone(KST)).total_seconds() / 60.0 if observed else None
    fresh = bool(
        (state or {}).get("status") == "ok"
        and observed
        and age_minutes is not None
        and -5 <= age_minutes <= freshness_minutes
        and decision.get("water_level_m") is not None
    )
    return {
        "status": "ok" if fresh else "unavailable",
        "used_for_trigger": False,
        "role": "current_state_confirmation_only",
        "station": decision.get("name"),
        "observed_at": decision.get("observed_at"),
        "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
        "water_level_m": decision.get("water_level_m"),
        "risk": (state or {}).get("risk", {"code": "unknown", "label": "판정불가"}) if fresh else {"code": "unknown", "label": "판정불가"},
        "selected_visual_stage": (state or {}).get("selected_visual_stage") if fresh else None,
        "reason": None if fresh else "V17 observation is missing or older than the freshness limit.",
    }


def build_guidance_context(
    config,
    field,
    inundation,
    forecast,
    hydrology_state,
    guidance_policy,
    shelter_route,
    history,
    now,
):
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    now = now.astimezone(KST)
    trigger_config = config["trigger"]
    base_datetime = parse_datetime(forecast.get("base_datetime"))
    base_age_hours = (now - base_datetime.astimezone(KST)).total_seconds() / 3600.0 if base_datetime else None
    forecast_complete = bool(
        forecast.get("status") == "complete"
        and forecast.get("coverage", {}).get("complete_24h")
    )
    forecast_fresh = bool(
        base_age_hours is not None
        and -1 <= base_age_hours <= float(config["kma"]["max_base_age_hours"])
    )
    forecast_available = forecast_complete and forecast_fresh
    rain_total = forecast.get("rain_24h", {}).get(trigger_config["rain_total_field"])
    rain_passed = bool(
        forecast_available
        and rain_total is not None
        and float(rain_total) >= float(trigger_config["rain_threshold_mm"])
    )

    field_info = inundation["field"]
    affected_percent = float(field_info.get("maximum_geometry_affected_percent", 0.0))
    field_passed = affected_percent >= float(trigger_config["field_overlap_threshold_percent"])
    field_id = field["field_id"]
    last_at, last_event = latest_dispatch(history, field_id, now)
    cooldown_until = last_at + timedelta(hours=float(trigger_config["cooldown_hours"])) if last_at else None
    cooldown_active = bool(cooldown_until and now < cooldown_until)
    should_generate = bool(forecast_available and rain_passed and field_passed and not cooldown_active)

    reasons = []
    if not forecast_complete:
        reasons.append("FORECAST_INCOMPLETE")
    elif not forecast_fresh:
        reasons.append("FORECAST_STALE")
    if forecast_available and not rain_passed:
        reasons.append("RAIN_BELOW_THRESHOLD")
    if not field_passed:
        reasons.append("FIELD_HAZARD_OVERLAP_BELOW_THRESHOLD")
    if cooldown_active:
        reasons.append("COOLDOWN_ACTIVE")
    if should_generate:
        reasons.append("TRIGGER_CONDITIONS_MET")

    if not forecast_available:
        status = "unavailable"
    elif cooldown_active and rain_passed and field_passed:
        status = "cooldown"
    elif should_generate:
        status = "ready"
    else:
        status = "not_triggered"

    shelter = shelter_route.get("shelter", {})
    route = shelter_route.get("route", {})
    target_date = forecast.get("target_date")
    context_id = f"{field_id}:{target_date or 'unknown'}:{forecast.get('base_datetime') or 'unknown'}"
    return {
        "schema_version": "1.0",
        "context_id": context_id,
        "generated_at": now.isoformat(),
        "status": status,
        "pilot": {
            "location_label": shelter_route.get("location_label", "충북 청주시 흥덕구 오송읍 미호강 인접 농경지"),
            "timezone": config["timezone"],
        },
        "field": {
            "field_id": field_id,
            "display_name": field["display_name"],
            "owner_display_name": field.get("owner_display_name"),
            "area_m2": field.get("derived_metrics", {}).get("area_m2"),
            "centre_wgs84": field["derived_metrics"]["centre_wgs84"],
            "geometry_accuracy": field["geometry_accuracy"],
            "registration_status": field.get("registration_status"),
        },
        "forecast": {
            **forecast,
            "base_age_hours": round(base_age_hours, 2) if base_age_hours is not None else None,
            "fresh_for_trigger": forecast_fresh,
            "used_for_trigger": True,
        },
        "hydrology": hydrology_context(hydrology_state, now),
        "inundation": {
            "dataset_id": inundation["dataset_id"],
            "source": inundation["source"],
            "field_affected_percent": affected_percent,
            "maximum_official_class_code": field_info.get("maximum_official_class_code"),
            "maximum_official_class_label": field_info.get("maximum_official_class_label"),
            "visual_depth_cap_m": inundation["method"].get("visual_depth_cap_m"),
            "condition_role": "official_hazard_overlap_proxy",
            "hydraulic_event_forecast": False,
        },
        "trigger": {
            "decision_only": True,
            "should_generate_video": should_generate,
            "target_date": target_date,
            "rain_condition": {
                "metric": trigger_config["rain_total_field"],
                "value_mm": rain_total,
                "threshold_mm": trigger_config["rain_threshold_mm"],
                "passed": rain_passed,
                "threshold_status": config["policies"]["rain_threshold_status"],
            },
            "field_condition": {
                "metric": "official_hazard_overlap_percent",
                "value_percent": affected_percent,
                "threshold_percent": trigger_config["field_overlap_threshold_percent"],
                "passed": field_passed,
                "proxy_only": True,
            },
            "cooldown": {
                "hours": trigger_config["cooldown_hours"],
                "active": cooldown_active,
                "last_dispatch_at": last_at.isoformat() if last_at else None,
                "cooldown_until": cooldown_until.isoformat() if cooldown_until else None,
                "last_event_id": last_event.get("event_id") if last_event else None,
            },
            "reason_codes": reasons,
        },
        "actions": {
            "before_rain": guidance_policy.get("allowed_before_rain_actions", []),
            "during_rain": guidance_policy.get("required_during_rain_actions", []),
            "official_sources": guidance_policy.get("official_sources", []),
        },
        "shelter": shelter,
        "route": route,
        "provenance": {
            "trigger_config": config["dataset_id"],
            "forecast_dataset": forecast.get("dataset_id"),
            "inundation_dataset": inundation["dataset_id"],
            "hydrology_dataset": (hydrology_state or {}).get("dataset_id"),
        },
        "limitations": [
            "The 80 mm threshold is an MVP calibrated candidate, not an official warning criterion.",
            "The field condition is overlap with a 100-year official hazard map, not a rain-conditioned hydraulic simulation.",
            "HRFCO observations confirm current river state and do not predict tomorrow's inundation footprint.",
            "The registered field is an OSM farmland polygon, not a cadastral ownership parcel.",
            "Categorical PCP values use an explicit representative estimate and retain lower/upper bounds.",
        ],
    }


def load_inputs(
    config_path: Path,
    forecast_path: Optional[Path] = None,
    history_path: Optional[Path] = None,
):
    root = config_path.resolve().parents[1]
    config = read_json(config_path)
    inputs = config["inputs"]
    outputs = config["outputs"]
    selected_forecast = forecast_path or resolve(root, outputs["forecast"])
    selected_history = history_path or resolve(root, outputs["dispatch_history"])
    return {
        "config": config,
        "field": read_json(resolve(root, inputs["field"])),
        "inundation": read_json(resolve(root, inputs["inundation"])),
        "forecast": read_json(selected_forecast),
        "hydrology": read_json(resolve(root, inputs["hydrology"]), default={}),
        "guidance": read_json(resolve(root, inputs["guidance"])),
        "shelter_route": read_json(resolve(root, inputs["shelter_route"])),
        "history": read_json(selected_history, default={"schema_version": "1.0", "events": []}),
        "root": root,
        "forecast_path": selected_forecast,
        "history_path": selected_history,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--forecast", type=Path)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--now", help="ISO-8601 KST time for deterministic checks")
    args = parser.parse_args()
    loaded = load_inputs(args.config, args.forecast, args.history)
    now = parse_datetime(args.now) if args.now else datetime.now(KST)
    context = build_guidance_context(
        loaded["config"],
        loaded["field"],
        loaded["inundation"],
        loaded["forecast"],
        loaded["hydrology"],
        loaded["guidance"],
        loaded["shelter_route"],
        loaded["history"],
        now,
    )
    output = args.output or resolve(loaded["root"], loaded["config"]["outputs"]["context"])
    context["provenance"]["forecast_sha256"] = file_sha256(loaded["forecast_path"])
    atomic_write_json(output, context)
    print(json.dumps({
        "status": context["status"],
        "should_generate_video": context["trigger"]["should_generate_video"],
        "rain_24h_mm": context["trigger"]["rain_condition"]["value_mm"],
        "field_affected_percent": context["trigger"]["field_condition"]["value_percent"],
        "reason_codes": context["trigger"]["reason_codes"],
        "context_path": str(output),
    }, ensure_ascii=False, indent=2))
    return 2 if context["status"] == "unavailable" else 0


if __name__ == "__main__":
    raise SystemExit(main())
