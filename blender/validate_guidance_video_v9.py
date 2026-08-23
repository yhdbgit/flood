"""Validate the saved V9 60-second VSE project and final MP4."""

import json
from pathlib import Path
import bpy

ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
OUT = ROOT / "output" / "guidance_v9"
MANIFEST_PATH = OUT / "guidance_manifest.json"
VIDEO_PATH = OUT / "gangnae_guidance_v9_60s.mp4"
REPORT_PATH = OUT / "saved_blend_validation.json"
manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
scene = bpy.context.scene
editor = scene.sequence_editor
failures = []
strips = list(editor.strips_all) if editor else []
type_counts = {}
for strip in strips:
    type_counts[strip.type] = type_counts.get(strip.type, 0) + 1
if scene.name != "Gangnae_Guidance_V9": failures.append(f"scene invalid: {scene.name}")
if type_counts.get("MOVIE", 0) != 1: failures.append(f"movie count invalid: {type_counts}")
if type_counts.get("IMAGE", 0) != 7: failures.append(f"image count invalid: {type_counts}")
if type_counts.get("SOUND", 0) != 7: failures.append(f"sound count invalid: {type_counts}")
if (scene.frame_start, scene.frame_end, scene.render.fps) != (1, 1440, 24): failures.append("timeline invalid")
if scene.get("flood_playback_speed") != 0.5: failures.append("flood speed metadata invalid")
if not scene.get("ai_voice_disclosure"): failures.append("AI voice disclosure missing")
if scene.render.ffmpeg.codec != "H264" or scene.render.ffmpeg.audio_codec != "AAC": failures.append("codec invalid")
video_bytes = VIDEO_PATH.stat().st_size if VIDEO_PATH.is_file() else 0
if video_bytes < 100_000 or (video_bytes and b"ftyp" not in VIDEO_PATH.read_bytes()[:32]): failures.append("video invalid")
text_dump = "\n".join(str(value) for value in [scene.name, *[scene.get(key) for key in scene.keys()]])
markers = [value for value in ("OPENAI_API_KEY", "HRFCO_API_KEY", "sk-", "1FB4A0FE") if value in text_dump]
if markers: failures.append(f"secret markers found: {markers}")
report = {
    "status": "failed" if failures else "ok",
    "scene": scene.name,
    "strip_type_counts": type_counts,
    "frames": [scene.frame_start, scene.frame_end],
    "fps": scene.render.fps,
    "duration_seconds": scene.frame_end / scene.render.fps,
    "video_bytes": video_bytes,
    "secret_markers": markers,
    "failures": failures,
}
REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if failures: raise RuntimeError("; ".join(failures))
