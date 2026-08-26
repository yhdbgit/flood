#!/usr/bin/env python3
"""Prepare deterministic reusable V23 flood-layer render segments."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
FIELD_MANIFEST = ROOT / "data" / "v23" / "field_assets" / "field_assets_manifest_v23.json"
DEFAULT_OUTPUT = ROOT / "data" / "v23" / "flood_assets" / "flood_render_plan_v23.json"
SCENE_PACK_ID = "OSONG-MIHO-SCENE-PACK-V23"
SOURCE_CAMERA = "Camera_Osong_Shelter_V19"
FPS = 16
RESOLUTION = [1280, 720]


def _segment(
    segment_id: str,
    frame_start: int,
    frame_end: int,
    camera_object: str,
    role: str,
    field_id: str | None = None,
    proof_frames: List[int] | None = None,
    view_layer: str = "V23_FLOOD_RGBA",
) -> Dict[str, Any]:
    frame_count = frame_end - frame_start + 1
    filename = f"{segment_id}_{frame_start:04d}_{frame_end:04d}.mov"
    result: Dict[str, Any] = {
        "segment_id": segment_id,
        "role": role,
        "frame_start": frame_start,
        "frame_end": frame_end,
        "frame_count": frame_count,
        "duration_seconds": round(frame_count / FPS, 4),
        "camera_object": camera_object,
        "view_layer": view_layer,
        "output_path": f"output/flood_assets/v23/clips/{filename}",
        "proof_frames": proof_frames or sorted({frame_start, (frame_start + frame_end) // 2, frame_end}),
    }
    if field_id is not None:
        result["field_id"] = field_id
    return result


def build_flood_render_plan(field_manifest_path: Path = FIELD_MANIFEST) -> Dict[str, Any]:
    manifest = json.loads(field_manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") not in {"built_preview_pending", "previews_rendered_review_pending", "ready"}:
        raise ValueError("V23 field-personalization blend must be rebuilt before flood planning")
    if manifest.get("field_asset_count") != 3:
        raise ValueError("V23 flood plan expects exactly three prepared demo fields")

    segments: List[Dict[str, Any]] = []
    for asset in sorted(manifest["field_assets"], key=lambda item: item["field_id"]):
        suffix = asset["field_id"][-3:]
        segments.append(_segment(
            f"field_{suffix}_focus_flood",
            1,
            719,
            asset["camera_object"],
            "field-specific overview, both flood cycles, focus, and zoom-out transition",
            field_id=asset["field_id"],
            proof_frames=[1, 120, 240, 400, 600, 719],
            view_layer=asset["flood_rgba_view_layer"],
        ))
    segments.append(_segment(
        "shared_shelter_hold",
        720,
        960,
        SOURCE_CAMERA,
        "shared post-flood shelter reveal and hold",
        proof_frames=[720, 840, 960],
    ))

    return {
        "schema_version": "1.0",
        "status": "planned",
        "scene_pack_id": SCENE_PACK_ID,
        "source_blend": "blender/osong_personalization_v23.blend",
        "view_layer": "V23_FLOOD_RGBA",
        "resolution": RESOLUTION,
        "fps": FPS,
        "frame_domain": [1, 960],
        "codec_contract": {
            "container": "QUICKTIME",
            "codec": "QTRLE",
            "colour_mode": "RGBA",
            "alpha_required": True,
            "source_of_truth": "lossless alpha movie plus reviewed RGBA proof frames",
        },
        "segmentation_policy": {
            "shared_camera_intervals_render_once": True,
            "field_camera_interval_render_per_registered_field": True,
            "trigger_time_blender_render": False,
            "reason": "camera projection changes the screen-space flood layer even when flood geometry is shared",
            "frame_boundary_note": "Frames 1-719 are field-specific; only the shelter interval 720-960 is shared.",
        },
        "segments": segments,
        "render_totals": {
            "segment_count": len(segments),
            "shared_frames": 241,
            "field_specific_frames": 719 * 3,
            "total_rendered_frames": sum(item["frame_count"] for item in segments),
            "full_sequence_equivalents": round(sum(item["frame_count"] for item in segments) / 960, 4),
        },
        "selection_contract": {
            "field_segment_by_field_id": {
                item["field_id"]: item["segment_id"]
                for item in segments
                if "field_id" in item
            },
            "ending_segment_id": "shared_shelter_hold",
            "field_segment_covers_opening_and_focus": True,
        },
        "limitations": [
            "The ten flood surfaces are a visual progression within an official hazard extent, not hydraulic time-step output.",
            "This stage pre-renders the caution scenario only; interest, alert, and severe mappings remain pending.",
            "Flood clips contain only RGBA water pixels and must be composited over matching camera background segments.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the V23 reusable flood-layer render plan")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    document = build_flood_render_plan()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "output": str(args.output),
        "segments": len(document["segments"]),
        "total_rendered_frames": document["render_totals"]["total_rendered_frames"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
