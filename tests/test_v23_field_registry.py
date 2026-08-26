#!/usr/bin/env python3
"""Tests for V23 registered-field lookup and ownership isolation."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
from v23_field_registry import FieldRegistry, FieldRegistryError, validate_registry  # noqa: E402


class V23FieldRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry_path = ROOT / "data" / "v23" / "fields" / "field_registry_v23.json"
        cls.registry_document = json.loads(cls.registry_path.read_text(encoding="utf-8"))
        cls.registry = FieldRegistry.load(cls.registry_path)
        cls.event = json.loads((ROOT / "data" / "v23" / "events" / "valid_forecast_and_hydrology.json").read_text(encoding="utf-8"))

    def test_registry_contains_three_distinct_demo_fields(self):
        fields = self.registry_document["fields"]
        self.assertEqual(len(fields), 3)
        self.assertEqual(len({item["field_id"] for item in fields}), 3)
        self.assertEqual(len({item["source"]["element_id"] for item in fields}), 3)

    def test_all_demo_fields_share_the_reserved_scene_pack_and_shelter(self):
        fields = self.registry_document["fields"]
        self.assertEqual({item["asset_binding"]["scene_pack_id"] for item in fields}, {"OSONG-MIHO-SCENE-PACK-V23"})
        self.assertEqual({item["shelter"]["shelter_id"] for item in fields}, {"OSONG-EUP-WELFARE-CENTER"})

    def test_registry_geometry_and_derived_metrics_are_valid(self):
        validated = validate_registry(self.registry_document)
        self.assertEqual(validated["registry_id"], "OSONG-FIELD-REGISTRY-V23")

    def test_all_demo_fields_intersect_official_flood_extent(self):
        for field in self.registry_document["fields"]:
            self.assertGreater(field["derived_metrics"]["official_flood_intersection_percent"], 0.0)

    def test_event_resolves_owned_field(self):
        field = self.registry.resolve_event(self.event)
        self.assertEqual(field["field_id"], "OSONG-FIELD-DEMO-001")
        self.assertEqual(field["owner_user_id"], "USER-DEMO-001")

    def test_event_cannot_resolve_another_users_field(self):
        event = deepcopy(self.event)
        event["field_id"] = "OSONG-FIELD-DEMO-002"
        with self.assertRaisesRegex(FieldRegistryError, "does not own"):
            self.registry.resolve_event(event)

    def test_unknown_field_is_rejected(self):
        with self.assertRaisesRegex(FieldRegistryError, "unknown field_id"):
            self.registry.get("OSONG-FIELD-DOES-NOT-EXIST")

    def test_user_lookup_returns_only_owned_fields(self):
        fields = self.registry.for_user("USER-DEMO-003")
        self.assertEqual([item["field_id"] for item in fields], ["OSONG-FIELD-DEMO-003"])

    def test_lookup_returns_a_defensive_copy(self):
        first = self.registry.get("OSONG-FIELD-DEMO-001")
        first["display_name"] = "changed"
        second = self.registry.get("OSONG-FIELD-DEMO-001")
        self.assertNotEqual(second["display_name"], "changed")

    def test_demo_geometry_limit_is_explicit(self):
        for field in self.registry_document["fields"]:
            self.assertEqual(field["geometry_accuracy"], "osm_landuse_farmland_not_cadastral")
            self.assertTrue(any("not a cadastral ownership parcel" in text for text in field["limitations"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
