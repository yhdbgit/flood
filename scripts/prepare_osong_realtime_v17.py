#!/usr/bin/env python3
"""Map fresh HRFCO gauge observations to the auditable V16 visual stages."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from shapely.geometry import shape


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
DEFAULT_SNAPSHOT = ROOT / "data" / "runtime" / "hydro_snapshot.json"
MAPPING_PATH = ROOT / "config" / "realtime_stage_mapping_v17.json"
FIELD_PATH = ROOT / "config" / "osong_farmland_v11.json"
V16_PATH = ROOT / "data" / "processed" / "osong_inundation_v16.json"
OUTPUT_PATH = ROOT / "data" / "runtime" / "osong_realtime_state_v17.json"
REPORT_PATH = ROOT / "output" / "realtime_v17" / "decision_report.json"
KST = ZoneInfo("Asia/Seoul")
RISK_RANK = {"unknown": -1, "normal": 0, "attention": 1, "warning": 2, "alarm": 3, "serious": 4}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def haversine_m(a, b):
    lon1, lat1 = a
    lon2, lat2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371000.0 * 2.0 * math.asin(math.sqrt(h))


def parse_observed_at(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return result if result.tzinfo else result.replace(tzinfo=KST)


def evaluate_station(station, now, freshness_minutes, field_lonlat):
    observed = parse_observed_at(station.get("observed_at"))
    age = (now - observed.astimezone(KST)).total_seconds() / 60.0 if observed else None
    level = station.get("water_level_m")
    risk = station.get("risk") or {"code": "unknown", "label": "판정불가"}
    code = risk.get("code", "unknown")
    warnings = list(station.get("warnings") or [])
    fresh = (
        observed is not None
        and level is not None
        and age is not None
        and -5.0 <= age <= float(freshness_minutes)
        and "stale_observation" not in warnings
        and code in RISK_RANK
        and code != "unknown"
    )
    lon, lat = station.get("longitude"), station.get("latitude")
    distance = haversine_m(field_lonlat, (float(lon), float(lat))) if lon is not None and lat is not None else None
    thresholds = station.get("thresholds_m") or {}
    attention = thresholds.get("attention")
    threshold_fraction = None
    if level is not None and attention not in (None, 0):
        threshold_fraction = float(level) / float(attention)
    return {
        "code": station.get("code"),
        "name": station.get("name"),
        "role": station.get("role"),
        "observed_at": observed.isoformat() if observed else None,
        "age_minutes": round(age, 1) if age is not None else None,
        "water_level_m": level,
        "flow_m3s": station.get("flow_m3s"),
        "risk": risk,
        "risk_rank": RISK_RANK.get(code, -1),
        "thresholds_m": thresholds,
        "attention_threshold_fraction": round(threshold_fraction, 4) if threshold_fraction is not None else None,
        "distance_to_field_m": round(distance, 1) if distance is not None else None,
        "fresh": fresh,
        "warnings": warnings,
    }


def select_station(evaluated):
    eligible = [item for item in evaluated if item["fresh"]]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            item["risk_rank"],
            -(item["distance_to_field_m"] if item["distance_to_field_m"] is not None else float("inf")),
        ),
    )


def build_state(snapshot, mapping, v16, field, now):
    centroid = shape(field["geometry"]).centroid
    field_lonlat = (float(centroid.x), float(centroid.y))
    evaluated = [
        evaluate_station(item, now, mapping["freshness_minutes"], field_lonlat)
        for item in snapshot.get("stations", [])
    ]
    decision = select_station(evaluated)
    if decision is None:
        status = "unavailable"
        selected_stage = None
        risk = {"code": "unknown", "label": "판정불가"}
        reason = "No fresh station observation satisfies the V17 freshness and value checks."
    else:
        status = "ok"
        risk = decision["risk"]
        selected_stage = mapping["risk_to_visual_stage"].get(risk["code"])
        if selected_stage is None:
            status = "unavailable"
            reason = f"Risk code is not mapped: {risk['code']}"
        else:
            reason = (
                f"Official risk {risk['label']} at {decision['name']} maps to V16 stage {selected_stage}."
            )
    stage = next((item for item in v16["stages"] if item["code"] == selected_stage), None)
    return {
        "schema_version": 1,
        "dataset_id": "OSONG-REALTIME-STATE-V17",
        "generated_at": now.isoformat(),
        "status": status,
        "source": snapshot.get("source"),
        "source_snapshot_generated_at": snapshot.get("generated_at"),
        "source_snapshot_status": snapshot.get("collector_status"),
        "source_notice": snapshot.get("source_notice"),
        "mapping_dataset": mapping["dataset_id"],
        "station_selection_policy": mapping["station_selection_policy"],
        "stations": evaluated,
        "decision_station": decision,
        "risk": risk,
        "selected_visual_stage": selected_stage,
        "selected_stage": stage,
        "decision_reason": reason,
        "flood_forecast": {
            "active": bool((snapshot.get("flood_forecast") or {}).get("active")),
            "count": int((snapshot.get("flood_forecast") or {}).get("count", 0)),
            "used_for_stage_selection": False,
        },
        "interpretation": mapping["interpretation"].get(selected_stage) if selected_stage else None,
        "realtime_observation_applied": bool(status == "ok" and selected_stage),
        "hydraulic_inundation_forecast": False,
        "limitations": mapping["limitations"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    args = parser.parse_args()
    snapshot_path = args.snapshot.resolve()
    snapshot = load_json(snapshot_path)
    mapping = load_json(MAPPING_PATH)
    v16 = load_json(V16_PATH)
    field = load_json(FIELD_PATH)
    now = datetime.now(KST)
    state = build_state(snapshot, mapping, v16, field, now)
    state["source_snapshot_path"] = str(snapshot_path)
    state["source_snapshot_sha256"] = sha256(snapshot_path)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "status": state["status"],
        "state_path": str(OUTPUT_PATH),
        "decision_station": state["decision_station"]["name"] if state["decision_station"] else None,
        "observed_at": state["decision_station"]["observed_at"] if state["decision_station"] else None,
        "water_level_m": state["decision_station"]["water_level_m"] if state["decision_station"] else None,
        "risk": state["risk"],
        "selected_visual_stage": state["selected_visual_stage"],
        "field_affected_percent": (
            state["selected_stage"]["field_affected_percent"] if state["selected_stage"] else None
        ),
        "realtime_observation_applied": state["realtime_observation_applied"],
        "video_rendered": False,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if state["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
