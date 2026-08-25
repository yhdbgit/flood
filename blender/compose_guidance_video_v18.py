"""Compose the context-specific V18 manifest into a dynamic 60-120 second MP4."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy


ROOT = Path(__file__).resolve().parents[1]


def resolved_path(value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def args_after_separator():
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args(values)


def main():
    args = args_after_separator()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("workflow_version") != "V18" or manifest.get("mode") not in {"production", "staging"}:
        raise RuntimeError("Only a production or staging V18 manifest may be rendered")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "Osong_Guidance_V18"
    scene.render.resolution_x, scene.render.resolution_y = manifest["resolution"]
    scene.render.resolution_percentage = 100
    scene.render.fps = manifest["fps"]
    scene.frame_start = manifest["frame_start"]
    scene.frame_end = manifest["frame_end"]
    editor = scene.sequence_editor_create()
    image_strips = []
    sound_strips = []
    for item in manifest["segments"]:
        duration = item["end_frame"] - item["start_frame"] + 1
        visual = resolved_path(item["visual_path"])
        audio = resolved_path(item["audio_path"])
        if not visual.is_file() or not audio.is_file():
            raise RuntimeError(f"Missing V18 composition asset for {item['id']}")
        image = editor.strips.new_image(
            f"Visual_{item['id']}", str(visual), 1, item["start_frame"], fit_method="FIT"
        )
        image.frame_final_duration = duration
        image_strips.append(image)
        sound = editor.strips.new_sound(f"TTS_{item['id']}", str(audio), 2, item["start_frame"])
        # Every voice strip is forcibly cropped to its assigned segment.
        sound.frame_final_duration = duration
        sound_strips.append(sound)
    scene.render.use_sequencer = True
    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.audio_codec = "AAC"
    scene.render.ffmpeg.audio_bitrate = 192
    scene.render.filepath = str(resolved_path(manifest["output_video"]))
    scene.render.use_file_extension = True
    try:
        scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
        scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    except (AttributeError, TypeError):
        pass
    scene["story_version"] = "V18"
    scene["guidance_run_id"] = manifest["run_id"]
    scene["guidance_context_id"] = manifest["context_id"]
    scene["guidance_context_source_mode"] = manifest["context_source_mode"]
    scene["hydraulic_event_forecast"] = False
    scene["visual_mode"] = manifest["visual_mode"]
    scene["guidance_manifest"] = str(args.manifest)
    scene.frame_set(1)
    output_blend = resolved_path(manifest["output_blend"])
    output_blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend), relative_remap=False)
    bpy.ops.render.render(animation=True)
    video = resolved_path(manifest["output_video"])
    if not video.is_file() or video.stat().st_size < 100_000 or b"ftyp" not in video.read_bytes()[:32]:
        raise RuntimeError("V18 final MP4 render failed")
    report = {
        "status": "ok",
        "scene": scene.name,
        "context_id": manifest["context_id"],
        "image_strips": len(image_strips),
        "sound_strips": len(sound_strips),
        "audio_crop_policy": "forced_to_segment_end_frame",
        "frames": [scene.frame_start, scene.frame_end],
        "fps": scene.render.fps,
        "duration_seconds": scene.frame_end / scene.render.fps,
        "video_path": str(video),
        "video_bytes": video.stat().st_size,
        "blend_path": str(output_blend),
    }
    (args.manifest.parent / "composition_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
