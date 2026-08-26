#!/usr/bin/env python3
"""Render the V23 clean common background once for trigger-time reuse."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import perf_counter

import bpy


ROOT = Path(__file__).resolve().parents[1]
BLEND = ROOT / "blender" / "osong_common_v23.blend"
OUTPUT_ROOT = ROOT / "output" / "scene_packs" / "osong_miho_v23"
VIDEO = OUTPUT_ROOT / "common_background_v23_60s.mp4"
MANIFEST = ROOT / "data" / "v23" / "scene_packs" / "osong_miho_v23_layer_manifest.json"
FPS = 16
FRAME_END = 960


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    if Path(bpy.data.filepath).resolve() != BLEND.resolve():
        raise RuntimeError(f"Run this script with {BLEND}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("status") != "layered_scene_preview_verified":
        raise RuntimeError("Stage 4 preview review must pass before the full common render")
    if manifest.get("blend_sha256") != sha256(BLEND):
        raise RuntimeError("V23 blend differs from the reviewed layered scene")

    scene = bpy.context.scene
    for layer in scene.view_layers:
        layer.use = layer.name == "V23_COMMON_BACKGROUND"
    if not scene.view_layers["V23_COMMON_BACKGROUND"].use:
        raise RuntimeError("Common background view layer is not enabled")
    scene.render.engine = "BLENDER_EEVEE"
    scene.frame_start = 1
    scene.frame_end = FRAME_END
    scene.render.fps = FPS
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.filepath = str(VIDEO)
    scene.render.use_file_extension = True
    try:
        scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
        scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    except (AttributeError, TypeError):
        pass

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    VIDEO.unlink(missing_ok=True)
    started = perf_counter()
    bpy.ops.render.render(animation=True)
    elapsed = round(perf_counter() - started, 3)
    if not VIDEO.is_file() or VIDEO.stat().st_size < 100_000 or b"ftyp" not in VIDEO.read_bytes()[:32]:
        raise RuntimeError("V23 common background MP4 render failed")

    manifest["status"] = "common_background_rendered"
    manifest["render_outputs"]["common_background_clip"] = {
        "status": "rendered_reuse_only",
        "path": str(VIDEO),
        "bytes": VIDEO.stat().st_size,
        "sha256": sha256(VIDEO),
        "resolution": [1280, 720],
        "fps": FPS,
        "frames": [1, FRAME_END],
        "duration_seconds": FRAME_END / FPS,
        "render_elapsed_seconds": elapsed,
        "view_layer": "V23_COMMON_BACKGROUND",
        "reuse_policy": "render_once_never_rerender_at_trigger_time",
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest["render_outputs"]["common_background_clip"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
