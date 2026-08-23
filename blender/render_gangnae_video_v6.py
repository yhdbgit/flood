"""Render the configured V6 scene to an MP4 using Blender's bundled FFmpeg."""

import json
from pathlib import Path
import time

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
VIDEO_PATH = ROOT / "output" / "gangnae_flood_mvp_v6.mp4"
REPORT_PATH = ROOT / "output" / "video_v6_render_report.json"

scene = bpy.context.scene
started = time.time()
if scene.render.image_settings.file_format != "FFMPEG":
    raise RuntimeError(f"Expected FFMPEG, got {scene.render.image_settings.file_format}")
if scene.render.ffmpeg.format != "MPEG4":
    raise RuntimeError(f"Expected MPEG4, got {scene.render.ffmpeg.format}")
scene.render.filepath = str(VIDEO_PATH)
bpy.ops.render.render(animation=True)
elapsed = round(time.time() - started, 3)
if not VIDEO_PATH.is_file() or VIDEO_PATH.stat().st_size < 100_000:
    raise RuntimeError(f"MP4 render failed or is too small: {VIDEO_PATH}")
header = VIDEO_PATH.read_bytes()[:32]
if b"ftyp" not in header:
    raise RuntimeError("Rendered output does not have an MP4 ftyp header")
report = {
    "status": "ok",
    "video_path": str(VIDEO_PATH),
    "video_bytes": VIDEO_PATH.stat().st_size,
    "frame_start": scene.frame_start,
    "frame_end": scene.frame_end,
    "fps": scene.render.fps,
    "duration_seconds": round((scene.frame_end - scene.frame_start + 1) / scene.render.fps, 3),
    "resolution": [scene.render.resolution_x, scene.render.resolution_y],
    "ffmpeg_format": scene.render.ffmpeg.format,
    "ffmpeg_codec": scene.render.ffmpeg.codec,
    "render_elapsed_seconds": elapsed,
}
REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("[video-v6] render complete")
print(json.dumps(report, ensure_ascii=False, indent=2))
