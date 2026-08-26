#!/usr/bin/env python3
"""Plan reusable V23 background and overlay assets for event-time composition."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
FIELD_MANIFEST = ROOT / "data" / "v23" / "field_assets" / "field_assets_manifest_v23.json"
FLOOD_PLAN = ROOT / "data" / "v23" / "flood_assets" / "flood_render_plan_v23.json"
DEFAULT_OUTPUT = ROOT / "data" / "v23" / "composition_assets" / "composition_asset_plan_v23.json"
SOURCE_BLEND = "blender/osong_personalization_v23.blend"
SOURCE_CAMERA = "Camera_Osong_Shelter_V19"
FPS = 16
RESOLUTION = [1280, 720]


def build_composition_asset_plan() -> Dict[str, Any]:
    fields = json.loads(FIELD_MANIFEST.read_text(encoding="utf-8"))
    flood = json.loads(FLOOD_PLAN.read_text(encoding="utf-8"))
    if fields.get("status") not in {"built_preview_pending", "previews_rendered_review_pending", "ready"}:
        raise ValueError("Stage 5 field-personalization blend must be rebuilt")
    if flood.get("status") != "planned":
        raise ValueError("Corrected Stage 6 flood render plan is required")

    assets: List[Dict[str, Any]] = []
    selection: Dict[str, Dict[str, str]] = {}
    for field in sorted(fields["field_assets"], key=lambda item: item["field_id"]):
        suffix = field["field_id"][-3:]
        background_id = f"field_{suffix}_clean_background"
        overlay_id = f"field_{suffix}_overlay_rgba"
        assets.extend([
            {
                "asset_id": background_id,
                "asset_type": "field_clean_background",
                "field_id": field["field_id"],
                "camera_object": field["camera_object"],
                "view_layer": "V23_COMMON_BACKGROUND",
                "frame_start": 1,
                "frame_end": 719,
                "frame_count": 719,
                "duration_seconds": 44.9375,
                "transparent_background": False,
                "container": "MPEG4",
                "codec": "H264",
                "colour_mode": "RGB",
                "output_path": f"output/composition_assets/v23/backgrounds/{background_id}_0001_0719.mp4",
                "proof_frames": [1, 120, 240, 400, 600, 719],
            },
            {
                "asset_id": overlay_id,
                "asset_type": "field_overlay",
                "field_id": field["field_id"],
                "camera_object": field["camera_object"],
                "view_layer": field["rgba_view_layer"],
                "frame_start": 1,
                "frame_end": 719,
                "frame_count": 719,
                "duration_seconds": 44.9375,
                "transparent_background": True,
                "container": "QUICKTIME",
                "codec": "QTRLE",
                "colour_mode": "RGBA",
                "output_path": f"output/composition_assets/v23/overlays/{overlay_id}_0001_0719.mov",
                "proof_frames": [1, 120, 400, 600, 719],
            },
        ])
        selection[field["field_id"]] = {
            "background_asset_id": background_id,
            "field_overlay_asset_id": overlay_id,
        }

    assets.append({
        "asset_id": "shared_shelter_overlay_rgba",
        "asset_type": "shelter_overlay",
        "shelter_id": "OSONG-EUP-WELFARE-CENTER",
        "camera_object": SOURCE_CAMERA,
        "view_layer": "V23_SHELTER_RGBA",
        "frame_start": 720,
        "frame_end": 960,
        "frame_count": 241,
        "duration_seconds": 15.0625,
        "transparent_background": True,
        "container": "QUICKTIME",
        "codec": "QTRLE",
        "colour_mode": "RGBA",
        "output_path": "output/composition_assets/v23/overlays/shared_shelter_overlay_rgba_0720_0960.mov",
        "proof_frames": [720, 768, 888, 960],
    })

    return {
        "schema_version": "1.0",
        "status": "planned",
        "scene_pack_id": flood["scene_pack_id"],
        "source_blend": SOURCE_BLEND,
        "resolution": RESOLUTION,
        "fps": FPS,
        "frame_domain": [1, 960],
        "common_background_clip": "output/scene_packs/osong_miho_v23/common_background_v23_60s.mp4",
        "flood_plan": "data/v23/flood_assets/flood_render_plan_v23.json",
        "assets": assets,
        "selection_by_field_id": selection,
        "shared_shelter_overlay_asset_id": "shared_shelter_overlay_rgba",
        "composition_policy": {
            "base_common_background_frames": [1, 960],
            "field_background_replacement_frames": [1, 719],
            "field_overlay_frames": [1, 719],
            "shelter_overlay_frames": [720, 960],
            "flood_segments_from_stage_6": True,
            "trigger_time_blender_3d_render": False,
            "trigger_time_vse_media_composition": True,
        },
        "render_totals": {
            "asset_count": len(assets),
            "background_frames": 719 * 3,
            "field_overlay_frames": 719 * 3,
            "shelter_overlay_frames": 241,
            "total_rendered_frames": sum(item["frame_count"] for item in assets),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Stage 7 V23 composition assets")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    document = build_composition_asset_plan()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "output": str(args.output),
        "asset_count": len(document["assets"]),
        "total_rendered_frames": document["render_totals"]["total_rendered_frames"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
