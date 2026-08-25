#!/usr/bin/env python3
"""Tests for the V18 guidance-context to Blender-scene policy."""

from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from v18_scene_policy import V18ScenePolicyError, build_preview_specs, require_renderable_context


def ready_context():
    return {
        "schema_version": "1.0",
        "context_id": "OSONG:2026-08-26:fixture",
        "status": "ready",
        "forecast": {
            "target_date": "2026-08-26",
            "source": {"mode": "fixture"},
        },
        "trigger": {
            "should_generate_video": True,
            "target_date": "2026-08-26",
            "rain_condition": {"value_mm": 80.0},
        },
        "inundation": {
            "field_affected_percent": 85.1,
            "condition_role": "official_hazard_overlap_proxy",
            "hydraulic_event_forecast": False,
        },
    }


class V18ScenePolicyTests(unittest.TestCase):
    def test_ready_context_builds_three_previews(self):
        specs = build_preview_specs(ready_context())
        self.assertEqual([item["stage"] for item in specs], ["normal", "maximum", "maximum"])
        self.assertEqual(specs[-1]["camera"], "Camera_Osong_Context_V14_Field")
        self.assertIn("85.1%", specs[-1]["impact_line"])
        self.assertIn("개발용", specs[0]["forecast_line"])

    def test_not_triggered_context_is_rejected(self):
        context = ready_context()
        context["status"] = "not_triggered"
        context["trigger"]["should_generate_video"] = False
        with self.assertRaises(V18ScenePolicyError):
            require_renderable_context(context)

    def test_hydraulic_forecast_claim_is_rejected(self):
        context = copy.deepcopy(ready_context())
        context["inundation"]["hydraulic_event_forecast"] = True
        with self.assertRaises(V18ScenePolicyError):
            require_renderable_context(context)


if __name__ == "__main__":
    unittest.main(verbosity=2)
