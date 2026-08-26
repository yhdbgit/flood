from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
import guidance_v23_workflow as workflow  # noqa: E402
from v23_field_registry import FieldRegistry  # noqa: E402


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

    def test_each_field_generates_field_specific_script(self):
        for suffix in ("001", "002", "003"):
            event = self.load_event(suffix)
            field = self.fields.resolve_event(event)
            segments = workflow.build_segments(event, field)
            text = " ".join(item["narration"] for item in segments)
            self.assertIn(field["display_name"], text)
            self.assertIn(f"{field['derived_metrics']['official_flood_intersection_percent']:.1f}", text)
            self.assertIn(field["shelter"]["name"], text)
            self.assertEqual(segments[0]["start_frame"], 1)
            self.assertEqual(segments[-1]["end_frame"], 1280)

    def test_visual_is_reused_without_full_3d_rerender(self):
        event = self.load_event("002")
        field = self.fields.resolve_event(event)
        state = {"event": event, "field": field, "mode": "staging", "run_dir": str(ROOT / "output" / "guidance_v23" / "test")}
        visual = workflow.ensure_personalized_visual(state)
        self.assertTrue(visual["reused"])
        self.assertEqual(visual["status"], "ready")
        self.assertTrue(Path(visual["video"]).is_file())


if __name__ == "__main__":
    unittest.main()
