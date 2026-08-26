#!/usr/bin/env python3
"""Build a V23 event-time visual composition plan from cached media only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Dict

from v23_event_contract import load_and_validate_event, validate_event
from v23_field_registry import FieldRegistry
from v23_flood_asset_catalog import FloodAssetCatalog


ROOT = Path(__file__).resolve().parents[1]
COMPOSITION_ASSET_PLAN = ROOT / "data" / "v23" / "composition_assets" / "composition_asset_plan_v23.json"
COMPOSITION_ASSET_MANIFEST = ROOT / "data" / "v23" / "composition_assets" / "composition_assets_manifest_v23.json"
DEFAULT_OUTPUT_ROOT = ROOT / "output" / "personalized_visuals" / "v23"
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(value: str) -> str:
    return SAFE_NAME.sub("_", value).strip("_")


def build_personalized_visual_plan(
    event: Dict[str, Any],
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> Dict[str, Any]:
    event = validate_event(event)
    field = FieldRegistry.load().resolve_event(event)
    flood = FloodAssetCatalog.load().select(field["field_id"], event["scenario_id"])
    asset_plan = json.loads(COMPOSITION_ASSET_PLAN.read_text(encoding="utf-8"))
    assets = json.loads(COMPOSITION_ASSET_MANIFEST.read_text(encoding="utf-8"))
    if assets.get("status") != "ready":
        raise ValueError("Stage 7 composition assets are not ready")
    by_id = {item["asset_id"]: item for item in assets["assets"]}
    field_selection = asset_plan["selection_by_field_id"][field["field_id"]]
    background = by_id[field_selection["background_asset_id"]]
    field_overlay = by_id[field_selection["field_overlay_asset_id"]]
    shelter_overlay = by_id[asset_plan["shared_shelter_overlay_asset_id"]]

    run_dir = output_root / _slug(event["event_id"])
    output_video = run_dir / f"{_slug(field['field_id'])}_personalized_visual_v23.mp4"
    output_blend = run_dir / f"{_slug(field['field_id'])}_composition_v23.blend"
    report = run_dir / "composition_report_v23.json"
    flood_segments = flood["segments"]
    strips = [
        {
            "strip_id": "common_background_full",
            "role": "base_common_background",
            "channel": 1,
            "timeline_start": 1,
            "duration_frames": 960,
            "path": asset_plan["common_background_clip"],
            "alpha_over": False,
        },
        {
            "strip_id": background["asset_id"],
            "role": "field_camera_background_replacement",
            "channel": 2,
            "timeline_start": 1,
            "duration_frames": 719,
            "path": background["project_relative_path"],
            "alpha_over": False,
        },
        *[
            {
                "strip_id": item["segment_id"],
                "role": "flood_rgba",
                "channel": 3,
                "timeline_start": item["frame_start"],
                "duration_frames": item["frame_count"],
                "path": item["project_relative_path"],
                "alpha_over": True,
            }
            for item in flood_segments
        ],
        {
            "strip_id": field_overlay["asset_id"],
            "role": "selected_field_rgba",
            "channel": 4,
            "timeline_start": 1,
            "duration_frames": 719,
            "path": field_overlay["project_relative_path"],
            "alpha_over": True,
        },
        {
            "strip_id": shelter_overlay["asset_id"],
            "role": "shelter_rgba",
            "channel": 4,
            "timeline_start": 720,
            "duration_frames": 241,
            "path": shelter_overlay["project_relative_path"],
            "alpha_over": True,
        },
    ]
    return {
        "schema_version": "1.0",
        "workflow_version": "V23-STAGE-7",
        "status": "planned",
        "event_id": event["event_id"],
        "user_id": event["user_id"],
        "field_id": field["field_id"],
        "scenario_id": event["scenario_id"],
        "scene_pack_id": field["asset_binding"]["scene_pack_id"],
        "resolution": [1280, 720],
        "fps": 16,
        "frame_start": 1,
        "frame_end": 960,
        "duration_seconds": 60.0,
        "strips": strips,
        "output_video": str(output_video),
        "output_blend": str(output_blend),
        "composition_report": str(report),
        "render_policy": {
            "blender_3d_scene_render": False,
            "vse_cached_media_composition": True,
            "full_scene_rerender_at_trigger_time": False,
        },
        "field_focus_flood_visible": flood["field_focus_flood_visible"],
        "risk_claim_allowed": flood["risk_claim_allowed"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a cached-media V23 personalized visual plan")
    parser.add_argument("event", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    event = load_and_validate_event(args.event)
    document = build_personalized_visual_plan(event, output_root=args.output_root)
    output = args.output or Path(document["output_video"]).parent / "composition_plan_v23.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "plan": str(output),
        "field_id": document["field_id"],
        "scenario_id": document["scenario_id"],
        "strip_count": len(document["strips"]),
        "blender_3d_scene_render": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
