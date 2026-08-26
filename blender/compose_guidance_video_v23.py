"""Compose a V23 personalized visual, parallel TTS, and information cards."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy


ROOT = Path(__file__).resolve().parents[1]


def resolved_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def parse_args() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args(values)


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("workflow_version") != "V23" or manifest.get("mode") not in {"production", "staging"}:
        raise RuntimeError("Only a production or staging V23 manifest may be rendered")
    if manifest.get("base_render_policy") != "cached_personalized_visual_reuse_no_3d_rerender":
        raise RuntimeError("V23 final composition requires the cached personalized visual policy")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "Osong_Guidance_V23"
    scene.render.resolution_x, scene.render.resolution_y = manifest["resolution"]
    scene.render.resolution_percentage = 100
    scene.render.fps = int(manifest["fps"])
    scene.frame_start = int(manifest["frame_start"])
    scene.frame_end = int(manifest["frame_end"])
    editor = scene.sequence_editor_create()
    base_path = resolved_path(manifest["personalized_visual"]["video"])
    if not base_path.is_file():
        raise RuntimeError("V23 personalized visual is missing")
    movie = editor.strips.new_movie("V23_Personalized_Visual", str(base_path), 1, 1, fit_method="FIT")
    movie.frame_final_duration = int(manifest["personalized_visual_end_frame"])
    image_count = 0
    sound_count = 0
    for item in manifest["segments"]:
        duration = int(item["end_frame"] - item["start_frame"] + 1)
        if item["visual_type"] == "information_card":
            visual = resolved_path(item["visual_path"])
            if not visual.is_file():
                raise RuntimeError(f"Missing information card: {item['id']}")
            image = editor.strips.new_image(f"Visual_{item['id']}", str(visual), 1, int(item["start_frame"]), fit_method="FIT")
            image.frame_final_duration = duration
            image_count += 1
        audio = resolved_path(item["audio_path"])
        if not audio.is_file():
            raise RuntimeError(f"Missing TTS asset: {item['id']}")
        sound = editor.strips.new_sound(f"TTS_{item['id']}", str(audio), 2, int(item["start_frame"]))
        sound.frame_final_duration = duration
        sound_count += 1
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
    scene["story_version"] = "V23"
    scene["event_id"] = manifest["event_id"]
    scene["field_id"] = manifest["field_id"]
    scene["user_id"] = manifest["user_id"]
    scene["full_3d_rerender"] = False
    scene["guidance_manifest"] = str(args.manifest)
    output_blend = resolved_path(manifest["output_blend"])
    output_blend.parent.mkdir(parents=True, exist_ok=True)
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend), relative_remap=False)
    bpy.ops.render.render(animation=True)
    video = resolved_path(manifest["output_video"])
    if not video.is_file() or video.stat().st_size < 100_000 or b"ftyp" not in video.read_bytes()[:32]:
        raise RuntimeError("V23 final MP4 render failed")
    report = {
        "status": "ok",
        "event_id": manifest["event_id"],
        "field_id": manifest["field_id"],
        "base_video": str(base_path),
        "base_rerendered": False,
        "image_strips": image_count,
        "sound_strips": sound_count,
        "audio_crop_policy": "forced_to_segment_end_frame",
        "frames": [scene.frame_start, scene.frame_end],
        "fps": scene.render.fps,
        "duration_seconds": scene.frame_end / scene.render.fps,
        "video_path": str(video),
        "video_bytes": video.stat().st_size,
        "blend_path": str(output_blend),
    }
    (args.manifest.parent / "composition_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
