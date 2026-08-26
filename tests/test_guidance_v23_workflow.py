from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
import guidance_v23_workflow as workflow  # noqa: E402
from runtime_config import ROOT as CONFIG_ROOT, asset_root  # noqa: E402
from v23_field_registry import FieldRegistry  # noqa: E402
from v23_personalized_visual_builder import build_personalized_visual_plan  # noqa: E402


class GuidanceV23WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fields = FieldRegistry.load()

    def load_event(self, suffix: str):
        name = "valid_forecast_and_hydrology.json" if suffix == "001" else f"valid_forecast_and_hydrology_field_{suffix}.json"
        return json.loads((ROOT / "data" / "v23" / "events" / name).read_text(encoding="utf-8"))

    def test_graph_has_exactly_four_agents(self):
        graph = workflow.build_graph().get_graph()
        nodes = set(graph.nodes) - {"__start__", "__end__"}
        self.assertEqual(nodes, {"script_agent", "tts_agent", "video_production_agent", "composition_agent"})

    def test_each_field_generates_field_specific_script_and_visual_plan(self):
        for suffix in ("001", "002", "003"):
            event = self.load_event(suffix)
            field = self.fields.resolve_event(event)
            segments = workflow.build_segments(event, field)
            text = " ".join(item["narration"] for item in segments)
            self.assertIn(field["display_name"], text)
            self.assertIn(field["shelter"]["name"], text)
            self.assertEqual(segments[0]["start_frame"], 1)
            self.assertEqual(segments[-1]["end_frame"], 1280)
            plan = build_personalized_visual_plan(event, output_root=ROOT / "output" / "test")
            self.assertEqual(plan["field_id"], field["field_id"])
            self.assertEqual(len(plan["strips"]), 6)
            selected = " ".join(item["strip_id"] for item in plan["strips"])
            self.assertIn(f"field_{suffix}", selected)

    def test_project_root_is_derived_from_source_location(self):
        self.assertEqual(CONFIG_ROOT, ROOT)

    def test_asset_root_can_be_overridden_on_windows_or_macos(self):
        expected = ROOT / "portable-assets"
        with patch.dict(os.environ, {"V23_ASSET_ROOT": str(expected)}):
            self.assertEqual(asset_root(), expected.resolve())


if __name__ == "__main__":
    unittest.main()
