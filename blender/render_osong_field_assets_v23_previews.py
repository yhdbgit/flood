#!/usr/bin/env python3
"""Render compact composite and transparent previews for every V23 field asset."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import perf_counter

import bpy


ROOT = Path(__file__).resolve().parents[1]
BLEND = ROOT / "blender" / "osong_personalization_v23.blend"
MANIFEST_PATH = ROOT / "data" / "v23" / "field_assets" / "field_assets_manifest_v23.json"
OUTPUT_ROOT = ROOT / "output" / "field_assets" / "v23" / "previews"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def render(scene, layer_name: str, frame: int, path: Path, transparent: bool):
    for layer in scene.view_layers:
        layer.use = layer.name == layer_name
    scene.render.film_transparent = transparent
    scene.frame_set(frame)
    scene.render.filepath = str(path)
    started = perf_counter()
    bpy.ops.render.render(write_still=True, layer=layer_name)
    if not path.is_file() or path.stat().st_size < 1000:
        raise RuntimeError(f"Preview render failed: {path}")
    return {
        "view_layer": layer_name,
        "frame": frame,
        "transparent_background": transparent,
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "elapsed_seconds": round(perf_counter() - started, 3),
    }


def main() -> None:
    if Path(bpy.data.filepath).resolve() != BLEND.resolve():
        raise RuntimeError(f"Run this script with {BLEND}")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    scene = bpy.context.scene
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 25
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"

    items = []
    started = perf_counter()
    for asset in manifest["field_assets"]:
        suffix = asset["field_id"][-3:]
        camera = bpy.data.objects.get(asset["camera_object"])
        if camera is None:
            raise RuntimeError(f"Camera missing for {asset['field_id']}")
        scene.camera = camera
        for frame, role in (
            (1, "selected_field_overview_start"),
            (240, "selected_field_first_flood_end"),
            (400, "selected_field_focus"),
            (600, "selected_field_close"),
            (719, "selected_field_zoom_out_end"),
        ):
            items.append(render(
                scene,
                asset["composite_view_layer"],
                frame,
                OUTPUT_ROOT / f"field_{suffix}_composite_{frame:03d}.png",
                False,
            ))
            items[-1]["field_id"] = asset["field_id"]
            items[-1]["preview_role"] = role
        items.append(render(
            scene,
            asset["rgba_view_layer"],
            400,
            OUTPUT_ROOT / f"field_{suffix}_rgba_400.png",
            True,
        ))
        items[-1]["field_id"] = asset["field_id"]
        items[-1]["preview_role"] = "field_overlay_rgba"

    manifest["status"] = "previews_rendered_review_pending"
    manifest["previews"] = {
        "status": "rendered_visual_review_pending",
        "resolution": [320, 180],
        "elapsed_seconds": round(perf_counter() - started, 3),
        "items": items,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest["previews"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
