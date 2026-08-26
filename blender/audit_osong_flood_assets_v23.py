#!/usr/bin/env python3
"""Audit rendered V23 flood movies through Blender's own movie decoder."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "data" / "v23" / "flood_assets" / "flood_render_plan_v23.json"
MANIFEST_PATH = ROOT / "data" / "v23" / "flood_assets" / "flood_assets_manifest_v23.json"
AUDIT_PATH = ROOT / "data" / "v23" / "flood_assets" / "flood_movie_audit_v23.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    rendered = {item["segment_id"]: item for item in manifest.get("segments", [])}
    items = []
    failures = []
    for expected in plan["segments"]:
        segment_id = expected["segment_id"]
        actual = rendered.get(segment_id)
        if actual is None:
            failures.append(f"missing manifest segment: {segment_id}")
            continue
        path = ROOT / expected["output_path"]
        if not path.is_file():
            failures.append(f"missing movie: {path}")
            continue
        clip = bpy.data.movieclips.load(str(path), check_existing=False)
        image = bpy.data.images.load(str(path), check_existing=False)
        item = {
            "segment_id": segment_id,
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "resolution": list(image.size),
            "frame_duration": int(clip.frame_duration),
            "image_source": image.source,
            "movie_clip_source": clip.source,
            "channels": int(image.channels),
            "alpha_mode": image.alpha_mode,
            "expected_frames": expected["frame_count"],
            "valid": True,
        }
        checks = {
            "resolution": item["resolution"] == plan["resolution"],
            "frame_duration": item["frame_duration"] == expected["frame_count"],
            "channels": item["channels"] == 4,
            "alpha_mode": item["alpha_mode"] == "STRAIGHT",
            "image_source": item["image_source"] == "MOVIE",
            "manifest_hash": item["sha256"] == actual["sha256"],
            "manifest_bytes": item["bytes"] == actual["bytes"],
        }
        item["checks"] = checks
        item["valid"] = all(checks.values())
        if not item["valid"]:
            failures.append(f"movie audit failed: {segment_id}")
        items.append(item)
        bpy.data.movieclips.remove(clip)
        bpy.data.images.remove(image)

    result = {
        "schema_version": "1.0",
        "status": "passed" if not failures and len(items) == len(plan["segments"]) else "failed",
        "scene_pack_id": plan["scene_pack_id"],
        "codec_contract": plan["codec_contract"],
        "segment_count": len(items),
        "items": items,
        "failures": failures,
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "passed":
        raise RuntimeError("V23 flood movie audit failed")


if __name__ == "__main__":
    main()
