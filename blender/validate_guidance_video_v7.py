"""Validate the saved V7 VSE project and final guidance MP4."""

import json
from pathlib import Path

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
OUT = ROOT / "output" / "guidance_v7"
MANIFEST_PATH = OUT / "guidance_manifest.json"
VIDEO_PATH = OUT / "gangnae_guidance_v7.mp4"
REPORT_PATH = OUT / "saved_blend_validation.json"

manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
scene = bpy.context.scene
editor = scene.sequence_editor
failures = []
strips = list(editor.strips_all) if editor else []
type_counts = {}
for strip in strips:
    type_counts[strip.type] = type_counts.get(strip.type, 0) + 1
if not editor:
    failures.append("sequence editor is missing")
if type_counts.get("SOUND", 0) != len(manifest["segments"]):
    failures.append(f"sound strip count invalid: {type_counts}")
if type_counts.get("IMAGE", 0) < 6:
    failures.append(f"image strip count invalid: {type_counts}")
if type_counts.get("MOVIE", 0) < 3:
    failures.append(f"digital-twin repeats missing: {type_counts}")
bad_scales = {strip.name: [strip.transform.scale_x, strip.transform.scale_y] for strip in strips if strip.type in {"IMAGE", "MOVIE"} and (abs(strip.transform.scale_x - 1.0) > 0.001 or abs(strip.transform.scale_y - 1.0) > 0.001)}
if bad_scales:
    failures.append(f"visual strip scale invalid: {bad_scales}")
if (scene.frame_start, scene.frame_end, scene.render.fps) != (1, manifest["frame_end"], 24):
    failures.append("timeline settings invalid")
if scene.render.image_settings.media_type != "VIDEO" or scene.render.image_settings.file_format != "FFMPEG":
    failures.append("video media settings invalid")
if scene.render.ffmpeg.format != "MPEG4" or scene.render.ffmpeg.codec != "H264" or scene.render.ffmpeg.audio_codec != "AAC":
    failures.append("video/audio codec settings invalid")
video_bytes = VIDEO_PATH.stat().st_size if VIDEO_PATH.is_file() else 0
if video_bytes < 100_000 or (video_bytes and b"ftyp" not in VIDEO_PATH.read_bytes()[:32]):
    failures.append(f"final video invalid: {video_bytes}")
if scene.get("guidance_mode") != "mvp_demo_not_live_forecast":
    failures.append("demo mode label is missing")

text_dump = "\n".join(str(value) for value in [scene.name, *[scene.get(key) for key in scene.keys()]])
api_key_markers = [marker for marker in ("1FB4A0FE", "HRFCO_API_KEY") if marker in text_dump]
if api_key_markers:
    failures.append(f"API key marker found: {api_key_markers}")

report = {
    "status": "failed" if failures else "ok",
    "scene": scene.name,
    "strip_type_counts": type_counts,
    "frames": [scene.frame_start, scene.frame_end],
    "fps": scene.render.fps,
    "duration_seconds": manifest["duration_seconds"],
    "video_bytes": video_bytes,
    "api_key_markers": api_key_markers,
    "failures": failures,
}
REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if failures:
    raise RuntimeError("; ".join(failures))
