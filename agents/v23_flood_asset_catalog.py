#!/usr/bin/env python3
"""Resolve pre-rendered V23 flood-layer segments without running Blender."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

from v23_field_registry import FieldRegistry


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data" / "v23" / "flood_assets" / "flood_assets_manifest_v23.json"


class FloodAssetCatalogError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class FloodAssetCatalog:
    """Read-only selector for the opening, field, and ending flood clips."""

    def __init__(self, manifest: Dict[str, Any], root: Path = ROOT):
        if manifest.get("status") != "ready":
            raise FloodAssetCatalogError("flood asset manifest is not ready")
        self.root = root
        self.manifest = deepcopy(manifest)
        self._segments = {item["segment_id"]: item for item in manifest["segments"]}
        self._selection = manifest["selection_contract"]

    @classmethod
    def load(cls, path: Path = DEFAULT_MANIFEST, root: Path = ROOT) -> "FloodAssetCatalog":
        return cls(json.loads(path.read_text(encoding="utf-8")), root=root)

    def select(self, field_id: str, scenario_id: str) -> Dict[str, Any]:
        if scenario_id != "caution":
            raise FloodAssetCatalogError(f"unsupported rendered scenario_id: {scenario_id}")
        try:
            field_segment_id = self._selection["field_segment_by_field_id"][field_id]
        except KeyError as exc:
            raise FloodAssetCatalogError(f"no flood-layer segment for field_id: {field_id}") from exc
        segment_ids = [field_segment_id, self._selection["ending_segment_id"]]
        segments = [deepcopy(self._segments[segment_id]) for segment_id in segment_ids]
        field = FieldRegistry.load().get(field_id)
        intersection_percent = field["derived_metrics"]["official_flood_intersection_percent"]
        return {
            "status": "resolved",
            "scenario_id": scenario_id,
            "field_id": field_id,
            "segments": segments,
            "total_output_frames": sum(item["frame_count"] for item in segments),
            "duration_seconds": round(sum(item["duration_seconds"] for item in segments), 4),
            "field_focus_flood_visible": intersection_percent > 0,
            "official_flood_intersection_percent": intersection_percent,
            "official_flood_intersection_source": field["derived_metrics"]["official_flood_intersection_source"],
            "risk_claim_allowed": intersection_percent > 0,
            "trigger_time_blender_render_required": False,
        }

    def verify_local_assets(self, selection: Dict[str, Any]) -> Dict[str, Any]:
        items = []
        for segment in selection["segments"]:
            path = self.root / segment["project_relative_path"]
            exists = path.is_file()
            checks = {
                "exists": exists,
                "bytes": exists and path.stat().st_size == segment["bytes"],
                "sha256": exists and _sha256(path) == segment["sha256"],
            }
            items.append({
                "segment_id": segment["segment_id"],
                "path": str(path),
                "checks": checks,
                "status": "verified" if all(checks.values()) else "invalid",
            })
        return {"items": items, "all_verified": all(item["status"] == "verified" for item in items)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve cached V23 flood-layer clips")
    parser.add_argument("field_id")
    parser.add_argument("--scenario-id", default="caution")
    parser.add_argument("--verify-local", action="store_true")
    args = parser.parse_args()
    catalog = FloodAssetCatalog.load()
    result = catalog.select(args.field_id, args.scenario_id)
    if args.verify_local:
        result["local_asset_integrity"] = catalog.verify_local_assets(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
