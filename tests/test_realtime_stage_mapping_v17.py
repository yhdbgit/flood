#!/usr/bin/env python3
"""Deterministic tests for V17 risk-to-visual-stage mapping."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
KST = ZoneInfo("Asia/Seoul")


def load_module():
    path = ROOT / "scripts" / "prepare_osong_realtime_v17.py"
    spec = importlib.util.spec_from_file_location("prepare_osong_realtime_v17", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot_for(risk_code, observed_at, water_level=5.1):
    labels = {
        "normal": "정상",
        "attention": "관심",
        "warning": "주의",
        "alarm": "경보",
        "serious": "심각",
    }
    station = {
        "code": "TEST-1",
        "name": "테스트 관측소",
        "role": "test",
        "observed_at": observed_at.isoformat(),
        "water_level_m": water_level,
        "flow_m3s": 1.0,
        "risk": {"code": risk_code, "label": labels[risk_code]},
        "thresholds_m": {"attention": 5.0, "warning": 7.0, "alarm": 8.0, "serious": 9.0},
        "longitude": 127.305,
        "latitude": 36.585,
        "warnings": [],
    }
    return {
        "source": "fixture",
        "generated_at": observed_at.isoformat(),
        "collector_status": "fixture",
        "stations": [station],
        "flood_forecast": {"active": False, "count": 0},
    }


def main():
    module = load_module()
    mapping = read_json(ROOT / "config" / "realtime_stage_mapping_v17.json")
    v16 = read_json(ROOT / "data" / "processed" / "osong_inundation_v16.json")
    field = read_json(ROOT / "config" / "osong_farmland_v11.json")
    now = datetime.now(KST)
    expected = {
        "normal": "normal",
        "attention": "intermediate",
        "warning": "intermediate",
        "alarm": "maximum",
        "serious": "maximum",
    }
    results = {}
    for risk, stage in expected.items():
        state = module.build_state(snapshot_for(risk, now - timedelta(minutes=5)), mapping, v16, field, now)
        assert state["status"] == "ok", state
        assert state["selected_visual_stage"] == stage, state
        results[risk] = stage
    stale = module.build_state(
        snapshot_for("serious", now - timedelta(minutes=31)), mapping, v16, field, now
    )
    assert stale["status"] == "unavailable", stale
    assert stale["selected_visual_stage"] is None, stale
    results["stale_serious"] = "unavailable"
    print(json.dumps({"status": "ok", "cases": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
