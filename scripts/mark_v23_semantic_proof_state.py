#!/usr/bin/env python3
"""Mark corrected V23 semantic personalization as proof-ready, media pending."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "scene_pack_registry_v23.json"
BLEND = ROOT / "blender" / "osong_personalization_v23.blend"
FIELD_MANIFEST = ROOT / "data" / "v23" / "field_assets" / "field_assets_manifest_v23.json"
FLOOD_MANIFEST = ROOT / "data" / "v23" / "flood_assets" / "flood_assets_manifest_v23.json"
COMPOSITION_MANIFEST = ROOT / "data" / "v23" / "composition_assets" / "composition_assets_manifest_v23.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    document = json.loads(REGISTRY.read_text(encoding="utf-8"))
    pack = next(item for item in document["scene_packs"] if item["scene_pack_id"] == "OSONG-MIHO-SCENE-PACK-V23")
    pack["scene_version"] = "23.5.0-semantic-personalization-proofs"
    pack["status"] = "semantic_personalization_proofs_ready_media_pending"
    assets = pack["v23_personalization_assets"]
    assets["personalization_blend"].update({
        "status": "proofs_rendered_review_pending",
        "bytes": BLEND.stat().st_size,
        "sha256": sha256(BLEND),
        "field_asset_count": 3,
    })
    assets["field_overlay_pipeline"].update({
        "status": "proofs_rendered_review_pending",
        "bytes": FIELD_MANIFEST.stat().st_size,
        "sha256": sha256(FIELD_MANIFEST),
        "field_asset_count": 3,
        "selection_policy": "field-specific camera and overlay for frames 1-719",
    })
    assets["flood_layer_catalog"].update({
        "status": "proofs_rendered_review_pending",
        "view_layer": "one field-specific V23_FLOOD_NNN_RGBA layer per field",
        "path": str(FLOOD_MANIFEST.relative_to(ROOT)),
        "bytes": FLOOD_MANIFEST.stat().st_size,
        "sha256": sha256(FLOOD_MANIFEST),
        "segment_count": 4,
        "total_rendered_frames": 2398,
        "selection_contract": {
            "field_specific_frames": [1, 719],
            "shared_shelter_frames": [720, 960],
        },
    })
    assets["composition_asset_catalog"].update({
        "status": "stale_rebuild_after_proof_approval",
        "bytes": COMPOSITION_MANIFEST.stat().st_size,
        "sha256": sha256(COMPOSITION_MANIFEST),
        "selection_policy": "field-specific background, flood, and field overlay through frame 719; shared shelter only after frame 720",
    })
    pack["reuse_policy"]["event_time_target"] = "select one field-specific cached visual for frames 1-719, then append shared shelter frames 720-960"
    REGISTRY.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": pack["status"],
        "scene_version": pack["scene_version"],
        "personalization_blend_sha256": assets["personalization_blend"]["sha256"],
        "full_mp4_rendered": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
