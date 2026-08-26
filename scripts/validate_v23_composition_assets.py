#!/usr/bin/env python3
"""Validate and register Stage 7 V23 composition assets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

from PIL import Image, ImageStat


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "data" / "v23" / "composition_assets" / "composition_asset_plan_v23.json"
MANIFEST_PATH = ROOT / "data" / "v23" / "composition_assets" / "composition_assets_manifest_v23.json"
AUDIT_PATH = ROOT / "data" / "v23" / "composition_assets" / "composition_movie_audit_v23.json"
REGISTRY_PATH = ROOT / "config" / "scene_pack_registry_v23.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def proof_metrics(path: Path) -> Dict[str, Any]:
    image = Image.open(path).convert("RGBA")
    alpha = image.getchannel("A")
    histogram = alpha.histogram()
    nonzero = sum(histogram[1:])
    stats = ImageStat.Stat(image.convert("RGB"))
    return {
        "resolution": list(image.size),
        "alpha_nonzero_ratio": round(nonzero / (image.width * image.height), 6),
        "alpha_bbox": list(alpha.getbbox()) if alpha.getbbox() else None,
        "rgb_mean": [round(value, 3) for value in stats.mean],
        "rgb_stddev": [round(value, 3) for value in stats.stddev],
    }


def validate(register: bool = False) -> Dict[str, Any]:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    failures = []
    if manifest.get("source_blend_sha256") != sha256(ROOT / plan["source_blend"]):
        failures.append("source blend hash mismatch")
    if manifest.get("plan_sha256") != sha256(PLAN_PATH):
        failures.append("composition asset plan hash mismatch")
    if audit.get("status") != "passed":
        failures.append("Blender movie audit did not pass")

    expected = {item["asset_id"]: item for item in plan["assets"]}
    actual = {item["asset_id"]: item for item in manifest.get("assets", [])}
    if set(expected) != set(actual):
        failures.append("rendered asset IDs do not match the plan")
    for asset_id, item in expected.items():
        rendered = actual.get(asset_id)
        if rendered is None:
            continue
        path = ROOT / item["output_path"]
        checks = {
            "exists": path.is_file(),
            "bytes": path.is_file() and path.stat().st_size == rendered["bytes"],
            "sha256": path.is_file() and sha256(path) == rendered["sha256"],
            "frames": rendered["frame_count"] == item["frame_count"],
            "camera": rendered["camera_object"] == item["camera_object"],
            "view_layer": rendered["view_layer"] == item["view_layer"],
        }
        rendered["validation_checks"] = checks
        if not all(checks.values()):
            failures.append(f"asset validation failed: {asset_id}")

    proofs = {(item["asset_id"], int(item["frame"])): item for item in manifest.get("proofs", {}).get("items", [])}
    metrics = []
    for asset in plan["assets"]:
        for frame in asset["proof_frames"]:
            proof = proofs.get((asset["asset_id"], frame))
            if proof is None:
                failures.append(f"missing proof: {asset['asset_id']} frame {frame}")
                continue
            path = Path(proof["path"])
            if not path.is_file() or sha256(path) != proof["sha256"]:
                failures.append(f"invalid proof: {path}")
                continue
            item = proof_metrics(path)
            item.update({"asset_id": asset["asset_id"], "asset_type": asset["asset_type"], "field_id": asset.get("field_id"), "frame": frame})
            metrics.append(item)

    for field_id in ("OSONG-FIELD-DEMO-001", "OSONG-FIELD-DEMO-002", "OSONG-FIELD-DEMO-003"):
        focus = [item for item in metrics if item.get("field_id") == field_id and item["asset_type"] == "field_overlay" and item["frame"] in {400, 600}]
        if len(focus) != 2 or any(item["alpha_nonzero_ratio"] <= 0 for item in focus):
            failures.append(f"field overlay is not visible in focus frames: {field_id}")
        backgrounds = [item for item in metrics if item.get("field_id") == field_id and item["asset_type"] == "field_clean_background"]
        background_asset = next(
            item
            for item in plan["assets"]
            if item.get("field_id") == field_id and item["asset_type"] == "field_clean_background"
        )
        if len(backgrounds) != len(background_asset["proof_frames"]) or any(max(item["rgb_stddev"]) < 5 for item in backgrounds):
            failures.append(f"field background proof is blank: {field_id}")
    shelter = [item for item in metrics if item["asset_type"] == "shelter_overlay" and item["frame"] in {768, 888, 960}]
    if len(shelter) != 3 or any(item["alpha_nonzero_ratio"] <= 0 for item in shelter):
        failures.append("shelter overlay is not visible after reveal")

    manifest["status"] = "ready" if not failures else "failed"
    manifest["proofs"]["status"] = "visual_and_alpha_review_passed" if not failures else "failed"
    manifest["proofs"]["metrics"] = metrics
    manifest["movie_audit"] = {
        "status": audit.get("status"),
        "path": str(AUDIT_PATH),
        "bytes": AUDIT_PATH.stat().st_size,
        "sha256": sha256(AUDIT_PATH),
    }
    manifest["selection_by_field_id"] = plan["selection_by_field_id"]
    manifest["shared_shelter_overlay_asset_id"] = plan["shared_shelter_overlay_asset_id"]
    manifest["common_background_clip"] = plan["common_background_clip"]
    manifest["flood_plan"] = plan["flood_plan"]
    manifest.pop("flood_manifest", None)
    manifest["composition_policy"] = plan["composition_policy"]
    manifest["render_totals"] = {
        **plan["render_totals"],
        "total_bytes": sum(item["bytes"] for item in manifest.get("assets", [])),
        "total_render_elapsed_seconds": round(sum(item["render_elapsed_seconds"] for item in manifest.get("assets", [])), 3),
    }
    manifest["failures"] = failures
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if register and not failures:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        pack = registry["scene_packs"][0]
        pack["scene_version"] = "23.4.0-event-composition"
        pack["status"] = "event_time_composition_ready"
        pack["v23_personalization_assets"]["personalization_blend"]["status"] = "ready"
        pack["v23_personalization_assets"]["field_overlay_pipeline"]["status"] = "ready"
        pack["v23_personalization_assets"]["composition_asset_catalog"] = {
            "status": "ready",
            "path": "data/v23/composition_assets/composition_assets_manifest_v23.json",
            "bytes": MANIFEST_PATH.stat().st_size,
            "sha256": sha256(MANIFEST_PATH),
            "asset_count": len(plan["assets"]),
            "selection_policy": "common base plus selected field background, flood, field overlay, and shelter overlay",
            "trigger_time_blender_3d_render": False,
        }
        pack["reuse_policy"]["trigger_time_full_blender_render_allowed"] = False
        pack["reuse_policy"]["event_time_target"] = "compose cached background, flood, requested field and shelter overlays; then add TTS and cards"
        REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": manifest["status"],
        "registered": bool(register and not failures),
        "asset_count": len(actual),
        "total_rendered_frames": plan["render_totals"]["total_rendered_frames"],
        "total_render_elapsed_seconds": manifest["render_totals"]["total_render_elapsed_seconds"],
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Stage 7 V23 composition assets")
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args()
    result = validate(register=args.register)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "ready":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
