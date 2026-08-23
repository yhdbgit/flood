#!/usr/bin/env python3
"""Fetch and validate HRFCO observations for the Gangnae pilot.

The API key is loaded from HRFCO_API_KEY or the project-local .env file.
The key is never written to output or included in error messages.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from datetime import datetime, timedelta
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "hydro_stations.json"
ENV_PATH = ROOT / ".env"
OUTPUT_PATH = ROOT / "data" / "runtime" / "hydro_snapshot.json"
KST = ZoneInfo("Asia/Seoul")

RISK_ORDER = (
    ("serious", "심각", "srswl"),
    ("alarm", "경보", "almwl"),
    ("warning", "주의", "wrnwl"),
    ("attention", "관심", "attwl"),
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_api_key() -> str:
    key = os.environ.get("HRFCO_API_KEY", "").strip()
    if key:
        return key
    if ENV_PATH.is_file():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            clean = line.strip()
            if not clean or clean.startswith("#") or "=" not in clean:
                continue
            name, value = clean.split("=", 1)
            if name.strip() == "HRFCO_API_KEY":
                key = value.strip().strip("\"'")
                break
    if not key:
        raise RuntimeError("HRFCO_API_KEY is not configured")
    return key


def number(value):
    try:
        clean = str(value).strip()
        return float(clean) if clean else None
    except (TypeError, ValueError):
        return None


def dms_to_decimal(value):
    try:
        degree, minute, second = [float(part) for part in value.strip().split("-")]
        return degree + minute / 60.0 + second / 3600.0
    except (AttributeError, TypeError, ValueError):
        return None


def parse_time(value: str):
    return datetime.strptime(value, "%Y%m%d%H%M").replace(tzinfo=KST)


def atomic_write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


class HrfcoClient:
    def __init__(self, api_base: str, api_key: str):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key

    def get(self, path: str, allow_no_data: bool = False):
        url = f"{self.api_base}/{self.api_key}/{path.lstrip('/')}"
        request = urllib.request.Request(
            url, headers={"User-Agent": "ICTCB-Gangnae-Hydro/2.0"}
        )
        last_error = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=25) as response:
                    document = json.loads(response.read().decode("utf-8"))
                api_code = document.get("code") if isinstance(document, dict) else None
                if api_code == "990" and allow_no_data:
                    return {"content": [], "no_data": True}
                if api_code:
                    raise RuntimeError(f"HRFCO API returned code {api_code}")
                if not isinstance(document, dict):
                    raise RuntimeError("HRFCO API returned a non-object response")
                return document
            except urllib.error.HTTPError as exc:
                last_error = RuntimeError(f"HRFCO HTTP status {exc.code}")
            except urllib.error.URLError as exc:
                last_error = RuntimeError(
                    f"HRFCO network error: {type(exc.reason).__name__}"
                )
            except json.JSONDecodeError:
                last_error = RuntimeError("HRFCO API returned invalid JSON")
            except RuntimeError:
                raise
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
        raise last_error or RuntimeError("HRFCO API request failed")


def classify_risk(water_level, station_info):
    if water_level is None:
        return {"code": "unknown", "label": "판정불가"}
    for code, label, field in RISK_ORDER:
        threshold = number(station_info.get(field))
        if threshold is not None and water_level >= threshold:
            return {"code": code, "label": label}
    return {"code": "normal", "label": "정상"}


def build_station_snapshot(client, spec, station_info, now):
    code = spec["code"]
    document = client.get(f"waterlevel/list/10M/{code}.json")
    rows = document.get("content", [])
    if not rows:
        raise RuntimeError(f"No latest water-level row for station {code}")
    row = rows[-1]
    if row.get("wlobscd") != code:
        raise RuntimeError(f"Station code mismatch for {code}")

    observed_at = parse_time(row["ymdhm"])
    age_minutes = (now - observed_at).total_seconds() / 60.0
    water_level = number(row.get("wl"))
    flow = number(row.get("fw"))
    gauge_zero = number(station_info.get("gdt"))
    absolute_level = (
        gauge_zero + water_level
        if gauge_zero is not None and water_level is not None
        else None
    )
    reference = number(spec.get("reference_water_level_m"))
    visual_delta = (
        water_level - reference
        if water_level is not None and reference is not None
        else 0.0
    )
    warnings = []
    if station_info.get("obsnm") != spec.get("expected_name"):
        warnings.append("station_name_mismatch")
    if age_minutes > 30:
        warnings.append("stale_observation")
    if water_level is None:
        warnings.append("missing_water_level")
    if flow is None:
        warnings.append("missing_flow")

    return {
        "code": code,
        "name": station_info.get("obsnm"),
        "expected_name": spec.get("expected_name"),
        "role": spec.get("role"),
        "agency": station_info.get("agcnm"),
        "address": " ".join(
            part.strip()
            for part in (station_info.get("addr", ""), station_info.get("etcaddr", ""))
            if part and part.strip()
        ),
        "longitude": dms_to_decimal(station_info.get("lon")),
        "latitude": dms_to_decimal(station_info.get("lat")),
        "observed_at": observed_at.isoformat(),
        "age_minutes": round(age_minutes, 1),
        "water_level_m": water_level,
        "flow_m3s": flow,
        "gauge_zero_el_m": gauge_zero,
        "estimated_surface_el_m": (
            round(absolute_level, 3) if absolute_level is not None else None
        ),
        "reference_water_level_m": reference,
        "visual_level_delta_m": round(visual_delta, 3),
        "risk": classify_risk(water_level, station_info),
        "thresholds_m": {
            "attention": number(station_info.get("attwl")),
            "warning": number(station_info.get("wrnwl")),
            "alarm": number(station_info.get("almwl")),
            "serious": number(station_info.get("srswl")),
            "planned_flood": number(station_info.get("pfh")),
        },
        "is_flood_forecast_station": station_info.get("fstnyn") == "Y",
        "quality": "live" if not warnings else "warning",
        "warnings": warnings,
    }


def fetch_history(client, station_code, latest_time, history_hours):
    end = latest_time
    start = end - timedelta(hours=history_hours)
    path = (
        f"waterlevel/list/10M/{station_code}/"
        f"{start:%Y%m%d%H%M}/{end:%Y%m%d%H%M}.json"
    )
    rows = client.get(path).get("content", [])
    series = []
    for row in rows:
        value = number(row.get("wl"))
        if value is None:
            continue
        try:
            observed = parse_time(row["ymdhm"])
        except (KeyError, ValueError):
            continue
        series.append((observed, value))
    series.sort(key=lambda item: item[0])
    if len(series) < 2:
        return {"count": len(series), "trend_m_per_hour": None, "interval_minutes": None}
    duration_hours = (series[-1][0] - series[0][0]).total_seconds() / 3600.0
    trend = (series[-1][1] - series[0][1]) / duration_hours if duration_hours else 0.0
    gaps = [
        (later[0] - earlier[0]).total_seconds() / 60.0
        for earlier, later in zip(series, series[1:])
    ]
    return {
        "count": len(series),
        "from": series[0][0].isoformat(),
        "to": series[-1][0].isoformat(),
        "min_water_level_m": min(value for _, value in series),
        "max_water_level_m": max(value for _, value in series),
        "trend_m_per_hour": round(trend, 4),
        "interval_minutes": statistics.median(gaps),
    }


def collect():
    config = read_json(CONFIG_PATH)
    client = HrfcoClient(config["api_base"], load_api_key())
    now = datetime.now(KST)

    info_rows = client.get("waterlevel/info.json").get("content", [])
    station_info = {row.get("wlobscd"): row for row in info_rows}
    snapshots = []
    for spec in config["stations"]:
        info = station_info.get(spec["code"])
        if info is None:
            raise RuntimeError(f"Station metadata not found: {spec['code']}")
        snapshots.append(build_station_snapshot(client, spec, info, now))

    primary = next(item for item in snapshots if item["role"] == "upstream_primary")
    latest_time = datetime.fromisoformat(primary["observed_at"])
    history = fetch_history(
        client, primary["code"], latest_time, config.get("history_hours", 2)
    )
    primary["history"] = history
    primary["trend"] = (
        "rising"
        if (history.get("trend_m_per_hour") or 0) > 0.005
        else "falling"
        if (history.get("trend_m_per_hour") or 0) < -0.005
        else "steady"
    )

    flood_document = client.get("fldfct/list.json", allow_no_data=True)
    flood_rows = flood_document.get("content", [])
    payload = {
        "schema_version": 1,
        "source": "Han River Flood Control Office OpenAPI",
        "generated_at": now.isoformat(),
        "collector_status": "live",
        "source_notice": (
            "T/M raw observations; values may differ from quality-controlled final data."
        ),
        "primary_river": config["primary_river"],
        "stations": snapshots,
        "primary_station_code": primary["code"],
        "scene_state": {
            "risk": primary["risk"],
            "trend": primary["trend"],
            "water_level_m": primary["water_level_m"],
            "flow_m3s": primary["flow_m3s"],
            "visual_level_delta_m": primary["visual_level_delta_m"],
        },
        "flood_forecast": {
            "active": bool(flood_rows),
            "count": len(flood_rows),
            "items": flood_rows,
        },
    }
    atomic_write_json(OUTPUT_PATH, payload)
    return payload


def main():
    try:
        payload = collect()
    except Exception as exc:
        print(f"[hrfco] collection failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    primary = next(
        item for item in payload["stations"] if item["code"] == payload["primary_station_code"]
    )
    print(
        "[hrfco] ok "
        f"station={primary['name']} observed_at={primary['observed_at']} "
        f"wl={primary['water_level_m']}m flow={primary['flow_m3s']}m3/s "
        f"risk={primary['risk']['label']} trend={primary['trend']}"
    )
    print(f"[hrfco] wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
