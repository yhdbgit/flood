"""Render the visually approved V19 shelter camera animation exactly once."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import bpy

ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
OUTPUT_DIR = ROOT / "output" / "shelter_v19"
VIDEO_PATH = OUTPUT_DIR / "osong_shelter_camera_v19.mp4"
REPORT_PATH = OUTPUT_DIR / "scene_report.json"
MANIFEST_PATH = ROOT / "data" / "processed" / "osong_shelter_v19_manifest.json"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    scene = bpy.context.scene
    if scene.name != "Osong_Shelter_V19":
        raise RuntimeError(f"Unexpected scene: {scene.name}")
    if bpy.data.objects.get("Camera_Osong_Shelter_V19") is None:
        raise RuntimeError("V19 animated camera is missing")
    if bool(scene.get("v19_flood_animation_included")):
        raise RuntimeError("This shelter-only stage must not contain flood animation")

    scene.frame_start = 1
    scene.frame_end = 528
    scene.render.fps = 24
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.filepath = str(VIDEO_PATH)
    scene.render.use_file_extension = True
    try:
        scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
        scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    except (AttributeError, TypeError):
        pass

    started = time.time()
    bpy.ops.render.render(animation=True)
    elapsed = round(time.time() - started, 3)
    if not VIDEO_PATH.is_file() or VIDEO_PATH.stat().st_size < 100_000:
        raise RuntimeError("V19 MP4 render failed")
    if b"ftyp" not in VIDEO_PATH.read_bytes()[:32]:
        raise RuntimeError("V19 MP4 container signature is invalid")

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    report.update({
        "status": "ok",
        "video_path": str(VIDEO_PATH),
        "video_bytes": VIDEO_PATH.stat().st_size,
        "video_sha256": sha256(VIDEO_PATH),
        "video_resolution": [1280, 720],
        "video_fps": 24,
        "video_duration_seconds": 22.0,
        "render_elapsed_seconds": elapsed,
        "preview_validation": "passed_before_video_render",
        "video_rendered": True,
    })
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["video_output"] = {
        "path": str(VIDEO_PATH),
        "bytes": VIDEO_PATH.stat().st_size,
        "sha256": report["video_sha256"],
        "resolution": [1280, 720],
        "fps": 24,
        "duration_seconds": 22.0,
        "render_elapsed_seconds": elapsed,
    }
    manifest["status"] = "shelter_camera_video_rendered"
    manifest["blender_scene"]["video_rendered"] = True
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
