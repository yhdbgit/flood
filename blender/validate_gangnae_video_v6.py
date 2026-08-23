"""Validate the saved V6 scene and rendered MP4 in a fresh Blender process."""

import json
from pathlib import Path

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
VIDEO_PATH = ROOT / "output" / "gangnae_flood_mvp_v6.mp4"
POSTER_PATH = ROOT / "output" / "gangnae_flood_mvp_v6_poster.png"
REPORT_PATH = ROOT / "output" / "video_v6_saved_blend_check.json"

failures = []
scene = bpy.context.scene
collection = bpy.data.collections.get("DT_VIDEO_V6")
objects = list(collection.objects) if collection else []
if collection is None:
    failures.append("DT_VIDEO_V6 collection is missing")

required = [
    "HUD_TitlePanel_V6",
    "HUD_StatusPanel_V6",
    "HUD_Title_V6",
    "HUD_Disclaimer_V6",
    "HUD_Status_normal_V6",
    "HUD_Status_attention_V6",
    "HUD_Status_warning_V6",
    "HUD_Status_serious_V6",
]
missing = [name for name in required if bpy.data.objects.get(name) is None]
if missing:
    failures.append(f"missing video overlays: {missing}")

visibility = {}
for code, frame in (("normal", 1), ("attention", 30), ("warning", 65), ("serious", 100)):
    scene.frame_set(frame)
    status = {
        item: not bpy.data.objects[f"HUD_Status_{item}_V6"].hide_render
        for item in ("normal", "attention", "warning", "serious")
        if bpy.data.objects.get(f"HUD_Status_{item}_V6")
    }
    visibility[code] = status
    if status.get(code) is not True or sum(status.values()) != 1:
        failures.append(f"status visibility invalid at frame {frame}: {status}")

if scene.render.image_settings.media_type != "VIDEO":
    failures.append(f"render media type invalid: {scene.render.image_settings.media_type}")
if scene.render.image_settings.file_format != "FFMPEG":
    failures.append(f"render file format invalid: {scene.render.image_settings.file_format}")
if scene.render.ffmpeg.format != "MPEG4":
    failures.append(f"container invalid: {scene.render.ffmpeg.format}")
if scene.render.ffmpeg.codec != "H264":
    failures.append(f"codec invalid: {scene.render.ffmpeg.codec}")
if (scene.render.resolution_x, scene.render.resolution_y) != (960, 540):
    failures.append(f"resolution invalid: {scene.render.resolution_x}x{scene.render.resolution_y}")
if (scene.frame_start, scene.frame_end, scene.render.fps) != (1, 120, 24):
    failures.append("timeline settings invalid")

video_bytes = VIDEO_PATH.stat().st_size if VIDEO_PATH.is_file() else 0
poster_bytes = POSTER_PATH.stat().st_size if POSTER_PATH.is_file() else 0
if video_bytes < 100_000:
    failures.append(f"video missing or too small: {video_bytes}")
elif b"ftyp" not in VIDEO_PATH.read_bytes()[:32]:
    failures.append("video MP4 header is invalid")
if poster_bytes == 0:
    failures.append("poster is missing")

text_dump = "\n".join(str(value) for obj in objects for value in [obj.name, *[obj.get(key) for key in obj.keys()]])
api_key_markers = [marker for marker in ("1FB4A0FE", "HRFCO_API_KEY") if marker in text_dump]
if api_key_markers:
    failures.append(f"API key marker found: {api_key_markers}")

report = {
    "status": "failed" if failures else "ok",
    "scene": scene.name,
    "overlay_count": len(objects),
    "missing_overlays": missing,
    "status_visibility": visibility,
    "render_settings": {
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "fps": scene.render.fps,
        "frames": [scene.frame_start, scene.frame_end],
        "container": scene.render.ffmpeg.format,
        "codec": scene.render.ffmpeg.codec,
    },
    "video_bytes": video_bytes,
    "poster_bytes": poster_bytes,
    "api_key_markers": api_key_markers,
    "failures": failures,
}
REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if failures:
    raise RuntimeError("; ".join(failures))
