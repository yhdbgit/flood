#!/usr/bin/env python3
"""Validate and register reusable V23 flood-layer assets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "data" / "v23" / "flood_assets" / "flood_render_plan_v23.json"
MANIFEST_PATH = ROOT / "data" / "v23" / "flood_assets" / "flood_assets_manifest_v23.json"
AUDIT_PATH = ROOT / "data" / "v23" / "flood_assets" / "flood_movie_audit_v23.json"
REGISTRY_PATH = ROOT / "config" / "scene_pack_registry_v23.json"
FIELD_MANIFEST_PATH = ROOT / "data" / "v23" / "field_assets" / "field_assets_manifest_v23.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def alpha_metrics(path: Path) -> Dict[str, Any]:
    image = Image.open(path).convert("RGBA")
    alpha = image.getchannel("A")
    histogram = alpha.histogram()
    nonzero = sum(histogram[1:])
    return {
        "mode": "RGBA",
        "resolution": list(image.size),
        "alpha_nonzero_pixels": nonzero,
        "alpha_nonzero_ratio": round(nonzero / (image.width * image.height), 6),
        "alpha_bbox": list(alpha.getbbox()) if alpha.getbbox() else None,
        "transparent_pixels": histogram[0],
    }


def validate(register: bool = False) -> Dict[str, Any]:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    failures = []

    if manifest.get("source_blend_sha256") != sha256(ROOT / plan["source_blend"]):
        failures.append("source blend hash mismatch")
    if manifest.get("plan_sha256") != sha256(PLAN_PATH):
        failures.append("render plan hash mismatch")
    if audit.get("status") != "passed":
        failures.append("Blender movie audit did not pass")

    expected = {item["segment_id"]: item for item in plan["segments"]}
    rendered = {
        item["segment_id"]: item
        for item in manifest.get("segments", [])
        if item["segment_id"] in expected
    }
    manifest["segments"] = list(rendered.values())
    if set(expected) != set(rendered):
        failures.append("rendered segment IDs do not match the plan")
    for segment_id, item in expected.items():
        actual = rendered.get(segment_id)
        if actual is None:
            continue
        path = ROOT / item["output_path"]
        checks = {
            "exists": path.is_file(),
            "bytes": path.is_file() and path.stat().st_size == actual["bytes"],
            "sha256": path.is_file() and sha256(path) == actual["sha256"],
            "frame_count": actual["frame_count"] == item["frame_count"],
            "camera": actual["camera_object"] == item["camera_object"],
            "rgba": actual["colour_mode"] == "RGBA" and actual["transparent_background"] is True,
        }
        actual["validation_checks"] = checks
        if not all(checks.values()):
            failures.append(f"segment validation failed: {segment_id}")

    proofs = {(
        item["segment_id"], int(item["frame"])
    ): item for item in manifest.get("proofs", {}).get("items", [])}
    proof_metrics = []
    for segment in plan["segments"]:
        for frame in segment["proof_frames"]:
            proof = proofs.get((segment["segment_id"], int(frame)))
            if proof is None:
                failures.append(f"missing proof: {segment['segment_id']} frame {frame}")
                continue
            path = Path(proof["path"])
            if not path.is_file() or sha256(path) != proof["sha256"]:
                failures.append(f"invalid proof file: {path}")
                continue
            metrics = alpha_metrics(path)
            metrics.update({"segment_id": segment["segment_id"], "field_id": segment.get("field_id"), "frame": frame})
            proof_metrics.append(metrics)

    # Every demo field uses the official final flood extent clipped around its
    # own geometry, so water must be visible in each maximum proof frame.
    maximum_visibility = {
        field_id: next((item["alpha_nonzero_ratio"] for item in proof_metrics if item.get("field_id") == field_id and item["frame"] == 600), None)
        for field_id in ("OSONG-FIELD-DEMO-001", "OSONG-FIELD-DEMO-002", "OSONG-FIELD-DEMO-003")
    }
    for field_id, ratio in maximum_visibility.items():
        if not ratio or ratio <= 0:
            failures.append(f"maximum flood proof has no visible water: {field_id}")

    status = "ready" if not failures else "failed"
    manifest["status"] = status
    manifest["validated_movie_audit"] = {
        "path": str(AUDIT_PATH),
        "bytes": AUDIT_PATH.stat().st_size,
        "sha256": sha256(AUDIT_PATH),
        "status": audit.get("status"),
    }
    manifest["proofs"]["status"] = "visual_and_alpha_review_passed" if not failures else "failed"
    manifest["proofs"]["alpha_metrics"] = proof_metrics
    manifest["scenario_visibility"] = {
        "scenario_id": "caution",
        "maximum_frame": 600,
        "field_alpha_nonzero_ratio": maximum_visibility,
        "field_intersection_interpretation": {
            "OSONG-FIELD-DEMO-001": "visible in field-focus camera",
            "OSONG-FIELD-DEMO-002": "visible in field-focus camera",
            "OSONG-FIELD-DEMO-003": "visible in field-focus camera",
        },
        "risk_claim_policy": "do not claim field flooding when the selected scenario has no visible intersection",
    }
    manifest["render_totals"] = {
        **plan["render_totals"],
        "total_bytes": sum(item["bytes"] for item in manifest.get("segments", [])),
        "total_render_elapsed_seconds": round(sum(item["render_elapsed_seconds"] for item in manifest.get("segments", [])), 3),
    }
    manifest["selection_contract"] = plan["selection_contract"]
    manifest["trigger_time_policy"] = {
        "full_blender_render_allowed": False,
        "select_cached_opening_field_and_ending_segments": True,
        "scenario_id": "caution",
    }
    manifest["failures"] = failures
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if register and not failures:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        pack = registry["scene_packs"][0]
        pack["scene_version"] = "23.3.0-flood-assets"
        pack["status"] = "personalization_and_flood_assets_ready"
        flood = pack["v23_personalization_assets"]["flood_layer_catalog"]
        flood.update({
            "status": "ready",
            "path": "data/v23/flood_assets/flood_assets_manifest_v23.json",
            "bytes": MANIFEST_PATH.stat().st_size,
            "sha256": sha256(MANIFEST_PATH),
            "segment_count": len(plan["segments"]),
            "total_rendered_frames": plan["render_totals"]["total_rendered_frames"],
            "format": "QuickTime QTRLE RGBA",
            "selection_contract": plan["selection_contract"],
        })
        flood.pop("planned_directory", None)
        caution = next(item for item in pack["scenario_catalog"] if item["scenario_id"] == "caution")
        caution.update({
            "status": "reusable_visual_sequence_ready",
            "eligible_for_event_time_selection": True,
            "note": "Four cached RGBA segments are ready. The sequence is visual guidance, not hydraulic time-step output.",
        })
        pack["limitations"] = [
            item for item in pack["limitations"]
            if item != "Only demo field 001 is covered by the current field-focused camera profile."
        ]
        pack["limitations"] = [
            item for item in pack["limitations"]
            if item != "The caution flood layer is visible in field 001 focus but not in fields 002 or 003; scripts must not claim those fields are flooded."
        ]
        limitation = "Flood progression is a staged visualization of the official final extent, not a hydraulic time-step simulation."
        if limitation not in pack["limitations"]:
            pack["limitations"].append(limitation)
        REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": status,
        "registered": bool(register and not failures),
        "segment_count": len(rendered),
        "total_rendered_frames": plan["render_totals"]["total_rendered_frames"],
        "total_render_elapsed_seconds": manifest["render_totals"]["total_render_elapsed_seconds"],
        "field_maximum_visibility": maximum_visibility,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate V23 flood-layer assets")
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args()
    result = validate(register=args.register)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "ready":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
