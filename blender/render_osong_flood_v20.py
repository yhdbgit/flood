"""Render the visually approved V20 flood and shelter camera animation once."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
OUTPUT_DIR = ROOT / "output" / "flood_v20"
VIDEO_PATH = OUTPUT_DIR / "osong_flood_camera_v20.mp4"
REPORT_PATH = OUTPUT_DIR / "scene_report.json"
MANIFEST_PATH = ROOT / "data" / "processed" / "osong_flood_v20_manifest.json"
BLEND_PATH = ROOT / "blender" / "osong_flood_v20.blend"
FPS = 24
FRAME_END = 960


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_scene(scene) -> None:
    if scene.name != "Osong_Flood_V20":
        raise RuntimeError(f"Unexpected scene: {scene.name}")
    if scene.camera is None or scene.camera.name != "Camera_Osong_Shelter_V19":
        raise RuntimeError("V20 animated camera is missing or inactive")
    if bpy.data.objects.get("RiverSurface_Osong_V20_Continuous") is None:
        raise RuntimeError("V20 continuous river is missing")
    stages = [obj for obj in bpy.data.objects if obj.name.startswith("FloodWaterV20_Step_")]
    if len(stages) != 10:
        raise RuntimeError(f"Expected 10 V20 flood stages, got {len(stages)}")
    hazard_named = [obj.name for obj in bpy.data.objects if "hazard" in obj.name.lower()]
    if hazard_named:
        raise RuntimeError(f"Hazard-map colour overlay objects must stay hidden: {hazard_named}")
    if bool(scene.get("v20_hydraulic_time_series")):
        raise RuntimeError("V20 must not claim a hydraulic time series")
    if bool(scene.get("v20_hazard_map_overlay_visible")):
        raise RuntimeError("V20 hazard-map class overlay must remain disabled")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    validate_scene(scene)

    scene.frame_start = 1
    scene.frame_end = FRAME_END
    scene.render.fps = FPS
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
        raise RuntimeError("V20 MP4 render failed")
    if b"ftyp" not in VIDEO_PATH.read_bytes()[:32]:
        raise RuntimeError("V20 MP4 container signature is invalid")

    scene["v20_video_rendered"] = True
    scene["v20_video_path"] = str(VIDEO_PATH)
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    report.update({
        "status": "ok",
        "blend_bytes": BLEND_PATH.stat().st_size,
        "blend_sha256": sha256(BLEND_PATH),
        "video_path": str(VIDEO_PATH),
        "video_bytes": VIDEO_PATH.stat().st_size,
        "video_sha256": sha256(VIDEO_PATH),
        "video_resolution": [1280, 720],
        "video_fps": FPS,
        "video_duration_seconds": FRAME_END / FPS,
        "render_elapsed_seconds": elapsed,
        "preview_validation": "passed_before_video_render",
        "visual_review": "passed",
        "video_rendered": True,
    })
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["status"] = "v20_silent_base_video_rendered"
    manifest["blender_scene"].update({
        "bytes": BLEND_PATH.stat().st_size,
        "sha256": report["blend_sha256"],
        "video_rendered": True,
    })
    manifest["video_output"] = {
        "path": str(VIDEO_PATH),
        "bytes": VIDEO_PATH.stat().st_size,
        "sha256": report["video_sha256"],
        "resolution": [1280, 720],
        "fps": FPS,
        "duration_seconds": FRAME_END / FPS,
        "render_elapsed_seconds": elapsed,
        "silent_base_video": True,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
