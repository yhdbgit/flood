#!/usr/bin/env python3
"""Plan tests for corrected V23 field personalization."""
from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "data" / "v23" / "field_assets" / "field_asset_plan_v23.json"
FIELD_REGISTRY_PATH = ROOT / "data" / "v23" / "fields" / "field_registry_v23.json"


class V23FieldAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        cls.fields = json.loads(FIELD_REGISTRY_PATH.read_text(encoding="utf-8"))["fields"]

    def test_plan_contains_three_distinct_localized_fields(self):
        items = self.plan["fields"]
        self.assertEqual(len(items), 3)
        self.assertEqual(len({item["field_id"] for item in items}), 3)
        self.assertEqual(len({tuple(item["centre_local_xy_m"]) for item in items}), 3)

    def test_each_camera_covers_entire_personalized_interval(self):
        expected = [1, 120, 240, 241, 320, 400, 600, 640, 719]
        for item in self.plan["fields"]:
            self.assertEqual(item["camera_profile"]["field_segment_frames"], expected)

    def test_all_fields_have_official_flood_intersection(self):
        for field in self.fields:
            self.assertGreater(field["derived_metrics"]["official_flood_intersection_percent"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
