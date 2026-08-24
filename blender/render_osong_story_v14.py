"""Render V14 key-frame previews or the already integrated base animation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
OUT = ROOT / "output" / "guidance_v14"
PREVIEW_DIR = OUT / "previews"
REPORT_PATH = OUT / "base_render_report.json"
PREVIEW_REPORT_PATH = OUT / "preview_report.json"
BASE_VIDEO = OUT / "osong_story_v14_base.mp4"
FRAMES = [1, 240, 480, 576, 816, 1056, 1128]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_previews(scene):
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    outputs = []
    started = time.time()
    for frame in FRAMES:
        scene.frame_set(frame)
        path = PREVIEW_DIR / f"frame_{frame:04d}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        if not path.is_file() or path.stat().st_size < 10_000:
            raise RuntimeError(f"Preview render failed: {path}")
        outputs.append({
            "frame": frame,
            "seconds": round(frame / scene.render.fps, 3),
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    report = {
        "status": "rendered_pending_visual_review",
        "frames": FRAMES,
        "outputs": outputs,
        "elapsed_seconds": round(time.time() - started, 3),
    }
    PREVIEW_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def render_video(scene):
    OUT.mkdir(parents=True, exist_ok=True)
    scene.frame_start = 1
    scene.frame_end = 1128
    scene.render.fps = 24
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.filepath = str(BASE_VIDEO)
    scene.render.use_file_extension = True
    try:
        scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
        scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    except (AttributeError, TypeError):
        pass
    started = time.time()
    bpy.ops.render.render(animation=True)
    elapsed = round(time.time() - started, 3)
    if not BASE_VIDEO.is_file() or BASE_VIDEO.stat().st_size < 100_000:
        raise RuntimeError("V14 base MP4 render failed")
    if b"ftyp" not in BASE_VIDEO.read_bytes()[:32]:
        raise RuntimeError("V14 base MP4 container is invalid")
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.is_file() else {}
    report.update({
        "status": "ok",
        "base_video": str(BASE_VIDEO),
        "base_video_bytes": BASE_VIDEO.stat().st_size,
        "base_video_sha256": sha256(BASE_VIDEO),
        "render_elapsed_seconds": elapsed,
        "preview_validation": "passed_before_video_render",
        "video_rendered": True,
    })
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--previews", action="store_true")
    parser.add_argument("--video", action="store_true")
    args, _unknown = parser.parse_known_args()
    args.previews = args.previews or "--previews" in sys.argv
    args.video = args.video or "--video" in sys.argv
    if args.previews == args.video:
        raise RuntimeError("Choose exactly one of --previews or --video")
    scene = bpy.context.scene
    if scene.name != "Osong_Official_Story_V14_Base":
        raise RuntimeError(f"Unexpected scene: {scene.name}")
    if bpy.data.objects.get("Camera_Osong_Story_V14") is None:
        raise RuntimeError("V14 story camera is missing")
    if args.previews:
        render_previews(scene)
    else:
        render_video(scene)


if __name__ == "__main__":
    main()
