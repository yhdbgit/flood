#!/usr/bin/env python3
"""Artifact tests for the Stage 4 V23 layer-separated Blender scene."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data" / "v23" / "scene_packs" / "osong_miho_v23_layer_manifest.json"
SCENE_REGISTRY = ROOT / "config" / "scene_pack_registry_v23.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class V23LayeredSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))
        cls.registry = json.loads(SCENE_REGISTRY.read_text(encoding="utf-8"))

    def test_source_v22_blend_was_not_modified(self):
        source = Path(self.report["source_blend"])
        self.assertTrue(self.report["source_blend_unchanged"])
        self.assertEqual(sha256(source), self.report["source_blend_sha256"])

    def test_v23_layered_blend_matches_report(self):
        blend = Path(self.report["blend_path"])
        self.assertTrue(blend.is_file())
        self.assertEqual(blend.stat().st_size, self.report["blend_bytes"])
        self.assertEqual(sha256(blend), self.report["blend_sha256"])

    def test_common_view_layer_excludes_personalized_and_event_layers(self):
        exclusions = set(self.report["view_layers"]["V23_COMMON_BACKGROUND"]["excluded_parent_groups"])
        self.assertTrue({"V23_FLOOD_LAYER", "V23_FIELD_OVERLAY_TEMPLATES", "V23_SHELTER_OVERLAY"}.issubset(exclusions))
        self.assertFalse(self.report["common_layer_contract"]["personalized_claims_baked_in"])

    def test_flood_and_overlay_layers_are_separate(self):
        groups = self.report["collection_groups"]
        self.assertEqual(groups["V23_FLOOD_LAYER"]["children"], ["V21_FLOOD_STAGES"])
        self.assertEqual(groups["V23_FIELD_OVERLAY_TEMPLATES"]["children"], ["V21_REGISTERED_FIELD"])
        self.assertEqual(groups["V23_SHELTER_OVERLAY"]["children"], ["V19_SHELTER_MARKER"])

    def test_preview_files_are_recorded(self):
        previews = self.report["render_outputs"]["previews"]
        self.assertEqual(previews["status"], "visual_review_passed")
        self.assertEqual(len(previews["items"]), 9)
        for item in previews["items"]:
            self.assertEqual(len(item["sha256"]), 64)
            path = Path(item["path"])
            if path.is_file():
                self.assertEqual(sha256(path), item["sha256"])

    def test_common_background_clip_is_registered_and_locally_verifiable(self):
        pack = self.registry["scene_packs"][0]
        registered = pack["v23_personalization_assets"]["common_background_clip"]
        rendered = self.report["render_outputs"]["common_background_clip"]
        self.assertEqual(registered["status"], "ready")
        self.assertEqual(registered["sha256"], rendered["sha256"])
        self.assertEqual(registered["duration_seconds"], 60.0)
        path = ROOT / registered["path"]
        if path.is_file():
            self.assertEqual(path.stat().st_size, registered["bytes"])
            self.assertEqual(sha256(path), registered["sha256"])

    def test_scene_registry_marks_layered_scene_ready(self):
        pack = self.registry["scene_packs"][0]
        self.assertEqual(pack["status"], "event_time_composition_ready")
        clean = pack["v23_personalization_assets"]["clean_common_blend"]
        self.assertEqual(clean["status"], "ready")
        self.assertEqual(clean["path"], "blender/osong_common_v23.blend")


if __name__ == "__main__":
    unittest.main(verbosity=2)
