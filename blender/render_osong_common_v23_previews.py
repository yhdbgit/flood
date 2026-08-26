#!/usr/bin/env python3
"""Render small Stage 4 proof frames from the V23 separated view layers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import perf_counter

import bpy


ROOT = Path(__file__).resolve().parents[1]
BLEND = ROOT / "blender" / "osong_common_v23.blend"
OUTPUT_ROOT = ROOT / "output" / "scene_packs" / "osong_miho_v23"
PREVIEW_ROOT = OUTPUT_ROOT / "previews"
REPORT_PATH = ROOT / "data" / "v23" / "scene_packs" / "osong_miho_v23_layer_manifest.json"

PREVIEWS = [
    ("V23_COMMON_BACKGROUND", 1, "common_001_regional.png", False),
    ("V23_COMMON_BACKGROUND", 240, "common_240_no_fixed_field_or_flood.png", False),
    ("V23_COMMON_BACKGROUND", 360, "common_360_field_focus_clean.png", False),
    ("V23_COMMON_BACKGROUND", 600, "common_600_field_focus_clean.png", False),
    ("V23_COMMON_BACKGROUND", 960, "common_960_shelter_without_marker.png", False),
    ("V23_FLOOD_RGBA", 240, "flood_rgba_240.png", True),
    ("V23_FLOOD_RGBA", 600, "flood_rgba_600.png", True),
    ("V23_FIELD_TEMPLATE_RGBA", 360, "legacy_field_template_rgba_360.png", True),
    ("V23_SHELTER_RGBA", 960, "shelter_overlay_rgba_960.png", True),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    if Path(bpy.data.filepath).resolve() != BLEND.resolve():
        raise RuntimeError(f"Run this script with {BLEND}")
    scene = bpy.context.scene
    PREVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 50
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"

    results = []
    started = perf_counter()
    for layer_name, frame, filename, transparent in PREVIEWS:
        for layer in scene.view_layers:
            layer.use = layer.name == layer_name
        scene.render.film_transparent = transparent
        scene.frame_set(frame)
        path = PREVIEW_ROOT / filename
        scene.render.filepath = str(path)
        item_started = perf_counter()
        bpy.ops.render.render(write_still=True, layer=layer_name)
        results.append({
            "view_layer": layer_name,
            "frame": frame,
            "transparent_background": transparent,
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "elapsed_seconds": round(perf_counter() - item_started, 3),
        })

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    report["status"] = "layered_scene_previews_rendered"
    report["render_outputs"]["previews"] = {
        "status": "rendered_visual_review_pending",
        "resolution": [640, 360],
        "elapsed_seconds": round(perf_counter() - started, 3),
        "items": results,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["render_outputs"]["previews"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
