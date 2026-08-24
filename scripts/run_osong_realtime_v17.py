#!/usr/bin/env python3
"""Run the V17 fetch -> decision -> Blender still workflow safely."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
SNAPSHOT_PATH = ROOT / "data" / "runtime" / "hydro_snapshot.json"
STATE_PATH = ROOT / "data" / "runtime" / "osong_realtime_state_v17.json"
REPORT_PATH = ROOT / "output" / "realtime_v17" / "workflow_report.json"
BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")


def execute(command):
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="")
    return completed.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-fetch", action="store_true")
    args = parser.parse_args()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fetch_status = "skipped"
    if not args.skip_fetch:
        fetch_code = execute(["python3", "scripts/fetch_hrfco_data.py"])
        fetch_status = "live" if fetch_code == 0 else "cached_fallback"
        if fetch_code != 0 and not SNAPSHOT_PATH.is_file():
            raise RuntimeError("HRFCO fetch failed and no cached snapshot exists")

    decision_code = execute(["python3", "scripts/prepare_osong_realtime_v17.py"])
    if decision_code != 0:
        report = {
            "status": "unavailable",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "fetch_status": fetch_status,
            "decision_exit_code": decision_code,
            "blender_executed": False,
            "reason": "The cached/live observation failed freshness or value checks.",
            "video_rendered": False,
        }
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    blender_code = execute([
        str(BLENDER),
        "--background",
        "blender/osong_inundation_v16.blend",
        "--python",
        "blender/apply_osong_realtime_v17.py",
    ])
    if blender_code != 0:
        raise RuntimeError(f"Blender V17 application failed with exit code {blender_code}")
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    report = {
        "status": "ok",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "fetch_status": fetch_status,
        "selected_stage": state["selected_visual_stage"],
        "risk": state["risk"],
        "decision_station": state["decision_station"]["name"],
        "observed_at": state["decision_station"]["observed_at"],
        "water_level_m": state["decision_station"]["water_level_m"],
        "blender_executed": True,
        "blend_path": str(ROOT / "blender" / "osong_realtime_v17.blend"),
        "preview_path": str(ROOT / "output" / "realtime_v17" / "current_state.png"),
        "video_rendered": False,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
