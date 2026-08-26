#!/usr/bin/env python3
"""Resolve V23 fields to versioned regional Scene Packs and verify source assets."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from pyproj import Transformer

from v23_field_registry import FieldRegistry, FieldRegistryError


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = ROOT / "config" / "scene_pack_registry_v23.json"
TO_UTM52N = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)


class ScenePackRegistryError(ValueError):
    """Raised when a Scene Pack registry or field binding is invalid."""

    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def _valid_bounds(bounds: Any) -> bool:
    return (
        isinstance(bounds, list)
        and len(bounds) == 4
        and all(isinstance(value, (int, float)) for value in bounds)
        and bounds[0] < bounds[2]
        and bounds[1] < bounds[3]
    )


def _contains(bounds: List[float], point: List[float]) -> bool:
    return bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]


def validate_scene_pack_registry(registry: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    if not isinstance(registry, dict):
        raise ScenePackRegistryError(["registry must be a JSON object"])
    if registry.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    if not isinstance(registry.get("registry_id"), str) or not registry.get("registry_id"):
        errors.append("registry_id must be a non-empty string")
    packs = registry.get("scene_packs")
    if not isinstance(packs, list) or not packs:
        errors.append("scene_packs must be a non-empty array")
        packs = []

    seen_pack_ids = set()
    seen_zone_versions = set()
    for index, pack in enumerate(packs):
        path = f"scene_packs[{index}]"
        if not isinstance(pack, dict):
            errors.append(f"{path} must be an object")
            continue
        pack_id = pack.get("scene_pack_id")
        version = pack.get("scene_version")
        if not isinstance(pack_id, str) or not pack_id:
            errors.append(f"{path}.scene_pack_id is required")
        elif pack_id in seen_pack_ids:
            errors.append(f"duplicate scene_pack_id: {pack_id}")
        else:
            seen_pack_ids.add(pack_id)
        if not isinstance(version, str) or not version:
            errors.append(f"{path}.scene_version is required")
        if pack.get("status") not in {"source_ready_personalization_pending", "layered_scene_ready_media_pending", "field_personalization_ready_flood_sequence_pending", "semantic_personalization_proofs_ready_media_pending", "personalization_and_flood_assets_ready", "event_time_composition_ready", "ready", "disabled"}:
            errors.append(f"{path}.status is invalid")

        zone = pack.get("scene_zone")
        if not isinstance(zone, dict):
            errors.append(f"{path}.scene_zone must be an object")
            continue
        zone_id = zone.get("scene_zone_id")
        zone_version = (zone_id, version)
        if zone_version in seen_zone_versions:
            errors.append(f"duplicate scene zone/version: {zone_id}/{version}")
        seen_zone_versions.add(zone_version)
        if zone.get("projected_crs") != "EPSG:32652":
            errors.append(f"{path}.scene_zone.projected_crs must be EPSG:32652")
        origin = zone.get("coordinate_origin_utm52n")
        if not isinstance(origin, list) or len(origin) != 2 or not all(isinstance(value, (int, float)) for value in origin):
            errors.append(f"{path}.scene_zone.coordinate_origin_utm52n is invalid")
        bounds = zone.get("bounds_wgs84")
        core = zone.get("hq_core_bounds_wgs84")
        if not _valid_bounds(bounds):
            errors.append(f"{path}.scene_zone.bounds_wgs84 is invalid")
        if not _valid_bounds(core):
            errors.append(f"{path}.scene_zone.hq_core_bounds_wgs84 is invalid")
        elif _valid_bounds(bounds) and not (
            bounds[0] <= core[0] < core[2] <= bounds[2]
            and bounds[1] <= core[1] < core[3] <= bounds[3]
        ):
            errors.append(f"{path}.scene_zone HQ bounds must be inside regional bounds")

        assets = pack.get("source_assets")
        if not isinstance(assets, dict):
            errors.append(f"{path}.source_assets must be an object")
        else:
            for asset_name in ("blend", "reference_video"):
                asset = assets.get(asset_name)
                if not isinstance(asset, dict):
                    errors.append(f"{path}.source_assets.{asset_name} is required")
                    continue
                asset_path = asset.get("path")
                if not isinstance(asset_path, str) or not asset_path or Path(asset_path).is_absolute():
                    errors.append(f"{path}.source_assets.{asset_name}.path must be project-relative")
                if not isinstance(asset.get("bytes"), int) or asset["bytes"] <= 0:
                    errors.append(f"{path}.source_assets.{asset_name}.bytes must be positive")
                sha = asset.get("sha256")
                if not isinstance(sha, str) or len(sha) != 64:
                    errors.append(f"{path}.source_assets.{asset_name}.sha256 is invalid")
            reference = assets.get("reference_video", {})
            if reference.get("eligible_for_v23_common_reuse") is not False:
                errors.append(f"{path} must not mark the baked V22 reference video as a clean V23 common asset")

        profile_ids = [item.get("camera_profile_id") for item in pack.get("camera_profiles", []) if isinstance(item, dict)]
        if not profile_ids or len(profile_ids) != len(set(profile_ids)) or any(not item for item in profile_ids):
            errors.append(f"{path}.camera_profiles must have unique IDs")
        scenario_ids = [item.get("scenario_id") for item in pack.get("scenario_catalog", []) if isinstance(item, dict)]
        if not scenario_ids or len(scenario_ids) != len(set(scenario_ids)) or any(not item for item in scenario_ids):
            errors.append(f"{path}.scenario_catalog must have unique IDs")
        shelter_ids = [item.get("shelter_id") for item in pack.get("shelters", []) if isinstance(item, dict)]
        if not shelter_ids or len(shelter_ids) != len(set(shelter_ids)) or any(not item for item in shelter_ids):
            errors.append(f"{path}.shelters must have unique IDs")

        personalization = pack.get("v23_personalization_assets")
        if not isinstance(personalization, dict):
            errors.append(f"{path}.v23_personalization_assets must be an object")
        elif pack.get("status") == "source_ready_personalization_pending":
            non_pending = [name for name, item in personalization.items() if not isinstance(item, dict) or item.get("status") != "pending"]
            if non_pending:
                errors.append(f"{path} pending pack has non-pending personalization assets: {', '.join(non_pending)}")
        elif pack.get("status") == "semantic_personalization_proofs_ready_media_pending":
            required_statuses = {
                "clean_common_blend": "ready",
                "common_background_clip": "ready",
                "flood_layer_catalog": "proofs_rendered_review_pending",
                "field_overlay_pipeline": "proofs_rendered_review_pending",
                "personalization_blend": "proofs_rendered_review_pending",
                "composition_asset_catalog": "stale_rebuild_after_proof_approval",
            }
            for asset_name, expected_status in required_statuses.items():
                asset = personalization.get(asset_name)
                if not isinstance(asset, dict) or asset.get("status") != expected_status:
                    errors.append(
                        f"{path}.v23_personalization_assets.{asset_name}.status "
                        f"must be {expected_status}"
                    )
        elif pack.get("status") in {"layered_scene_ready_media_pending", "field_personalization_ready_flood_sequence_pending", "personalization_and_flood_assets_ready", "event_time_composition_ready"}:
            field_ready = pack.get("status") in {"field_personalization_ready_flood_sequence_pending", "personalization_and_flood_assets_ready", "event_time_composition_ready"}
            flood_ready = pack.get("status") in {"personalization_and_flood_assets_ready", "event_time_composition_ready"}
            required_statuses = {
                "clean_common_blend": "ready",
                "common_background_clip": "ready",
                "flood_layer_catalog": "ready" if flood_ready else "preview_verified_sequence_pending",
                "field_overlay_pipeline": "ready" if field_ready else "pending",
            }
            if field_ready:
                required_statuses["personalization_blend"] = "ready"
            if pack.get("status") == "event_time_composition_ready":
                required_statuses["composition_asset_catalog"] = "ready"
            for asset_name, expected_status in required_statuses.items():
                asset = personalization.get(asset_name)
                if not isinstance(asset, dict) or asset.get("status") != expected_status:
                    errors.append(
                        f"{path}.v23_personalization_assets.{asset_name}.status "
                        f"must be {expected_status}"
                    )

    if errors:
        raise ScenePackRegistryError(errors)
    return deepcopy(registry)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class ScenePackRegistry:
    """Read-only Scene Pack resolver for registered fields and events."""

    def __init__(self, registry: Dict[str, Any], root: Path = ROOT):
        validated = validate_scene_pack_registry(registry)
        self.registry_id = validated["registry_id"]
        self.root = root
        self._packs = {item["scene_pack_id"]: item for item in validated["scene_packs"]}

    @classmethod
    def load(cls, path: Path = DEFAULT_REGISTRY_PATH, root: Path = ROOT) -> "ScenePackRegistry":
        return cls(json.loads(path.read_text(encoding="utf-8")), root=root)

    def get(self, scene_pack_id: str) -> Dict[str, Any]:
        try:
            return deepcopy(self._packs[scene_pack_id])
        except KeyError as exc:
            raise ScenePackRegistryError([f"unknown scene_pack_id: {scene_pack_id}"]) from exc

    def resolve_field(self, field: Dict[str, Any]) -> Dict[str, Any]:
        binding = field.get("asset_binding", {})
        pack = self.get(binding.get("scene_pack_id"))
        zone = pack["scene_zone"]
        if binding.get("scene_zone_id") != zone["scene_zone_id"]:
            raise ScenePackRegistryError([
                f"field {field.get('field_id')} scene_zone_id does not match Scene Pack"
            ])
        centre = field.get("derived_metrics", {}).get("centre_wgs84")
        if not isinstance(centre, list) or len(centre) != 2 or not _contains(zone["bounds_wgs84"], centre):
            raise ScenePackRegistryError([
                f"field {field.get('field_id')} centre is outside Scene Pack bounds"
            ])
        if pack["status"] == "disabled":
            raise ScenePackRegistryError([f"scene_pack_id {pack['scene_pack_id']} is disabled"])
        return pack

    def resolve_event(self, event: Dict[str, Any], fields: FieldRegistry) -> Dict[str, Any]:
        try:
            field = fields.resolve_event(event)
        except FieldRegistryError:
            raise
        pack = self.resolve_field(field)
        return {"event": deepcopy(event), "field": field, "scene_pack": pack}

    def local_xy(self, scene_pack_id: str, lon: float, lat: float) -> List[float]:
        pack = self.get(scene_pack_id)
        origin = pack["scene_zone"]["coordinate_origin_utm52n"]
        east, north = TO_UTM52N.transform(lon, lat)
        return [east - origin[0], north - origin[1]]

    def verify_source_assets(self, scene_pack_id: str) -> Dict[str, Any]:
        pack = self.get(scene_pack_id)
        results = {}
        for name in ("blend", "reference_video"):
            expected = pack["source_assets"][name]
            path = self.root / expected["path"]
            exists = path.is_file()
            bytes_ok = exists and path.stat().st_size == expected["bytes"]
            sha_ok = exists and _sha256(path) == expected["sha256"]
            results[name] = {
                "path": str(path),
                "exists": exists,
                "bytes_ok": bytes_ok,
                "sha256_ok": sha_ok,
                "status": "verified" if exists and bytes_ok and sha_ok else "invalid",
            }
        results["all_verified"] = all(item["status"] == "verified" for item in results.values())
        return results

    def verify_v23_ready_assets(self, scene_pack_id: str) -> Dict[str, Any]:
        """Verify V23 personalization assets currently marked ready."""
        pack = self.get(scene_pack_id)
        results: Dict[str, Any] = {}
        for name, expected in pack["v23_personalization_assets"].items():
            if not isinstance(expected, dict) or expected.get("status") != "ready":
                continue
            asset_path = expected.get("path")
            if not isinstance(asset_path, str) or not asset_path:
                results[name] = {
                    "path": None,
                    "exists": False,
                    "bytes_ok": False,
                    "sha256_ok": False,
                    "status": "invalid",
                }
                continue
            path = self.root / asset_path
            exists = path.is_file()
            bytes_ok = exists and path.stat().st_size == expected.get("bytes")
            sha_ok = exists and _sha256(path) == expected.get("sha256")
            results[name] = {
                "path": str(path),
                "exists": exists,
                "bytes_ok": bytes_ok,
                "sha256_ok": sha_ok,
                "status": "verified" if exists and bytes_ok and sha_ok else "invalid",
            }
        results["all_verified"] = bool(results) and all(
            item["status"] == "verified" for item in results.values()
        )
        return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a V23 regional Scene Pack")
    parser.add_argument("scene_pack_id", nargs="?", default="OSONG-MIHO-SCENE-PACK-V23")
    parser.add_argument("--verify-assets", action="store_true")
    args = parser.parse_args()
    registry = ScenePackRegistry.load()
    pack = registry.get(args.scene_pack_id)
    result = {
        "status": "resolved",
        "scene_pack_id": pack["scene_pack_id"],
        "scene_version": pack["scene_version"],
        "pack_status": pack["status"],
        "scene_zone_id": pack["scene_zone"]["scene_zone_id"],
        "camera_profiles": [item["camera_profile_id"] for item in pack["camera_profiles"]],
        "scenario_status": {item["scenario_id"]: item["status"] for item in pack["scenario_catalog"]},
        "personalization_status": {name: item["status"] for name, item in pack["v23_personalization_assets"].items()},
    }
    if args.verify_assets:
        result["source_asset_integrity"] = registry.verify_source_assets(args.scene_pack_id)
        result["v23_ready_asset_integrity"] = registry.verify_v23_ready_assets(args.scene_pack_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
