#!/usr/bin/env python3
"""Audit Stage 7 cached media through Blender's movie decoder."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "data" / "v23" / "composition_assets" / "composition_asset_plan_v23.json"
MANIFEST_PATH = ROOT / "data" / "v23" / "composition_assets" / "composition_assets_manifest_v23.json"
AUDIT_PATH = ROOT / "data" / "v23" / "composition_assets" / "composition_movie_audit_v23.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    rendered = {item["asset_id"]: item for item in manifest.get("assets", [])}
    items = []
    failures = []
    for expected in plan["assets"]:
        asset_id = expected["asset_id"]
        actual = rendered.get(asset_id)
        if actual is None:
            failures.append(f"missing manifest asset: {asset_id}")
            continue
        path = ROOT / expected["output_path"]
        if not path.is_file():
            failures.append(f"missing movie: {path}")
            continue
        clip = bpy.data.movieclips.load(str(path), check_existing=False)
        image = bpy.data.images.load(str(path), check_existing=False)
        checks = {
            "resolution": list(image.size) == plan["resolution"],
            "frame_duration": int(clip.frame_duration) == expected["frame_count"],
            "image_source": image.source == "MOVIE",
            "movie_source": clip.source == "MOVIE",
            "manifest_hash": sha256(path) == actual["sha256"],
            "manifest_bytes": path.stat().st_size == actual["bytes"],
        }
        if expected["transparent_background"]:
            checks["rgba_channels"] = int(image.channels) == 4
            checks["straight_alpha"] = image.alpha_mode == "STRAIGHT"
        item = {
            "asset_id": asset_id,
            "asset_type": expected["asset_type"],
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "resolution": list(image.size),
            "frame_duration": int(clip.frame_duration),
            "channels": int(image.channels),
            "alpha_mode": image.alpha_mode,
            "transparent_background": expected["transparent_background"],
            "checks": checks,
            "valid": all(checks.values()),
        }
        if not item["valid"]:
            failures.append(f"movie audit failed: {asset_id}")
        items.append(item)
        bpy.data.movieclips.remove(clip)
        bpy.data.images.remove(image)
    result = {
        "schema_version": "1.0",
        "status": "passed" if not failures and len(items) == len(plan["assets"]) else "failed",
        "scene_pack_id": plan["scene_pack_id"],
        "asset_count": len(items),
        "items": items,
        "failures": failures,
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "passed":
        raise RuntimeError("Stage 7 composition movie audit failed")


if __name__ == "__main__":
    main()
