#!/usr/bin/env python3
"""Compose cached V23 media strips into a personalized visual MP4."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

import bpy


ROOT = Path(__file__).resolve().parents[1]


def resolved_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def parse_args() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Compose a V23 personalized visual")
    parser.add_argument("--plan", type=Path, required=True)
    return parser.parse_args(values)


def main() -> None:
    args = parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if plan.get("workflow_version") != "V23-STAGE-7":
        raise RuntimeError("Unsupported V23 composition plan")
    policy = plan.get("render_policy", {})
    if policy.get("blender_3d_scene_render") is not False or policy.get("vse_cached_media_composition") is not True:
        raise RuntimeError("Stage 7 requires cached-media-only VSE composition")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "V23_Personalized_Visual_Composition"
    scene.render.resolution_x, scene.render.resolution_y = plan["resolution"]
    scene.render.resolution_percentage = 100
    scene.render.fps = int(plan["fps"])
    scene.frame_start = int(plan["frame_start"])
    scene.frame_end = int(plan["frame_end"])
    editor = scene.sequence_editor_create()
    strip_report = []
    for item in plan["strips"]:
        path = resolved_path(item["path"])
        if not path.is_file():
            raise RuntimeError(f"Missing cached composition asset: {path}")
        strip = editor.strips.new_movie(
            item["strip_id"], str(path), int(item["channel"]), int(item["timeline_start"]), fit_method="FIT"
        )
        strip.frame_final_duration = int(item["duration_frames"])
        if item.get("alpha_over"):
            strip.blend_type = "ALPHA_OVER"
        strip_report.append({
            "strip_id": item["strip_id"],
            "role": item["role"],
            "channel": item["channel"],
            "frame_start": strip.frame_final_start,
            "frame_end": strip.frame_final_end - 1,
            "duration_frames": strip.frame_final_duration,
            "source_path": str(path),
            "blend_type": strip.blend_type,
        })

    scene.render.use_sequencer = True
    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.audio_codec = "NONE"
    try:
        scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
        scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    except (AttributeError, TypeError):
        pass
    video = resolved_path(plan["output_video"])
    blend = resolved_path(plan["output_blend"])
    report_path = resolved_path(plan["composition_report"])
    video.parent.mkdir(parents=True, exist_ok=True)
    video.unlink(missing_ok=True)
    scene.render.filepath = str(video)
    scene.render.use_file_extension = True
    scene["v23_event_id"] = plan["event_id"]
    scene["v23_field_id"] = plan["field_id"]
    scene["v23_scenario_id"] = plan["scenario_id"]
    scene["v23_blender_3d_scene_render"] = False
    scene["v23_cached_media_only"] = True
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), relative_remap=False)
    started = perf_counter()
    bpy.ops.render.render(animation=True)
    elapsed = round(perf_counter() - started, 3)
    if not video.is_file() or video.stat().st_size < 100_000 or b"ftyp" not in video.read_bytes()[:64]:
        raise RuntimeError("V23 personalized visual composition failed")
    report = {
        "schema_version": "1.0",
        "status": "ok",
        "workflow_version": plan["workflow_version"],
        "event_id": plan["event_id"],
        "field_id": plan["field_id"],
        "scenario_id": plan["scenario_id"],
        "frames": [scene.frame_start, scene.frame_end],
        "fps": scene.render.fps,
        "duration_seconds": plan["duration_seconds"],
        "strip_count": len(strip_report),
        "strips": strip_report,
        "blender_3d_scene_render": False,
        "cached_media_only": True,
        "composition_elapsed_seconds": elapsed,
        "video_path": str(video),
        "video_bytes": video.stat().st_size,
        "blend_path": str(blend),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
