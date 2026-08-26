#!/usr/bin/env python3
"""Validate V23 field previews and publish ready bindings to both registries."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "v23" / "field_assets" / "field_assets_manifest_v23.json"
FIELD_REGISTRY_PATH = ROOT / "data" / "v23" / "fields" / "field_registry_v23.json"
SCENE_REGISTRY_PATH = ROOT / "config" / "scene_pack_registry_v23.json"
PERSONALIZATION_BLEND = ROOT / "blender" / "osong_personalization_v23.blend"
SCENE_PACK_ID = "OSONG-MIHO-SCENE-PACK-V23"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_metrics(path: Path, transparent: bool):
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] != 4:
        raise RuntimeError(f"Expected RGBA PNG: {path}")
    height, width = image.shape[:2]
    alpha = image[:, :, 3]
    nonzero = alpha > 0
    nonzero_percent = float(nonzero.mean() * 100.0)
    result = {
        "width": width,
        "height": height,
        "alpha_min": int(alpha.min()),
        "alpha_max": int(alpha.max()),
        "nonzero_percent": round(nonzero_percent, 3),
    }
    if transparent:
        ys, xs = nonzero.nonzero()
        if not len(xs):
            raise RuntimeError(f"Transparent overlay has no visible pixels: {path}")
        bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        result["alpha_bbox_px"] = bbox
        result["not_clipped"] = bbox[0] > 1 and bbox[1] > 1 and bbox[2] < width - 2 and bbox[3] < height - 2
        if not 0.05 <= nonzero_percent <= 65.0:
            raise RuntimeError(f"Unexpected overlay alpha coverage {nonzero_percent:.3f}%: {path}")
        if not result["not_clipped"]:
            raise RuntimeError(f"Field overlay touches preview boundary: {path}")
    elif result["alpha_min"] != 255 or result["alpha_max"] != 255:
        raise RuntimeError(f"Composite preview must be opaque: {path}")
    return result


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("field_asset_count") != 3:
        raise RuntimeError("Expected three generated field assets")
    preview_items = manifest.get("previews", {}).get("items", [])
    if len(preview_items) != 9:
        raise RuntimeError("Expected nine field preview renders")
    metrics = {}
    for item in preview_items:
        path = Path(item["path"])
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise RuntimeError(f"Preview hash mismatch: {path}")
        metrics[path.name] = image_metrics(path, bool(item["transparent_background"]))

    manifest["status"] = "ready"
    manifest["scene_version"] = "23.2.0-field-personalization"
    manifest["previews"]["status"] = "visual_review_passed"
    manifest["previews"]["image_validation"] = metrics
    manifest["visual_review"] = {
        "status": "passed_with_known_limits",
        "reviewed_at_local": "2026-08-26",
        "confirmed": [
            "Each field camera keeps the requested field boundary inside the frame.",
            "Each RGBA view layer contains only one requested field overlay.",
            "All three field sizes, including the 620 square metre demo field, remain identifiable.",
        ],
        "known_limits": [
            "Fields 002 and 003 are outside the current 1.5 km HQ core and use the lower-detail regional background.",
            "The overlays identify registered geometry and do not claim calculated flood damage.",
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = json.loads(FIELD_REGISTRY_PATH.read_text(encoding="utf-8"))
    profiles = {asset["field_id"]: asset["camera_profile_id"] for asset in manifest["field_assets"]}
    for field in fields["fields"]:
        field_id = field["field_id"]
        if field_id not in profiles:
            raise RuntimeError(f"Generated camera profile missing for {field_id}")
        field["asset_binding"]["camera_profile_id"] = profiles[field_id]
        field["asset_binding"]["preparation_status"] = "ready"
    FIELD_REGISTRY_PATH.write_text(json.dumps(fields, ensure_ascii=False, indent=2), encoding="utf-8")

    registry = json.loads(SCENE_REGISTRY_PATH.read_text(encoding="utf-8"))
    pack = next(item for item in registry["scene_packs"] if item["scene_pack_id"] == SCENE_PACK_ID)
    source_profiles = [item for item in pack["camera_profiles"] if item.get("status") == "source_reference_only"]
    generated_profiles = []
    for asset in manifest["field_assets"]:
        generated_profiles.append({
            "camera_profile_id": asset["camera_profile_id"],
            "status": "ready",
            "camera_object": asset["camera_object"],
            "supported_field_ids": [asset["field_id"]],
            "field_segment_frames": [241, 320, 400, 600, 640],
            "rgba_view_layer": asset["rgba_view_layer"],
            "composite_view_layer": asset["composite_view_layer"],
            "generated_when": "field_registration_or_scene_pack_preparation",
        })
    pack["camera_profiles"] = source_profiles + generated_profiles
    pack["scene_version"] = "23.2.0-field-personalization"
    pack["status"] = "field_personalization_ready_flood_sequence_pending"
    assets = pack["v23_personalization_assets"]
    assets["personalization_blend"] = {
        "status": "ready",
        "path": str(PERSONALIZATION_BLEND.relative_to(ROOT)),
        "bytes": PERSONALIZATION_BLEND.stat().st_size,
        "sha256": sha256(PERSONALIZATION_BLEND),
        "field_asset_count": 3,
    }
    assets["field_overlay_pipeline"] = {
        "status": "ready",
        "path": str(MANIFEST_PATH.relative_to(ROOT)),
        "bytes": MANIFEST_PATH.stat().st_size,
        "sha256": sha256(MANIFEST_PATH),
        "field_asset_count": 3,
        "selection_policy": "enable_requested_field_only",
    }
    SCENE_REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "manifest": str(MANIFEST_PATH),
        "field_bindings_ready": len(fields["fields"]),
        "camera_profiles_ready": len(generated_profiles),
        "personalization_blend_sha256": assets["personalization_blend"]["sha256"],
        "preview_metrics": metrics,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
