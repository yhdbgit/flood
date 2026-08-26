#!/usr/bin/env python3
"""Tests for V23 regional Scene Pack registration and field resolution."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
from v23_field_registry import FieldRegistry  # noqa: E402
from v23_scene_pack_registry import ScenePackRegistry, ScenePackRegistryError, validate_scene_pack_registry  # noqa: E402


class V23ScenePackRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry_path = ROOT / "config" / "scene_pack_registry_v23.json"
        cls.document = json.loads(cls.registry_path.read_text(encoding="utf-8"))
        cls.scenes = ScenePackRegistry.load(cls.registry_path)
        cls.fields = FieldRegistry.load()
        cls.event = json.loads((ROOT / "data" / "v23" / "events" / "valid_forecast_and_hydrology.json").read_text(encoding="utf-8"))

    def test_registry_and_scene_pack_are_valid(self):
        validated = validate_scene_pack_registry(self.document)
        self.assertEqual(validated["registry_id"], "SCENE-PACK-REGISTRY-V23")
        self.assertEqual(len(validated["scene_packs"]), 1)

    def test_all_three_fields_resolve_to_the_same_scene_pack(self):
        resolved = {
            self.scenes.resolve_field(self.fields.get(f"OSONG-FIELD-DEMO-00{index}"))["scene_pack_id"]
            for index in (1, 2, 3)
        }
        self.assertEqual(resolved, {"OSONG-MIHO-SCENE-PACK-V23"})

    def test_event_resolves_field_and_scene_pack(self):
        bundle = self.scenes.resolve_event(self.event, self.fields)
        self.assertEqual(bundle["field"]["field_id"], "OSONG-FIELD-DEMO-001")
        self.assertEqual(bundle["scene_pack"]["scene_zone"]["scene_zone_id"], "OSONG-MIHO-REGION")

    def test_field_centres_convert_to_distinct_local_coordinates(self):
        coordinates = []
        for index in (1, 2, 3):
            field = self.fields.get(f"OSONG-FIELD-DEMO-00{index}")
            lon, lat = field["derived_metrics"]["centre_wgs84"]
            coordinates.append(tuple(round(value, 1) for value in self.scenes.local_xy("OSONG-MIHO-SCENE-PACK-V23", lon, lat)))
        self.assertEqual(len(set(coordinates)), 3)
        self.assertTrue(all(-6000 <= axis <= 6000 for pair in coordinates for axis in pair))

    def test_source_asset_hashes_match_the_registered_files(self):
        report = self.scenes.verify_source_assets("OSONG-MIHO-SCENE-PACK-V23")
        self.assertTrue(report["all_verified"])
        self.assertEqual(report["blend"]["status"], "verified")
        self.assertEqual(report["reference_video"]["status"], "verified")

    def test_v22_reference_video_is_not_marked_as_clean_common_base(self):
        pack = self.scenes.get("OSONG-MIHO-SCENE-PACK-V23")
        self.assertFalse(pack["source_assets"]["reference_video"]["eligible_for_v23_common_reuse"])
        self.assertTrue(pack["reuse_policy"]["v22_reference_video_is_not_a_clean_common_base"])

    def test_field_personalization_and_cached_movies_are_ready(self):
        pack = self.scenes.get("OSONG-MIHO-SCENE-PACK-V23")
        assets = pack["v23_personalization_assets"]
        self.assertEqual(pack["status"], "event_time_composition_ready")
        self.assertEqual(assets["clean_common_blend"]["status"], "ready")
        self.assertEqual(assets["common_background_clip"]["status"], "ready")
        self.assertEqual(assets["personalization_blend"]["status"], "ready")
        self.assertEqual(assets["field_overlay_pipeline"]["status"], "ready")
        self.assertEqual(assets["flood_layer_catalog"]["status"], "ready")
        self.assertEqual(assets["composition_asset_catalog"]["status"], "ready")

    def test_v23_ready_asset_hashes_match_registered_files(self):
        report = self.scenes.verify_v23_ready_assets("OSONG-MIHO-SCENE-PACK-V23")
        self.assertTrue(report["all_verified"])
        self.assertEqual(report["clean_common_blend"]["status"], "verified")
        self.assertEqual(report["common_background_clip"]["status"], "verified")

    def test_field_outside_bounds_is_rejected(self):
        field = self.fields.get("OSONG-FIELD-DEMO-001")
        field["derived_metrics"]["centre_wgs84"] = [129.0, 37.0]
        with self.assertRaisesRegex(ScenePackRegistryError, "outside Scene Pack bounds"):
            self.scenes.resolve_field(field)

    def test_scene_zone_mismatch_is_rejected(self):
        field = self.fields.get("OSONG-FIELD-DEMO-001")
        field["asset_binding"]["scene_zone_id"] = "WRONG-ZONE"
        with self.assertRaisesRegex(ScenePackRegistryError, "does not match"):
            self.scenes.resolve_field(field)

    def test_duplicate_scene_pack_is_rejected(self):
        document = deepcopy(self.document)
        document["scene_packs"].append(deepcopy(document["scene_packs"][0]))
        with self.assertRaisesRegex(ScenePackRegistryError, "duplicate scene_pack_id"):
            validate_scene_pack_registry(document)


if __name__ == "__main__":
    unittest.main(verbosity=2)
