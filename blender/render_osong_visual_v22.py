"""Render the approved V22 dynamic silent base once for later agent reuse."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
OUTPUT_DIR = ROOT / "output" / "visual_v22"
VIDEO_PATH = OUTPUT_DIR / "osong_visual_v22_60s.mp4"
REPORT_PATH = OUTPUT_DIR / "scene_report.json"
MANIFEST_PATH = ROOT / "data" / "processed" / "osong_visual_v22_manifest.json"
FPS = 16
FRAME_END = 960


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_scene(scene) -> None:
    if scene.name != "Osong_Visual_V22":
        raise RuntimeError(f"Unexpected V22 scene: {scene.name}")
    if scene.camera is None or scene.camera.name != "Camera_Osong_Shelter_V19":
        raise RuntimeError("Approved V22 animated camera is missing")
    if bpy.data.objects.get("RiverSurface_Miho_V21_Continuous") is None:
        raise RuntimeError("Approved continuous Miho River is missing")
    flood = [obj for obj in bpy.data.objects if obj.name.startswith("FloodWaterV21_Step_")]
    if len(flood) != 10:
        raise RuntimeError(f"Expected 10 V21 flood stages in V22, got {len(flood)}")
    collection = bpy.data.collections.get("V22_FIELD_IMAGE_PROXY_STRUCTURES")
    proxies = [] if collection is None else [obj for obj in collection.all_objects if obj.type == "MESH"]
    if len(proxies) != 79:
        raise RuntimeError(f"Expected 79 V22 field visual proxies, got {len(proxies)}")
    if int(scene.get("v22_shelter_actual_osm_building_count", 0)) != 19:
        raise RuntimeError("Expected 19 shelter OSM buildings")
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    review = report.get("visual_review", {})
    if review.get("status") != "passed_with_limitations":
        raise RuntimeError("V22 visual review has not passed")
    if not review.get("final_mp4_approved"):
        raise RuntimeError("V22 final MP4 has not been approved")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    validate_scene(scene)
    VIDEO_PATH.unlink(missing_ok=True)
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
        raise RuntimeError("V22 silent base MP4 render failed")
    if b"ftyp" not in VIDEO_PATH.read_bytes()[:32]:
        raise RuntimeError("V22 MP4 container signature is invalid")
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    report.update({
        "status": "approved_silent_base_rendered",
        "video_path": str(VIDEO_PATH),
        "video_bytes": VIDEO_PATH.stat().st_size,
        "video_sha256": sha256(VIDEO_PATH),
        "video_resolution": [1280, 720],
        "video_fps": FPS,
        "video_duration_seconds": FRAME_END / FPS,
        "render_elapsed_seconds": elapsed,
        "video_rendered": True,
        "reuse_policy": "render_once_and_reuse_for_all_v22_guidance_compositions",
    })
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["status"] = "approved_silent_base_rendered"
    manifest["visual_review"]["final_mp4_approved"] = True
    manifest["video_output"] = {
        "path": str(VIDEO_PATH),
        "bytes": VIDEO_PATH.stat().st_size,
        "sha256": report["video_sha256"],
        "resolution": [1280, 720],
        "fps": FPS,
        "duration_seconds": FRAME_END / FPS,
        "render_elapsed_seconds": elapsed,
        "silent_base_video": True,
        "reuse_policy": report["reuse_policy"],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
