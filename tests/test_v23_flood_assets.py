#!/usr/bin/env python3
"""Structural tests for corrected field-specific V23 flood assets."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
from v23_flood_asset_catalog import FloodAssetCatalog, FloodAssetCatalogError  # noqa: E402

PLAN_PATH = ROOT / "data" / "v23" / "flood_assets" / "flood_render_plan_v23.json"
FIELD_REGISTRY_PATH = ROOT / "data" / "v23" / "fields" / "field_registry_v23.json"


class V23FloodAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        cls.fields = json.loads(FIELD_REGISTRY_PATH.read_text(encoding="utf-8"))["fields"]
        cls.catalog = FloodAssetCatalog({
            "status": "ready",
            "segments": cls.plan["segments"],
            "selection_contract": cls.plan["selection_contract"],
        })

    def test_only_shelter_interval_is_shared(self):
        boundaries = [(item["frame_start"], item["frame_end"]) for item in self.plan["segments"]]
        self.assertEqual(boundaries, [(1, 719), (1, 719), (1, 719), (720, 960)])
        self.assertEqual(self.plan["render_totals"]["total_rendered_frames"], 2398)
        self.assertFalse(self.plan["segmentation_policy"]["trigger_time_blender_render"])

    def test_each_field_resolves_its_own_full_visual_and_shared_shelter(self):
        personalized = set()
        for field in self.fields:
            selected = self.catalog.select(field["field_id"], "caution")
            ids = [item["segment_id"] for item in selected["segments"]]
            self.assertEqual(len(ids), 2)
            self.assertEqual(ids[-1], "shared_shelter_hold")
            self.assertEqual(selected["total_output_frames"], 960)
            personalized.add(ids[0])
        self.assertEqual(len(personalized), 3)

    def test_risk_claim_uses_official_geometry_intersection(self):
        for field in self.fields:
            selected = self.catalog.select(field["field_id"], "caution")
            expected = field["derived_metrics"]["official_flood_intersection_percent"]
            self.assertEqual(selected["official_flood_intersection_percent"], expected)
            self.assertTrue(selected["risk_claim_allowed"])

    def test_unsupported_scenario_is_rejected(self):
        with self.assertRaisesRegex(FloodAssetCatalogError, "unsupported rendered scenario"):
            self.catalog.select("OSONG-FIELD-DEMO-001", "severe")


if __name__ == "__main__":
    unittest.main(verbosity=2)
