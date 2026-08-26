"""Resolve and verify the portable V23 cached-media bundle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

from runtime_config import ROOT, asset_root


CATALOG_PATH = ROOT / "config" / "runtime_assets_v23.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class RuntimeAssetCatalog:
    def __init__(self, document: Dict[str, Any], root: Path | None = None):
        if document.get("schema_version") != "1.0":
            raise ValueError("Unsupported V23 runtime asset catalog")
        self.document = document
        self.root = (root or asset_root()).resolve()

    @classmethod
    def load(cls, path: Path = CATALOG_PATH, root: Path | None = None) -> "RuntimeAssetCatalog":
        return cls(json.loads(path.read_text(encoding="utf-8")), root=root)

    def _item(self, asset_id: str) -> Dict[str, Any]:
        try:
            item = next(item for item in self.document["assets"] if item["asset_id"] == asset_id)
        except StopIteration as exc:
            raise ValueError(f"Unknown V23 runtime asset: {asset_id}") from exc
        return {**item, "path": str((self.root / item["relative_path"]).resolve())}

    def select(self, field_id: str, scenario_id: str) -> Dict[str, Any]:
        if scenario_id != "caution":
            raise ValueError(f"Unsupported rendered scenario_id: {scenario_id}")
        try:
            selection = self.document["selection_by_field_id"][field_id]
        except KeyError as exc:
            raise ValueError(f"No cached V23 assets for field_id: {field_id}") from exc
        return {
            "common_background": self._item(self.document["shared"]["common_background"]),
            "field_background": self._item(selection["field_background"]),
            "field_overlay": self._item(selection["field_overlay"]),
            "field_flood": self._item(selection["field_flood"]),
            "shelter_flood": self._item(self.document["shared"]["shelter_flood"]),
            "shelter_overlay": self._item(self.document["shared"]["shelter_overlay"]),
        }

    def verify(self, selection: Dict[str, Any] | None = None) -> Dict[str, Any]:
        items = selection.values() if selection else (self._item(item["asset_id"]) for item in self.document["assets"])
        results = []
        for item in items:
            path = Path(item["path"])
            exists = path.is_file()
            checks = {
                "exists": exists,
                "bytes": exists and path.stat().st_size == int(item["bytes"]),
                "sha256": exists and _sha256(path) == item["sha256"],
            }
            results.append({"asset_id": item["asset_id"], "path": str(path), "checks": checks, "status": "verified" if all(checks.values()) else "invalid"})
        return {"items": results, "all_verified": all(item["status"] == "verified" for item in results)}

