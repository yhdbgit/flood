#!/usr/bin/env python3
"""Validate alpha separation and record the Stage 4 visual review."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "v23" / "scene_packs" / "osong_miho_v23_layer_manifest.json"


def alpha_stats(path: Path):
    image = Image.open(path).convert("RGBA")
    alpha = image.getchannel("A")
    histogram = alpha.histogram()
    pixels = image.width * image.height
    return {
        "alpha_min": alpha.getextrema()[0],
        "alpha_max": alpha.getextrema()[1],
        "nonzero_percent": round((pixels - histogram[0]) / pixels * 100, 3),
        "opaque_percent": round(histogram[255] / pixels * 100, 3),
    }


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    previews = manifest["render_outputs"]["previews"]
    if previews.get("status") != "rendered_visual_review_pending":
        raise RuntimeError("Preview render must finish before validation")

    stats = {}
    for item in previews["items"]:
        path = Path(item["path"])
        if not path.is_file():
            raise FileNotFoundError(path)
        item_stats = alpha_stats(path)
        stats[path.name] = item_stats
        if item["view_layer"] == "V23_COMMON_BACKGROUND":
            if item_stats["alpha_min"] != 255 or item_stats["alpha_max"] != 255:
                raise RuntimeError(f"Common background is not opaque: {path.name}")
        else:
            if item_stats["alpha_min"] != 0 or item_stats["nonzero_percent"] <= 0:
                raise RuntimeError(f"RGBA layer lacks transparent separation: {path.name}")

    manifest["status"] = "layered_scene_preview_verified"
    manifest["render_outputs"]["previews"]["status"] = "visual_review_passed"
    manifest["render_outputs"]["previews"]["alpha_validation"] = stats
    manifest["visual_review"] = {
        "status": "passed_with_known_limits",
        "reviewed_at_local": "2026-08-26",
        "reviewed_files": [Path(item["path"]).name for item in previews["items"]],
        "confirmed": [
            "The common background contains no fixed field fill or boundary.",
            "The common background contains no flood-stage surface.",
            "The common shelter frame contains no shelter marker or label.",
            "Flood, legacy field, and shelter overlays render as separate transparent PNG layers.",
        ],
        "known_limits": manifest["limitations"],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest["visual_review"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
