#!/usr/bin/env python3
"""Contract tests for the V22 reusable dynamic-base four-agent workflow."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
from guidance_v22_workflow import DYNAMIC_END, FPS, FRAME_END, build_graph, build_segments, run_workflow, validate_reusable_base  # noqa: E402


class GuidanceV22WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context_path = ROOT / "data" / "staging" / "guidance_context_v18_80mm.json"
        cls.context = json.loads(cls.context_path.read_text(encoding="utf-8"))

    def test_graph_contains_exactly_four_agents(self):
        nodes = set(build_graph().get_graph().nodes)
        self.assertEqual(nodes - {"__start__", "__end__"}, {"script_agent", "tts_agent", "video_production_agent", "composition_agent"})

    def test_storyboard_is_contiguous_and_uses_dynamic_base_then_cards(self):
        segments = build_segments(self.context)
        self.assertEqual(len(segments), 6)
        self.assertEqual(segments[0]["start_frame"], 1)
        self.assertEqual(segments[-1]["end_frame"], FRAME_END)
        self.assertEqual(FRAME_END / FPS, 80.0)
        self.assertEqual(segments[3]["end_frame"], DYNAMIC_END)
        self.assertTrue(all(item["visual_type"] == "dynamic_video" for item in segments[:4]))
        self.assertTrue(all(item["visual_type"] == "information_card" for item in segments[4:]))
        for previous, following in zip(segments, segments[1:]):
            self.assertEqual(previous["end_frame"] + 1, following["start_frame"])

    def test_storyboard_omits_old_hazard_overlay_claims(self):
        narration = " ".join(item["narration"] for item in build_segments(self.context))
        self.assertNotIn("100년", narration)
        self.assertNotIn("백 년", narration)
        self.assertNotIn("85.1", narration)
        self.assertIn("오송읍복지회관", narration)
        self.assertIn("80", narration)

    def test_approved_base_is_reuse_only(self):
        report = validate_reusable_base()
        self.assertEqual(report["status"], "approved_silent_base_rendered")
        self.assertEqual(report["video_duration_seconds"], 60.0)
        self.assertEqual(report["reuse_policy"], "render_once_and_reuse_for_all_v22_guidance_compositions")

    def test_plan_mode_traverses_four_agents_without_media_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = asyncio.run(run_workflow(self.context_path, "plan", Path(temporary) / "output"))
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(result["trace_nodes"], ["script_agent", "tts_agent", "video_production_agent", "composition_agent"])
        self.assertIsNone(result["final_video"])
        self.assertEqual(result["tts_meta"]["request_count"], 0)
        self.assertEqual(manifest["duration_seconds"], 80.0)
        self.assertEqual(manifest["base_render_policy"], "reuse_only_never_rerender_in_agent_workflow")


if __name__ == "__main__":
    unittest.main(verbosity=2)
