#!/usr/bin/env python3
"""Validate trusted V23 video-generation events without re-running trigger logic."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Dict, List


SCHEMA_VERSION = "1.0"
EVENT_TYPE = "flood_guidance_requested"
SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]+$")
TOP_LEVEL_KEYS = {
    "schema_version",
    "event_type",
    "event_id",
    "user_id",
    "field_id",
    "scenario_id",
    "triggered_at",
    "requested_at",
    "source",
    "forecast_summary",
    "hydrology_summary",
    "delivery",
    "metadata",
}
REQUIRED_KEYS = {
    "schema_version",
    "event_type",
    "event_id",
    "user_id",
    "field_id",
    "scenario_id",
    "triggered_at",
    "requested_at",
    "source",
}


class EventContractError(ValueError):
    """Raised when an upstream trigger event does not match the V23 contract."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _validate_id(value: Any, path: str, errors: List[str], max_length: int = 128) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path} must be a non-empty string")
    elif len(value) > max_length:
        errors.append(f"{path} must be at most {max_length} characters")
    elif not SAFE_ID.fullmatch(value):
        errors.append(f"{path} contains unsupported characters")


def _validate_datetime(value: Any, path: str, errors: List[str]) -> None:
    if not isinstance(value, str):
        errors.append(f"{path} must be an ISO-8601 date-time string")
        return
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{path} must be a valid ISO-8601 date-time")
        return
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(f"{path} must include a timezone offset")


def _reject_unknown_keys(value: Dict[str, Any], allowed: set, path: str, errors: List[str]) -> None:
    for key in sorted(set(value) - allowed):
        errors.append(f"{path}.{key} is not allowed")


def validate_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Return a defensive copy of a valid event or raise EventContractError.

    This validator checks transport and data shape only. It deliberately does
    not calculate rainfall thresholds, water-level thresholds, cooldowns, or a
    should-generate-video decision; those belong to the upstream trigger owner.
    """
    if not isinstance(event, dict):
        raise EventContractError(["event must be a JSON object"])

    errors: List[str] = []
    missing = sorted(REQUIRED_KEYS - set(event))
    errors.extend(f"{key} is required" for key in missing)
    _reject_unknown_keys(event, TOP_LEVEL_KEYS, "event", errors)

    if event.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if event.get("event_type") != EVENT_TYPE:
        errors.append(f"event_type must be {EVENT_TYPE}")

    for key in ("event_id", "user_id", "field_id", "scenario_id"):
        _validate_id(event.get(key), key, errors)
    for key in ("triggered_at", "requested_at"):
        _validate_datetime(event.get(key), key, errors)

    source = event.get("source")
    if not isinstance(source, dict):
        errors.append("source must be an object")
    else:
        _reject_unknown_keys(source, {"system_id", "trigger_version"}, "source", errors)
        _validate_id(source.get("system_id"), "source.system_id", errors)
        version = source.get("trigger_version")
        if version is not None and (not isinstance(version, str) or not version or len(version) > 64):
            errors.append("source.trigger_version must be a non-empty string of at most 64 characters")

    forecast = event.get("forecast_summary")
    hydrology = event.get("hydrology_summary")
    if forecast is None and hydrology is None:
        errors.append("at least one of forecast_summary or hydrology_summary is required")

    if forecast is not None:
        if not isinstance(forecast, dict) or not forecast:
            errors.append("forecast_summary must be a non-empty object")
        else:
            _reject_unknown_keys(forecast, {"rain_24h_mm", "expected_start_at", "summary_text"}, "forecast_summary", errors)
            rain = forecast.get("rain_24h_mm")
            if rain is not None and (not isinstance(rain, (int, float)) or isinstance(rain, bool) or not 0 <= rain <= 2000):
                errors.append("forecast_summary.rain_24h_mm must be between 0 and 2000")
            if "expected_start_at" in forecast:
                _validate_datetime(forecast["expected_start_at"], "forecast_summary.expected_start_at", errors)
            summary = forecast.get("summary_text")
            if summary is not None and (not isinstance(summary, str) or len(summary) > 500):
                errors.append("forecast_summary.summary_text must be a string of at most 500 characters")

    if hydrology is not None:
        if not isinstance(hydrology, dict):
            errors.append("hydrology_summary must be an object")
        else:
            _reject_unknown_keys(hydrology, {"station_id", "observed_at", "water_level_m", "alert_level"}, "hydrology_summary", errors)
            _validate_id(hydrology.get("station_id"), "hydrology_summary.station_id", errors)
            _validate_datetime(hydrology.get("observed_at"), "hydrology_summary.observed_at", errors)
            level = hydrology.get("water_level_m")
            if level is not None and (not isinstance(level, (int, float)) or isinstance(level, bool) or not -100 <= level <= 1000):
                errors.append("hydrology_summary.water_level_m must be between -100 and 1000")
            alert = hydrology.get("alert_level")
            if alert is not None and (not isinstance(alert, str) or not alert or len(alert) > 64):
                errors.append("hydrology_summary.alert_level must be a non-empty string of at most 64 characters")

    delivery = event.get("delivery")
    if delivery is not None:
        if not isinstance(delivery, dict):
            errors.append("delivery must be an object")
        else:
            _reject_unknown_keys(delivery, {"locale", "recipient_ids"}, "delivery", errors)
            locale = delivery.get("locale")
            if locale is not None and (not isinstance(locale, str) or not 2 <= len(locale) <= 32):
                errors.append("delivery.locale must be a string between 2 and 32 characters")
            recipients = delivery.get("recipient_ids")
            if recipients is not None:
                if not isinstance(recipients, list) or any(not isinstance(item, str) or not item or len(item) > 128 for item in recipients):
                    errors.append("delivery.recipient_ids must contain non-empty strings of at most 128 characters")
                elif len(recipients) != len(set(recipients)):
                    errors.append("delivery.recipient_ids must not contain duplicates")

    metadata = event.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append("metadata must be an object")

    if errors:
        raise EventContractError(errors)
    return deepcopy(event)


def load_and_validate_event(path: Path) -> Dict[str, Any]:
    return validate_event(json.loads(path.read_text(encoding="utf-8")))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a V23 upstream trigger event")
    parser.add_argument("event", type=Path)
    args = parser.parse_args()
    event = load_and_validate_event(args.event)
    print(json.dumps({
        "status": "accepted",
        "event_id": event["event_id"],
        "field_id": event["field_id"],
        "scenario_id": event["scenario_id"],
        "trigger_recalculated": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
