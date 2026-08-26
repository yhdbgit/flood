#!/usr/bin/env python3
"""Structural tests for corrected V23 cached-media composition assets."""
from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "data" / "v23" / "composition_assets" / "composition_asset_plan_v23.json"


class V23CompositionAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))

    def test_plan_contains_three_backgrounds_three_field_overlays_and_one_shelter(self):
        counts = {}
        for item in self.plan["assets"]:
            counts[item["asset_type"]] = counts.get(item["asset_type"], 0) + 1
        self.assertEqual(counts, {"field_clean_background": 3, "field_overlay": 3, "shelter_overlay": 1})
        self.assertEqual(self.plan["render_totals"]["total_rendered_frames"], 4555)

    def test_every_field_camera_background_covers_frames_1_through_719(self):
        backgrounds = [item for item in self.plan["assets"] if item["asset_type"] == "field_clean_background"]
        self.assertEqual({(item["frame_start"], item["frame_end"]) for item in backgrounds}, {(1, 719)})
        self.assertEqual(len({item["camera_object"] for item in backgrounds}), 3)

    def test_shared_media_is_limited_to_shelter_interval(self):
        self.assertEqual(self.plan["composition_policy"]["field_background_replacement_frames"], [1, 719])
        self.assertEqual(self.plan["composition_policy"]["shelter_overlay_frames"], [720, 960])
        self.assertFalse(self.plan["composition_policy"]["trigger_time_blender_3d_render"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
