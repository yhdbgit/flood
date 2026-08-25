#!/usr/bin/env python3
"""Contract tests for the context-gated V18 four-agent workflow."""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from guidance_v18_workflow import (  # noqa: E402
    FRAME_END,
    MAX_DURATION_SECONDS,
    build_graph,
    build_segments,
    gate_decision,
    retime_segments_for_audio,
    run_workflow,
)
from kma_forecast_v18 import KST, normalize_next_day_forecast  # noqa: E402
from prepare_guidance_context_v18 import build_guidance_context, read_json  # noqa: E402
from test_kma_trigger_v18 import make_document  # noqa: E402


class GuidanceV18WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = read_json(ROOT / "config" / "kma_trigger_v18.json")
        field = read_json(ROOT / config["inputs"]["field"])
        inundation = read_json(ROOT / config["inputs"]["inundation"])
        hydrology = read_json(ROOT / config["inputs"]["hydrology"])
        guidance = read_json(ROOT / config["inputs"]["guidance"])
        shelter_route = read_json(ROOT / config["inputs"]["shelter_route"])
        now = datetime(2026, 8, 25, 6, 0, tzinfo=KST)
        base = datetime(2026, 8, 25, 5, 0, tzinfo=KST)
        forecast = normalize_next_day_forecast(
            make_document(["3.0"] * 23 + ["11.0"]),
            base,
            66,
            105,
            now,
            source_mode="fixture",
        )
        cls.ready_context = build_guidance_context(
            config,
            field,
            inundation,
            forecast,
            hydrology,
            guidance,
            shelter_route,
            {"schema_version": "1.0", "events": []},
            now,
        )
        cls.live_context = read_json(ROOT / "data" / "runtime" / "guidance_context_v18.json")

    def test_graph_contains_exactly_four_agents(self):
        nodes = set(build_graph().get_graph().nodes)
        self.assertEqual(
            nodes - {"__start__", "__end__"},
            {"script_agent", "tts_agent", "video_production_agent", "composition_agent"},
        )

    def test_current_live_context_is_rejected_before_graph(self):
        gate = gate_decision(self.live_context, "production")
        self.assertFalse(gate["accepted"])
        self.assertIn("VIDEO_TRIGGER_FALSE", gate["reason_codes"])
        self.assertIn("RAIN_BELOW_THRESHOLD", gate["reason_codes"])

    def test_fixture_is_allowed_in_plan_and_staging_only(self):
        self.assertTrue(gate_decision(self.ready_context, "plan")["accepted"])
        self.assertTrue(gate_decision(self.ready_context, "staging")["accepted"])
        production = gate_decision(self.ready_context, "production")
        self.assertFalse(production["accepted"])
        self.assertIn("FIXTURE_NOT_ALLOWED_IN_PRODUCTION", production["reason_codes"])

    def test_storyboard_is_contiguous_and_personalized(self):
        segments = build_segments(self.ready_context)
        self.assertEqual(len(segments), 5)
        self.assertEqual(segments[0]["start_frame"], 1)
        self.assertEqual(segments[-1]["end_frame"], FRAME_END)
        for previous, following in zip(segments, segments[1:]):
            self.assertEqual(previous["end_frame"] + 1, following["start_frame"])
        narration = " ".join(item["narration"] for item in segments)
        self.assertIn("80", narration)
        self.assertIn("85.1", narration)
        self.assertIn(self.ready_context["shelter"]["name"], narration)


    def test_storyboard_expands_to_fit_audio_up_to_two_minutes(self):
        segments = build_segments(self.ready_context)
        durations = [12.2, 12.1, 24.2, 12.2, 11.2]
        assets = {
            item["id"]: {
                "source_duration_seconds": duration,
                "assigned_duration_seconds": item["duration_seconds"],
            }
            for item, duration in zip(segments, durations)
        }
        retimed, total_seconds = retime_segments_for_audio(segments, assets)
        self.assertGreater(total_seconds, 60.0)
        self.assertLessEqual(total_seconds, MAX_DURATION_SECONDS)
        for previous, following in zip(retimed, retimed[1:]):
            self.assertEqual(previous["end_frame"] + 1, following["start_frame"])
        for item in retimed:
            self.assertGreaterEqual(
                item["duration_seconds"], assets[item["id"]]["source_duration_seconds"]
            )

    def test_storyboard_rejects_only_when_audio_timeline_exceeds_two_minutes(self):
        segments = build_segments(self.ready_context)
        assets = {
            item["id"]: {
                "source_duration_seconds": 30.0,
                "assigned_duration_seconds": item["duration_seconds"],
            }
            for item in segments
        }
        with self.assertRaisesRegex(RuntimeError, "exceeds 120 seconds"):
            retime_segments_for_audio(segments, assets)

    def test_ready_fixture_plan_traverses_all_four_agents_without_media_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            context_path = temporary_path / "ready_context.json"
            context_path.write_text(
                json.dumps(self.ready_context, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            result = asyncio.run(run_workflow(context_path, "plan", temporary_path / "output"))
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "planned")
        self.assertEqual(
            result["trace_nodes"],
            ["script_agent", "tts_agent", "video_production_agent", "composition_agent"],
        )
        self.assertIsNone(result["final_video"])
        self.assertEqual(result["tts_meta"]["request_count"], 0)
        self.assertEqual(manifest["duration_seconds"], 60.0)
        self.assertEqual(manifest["visual_mode"], "context_specific_stage_slideshow")
        self.assertFalse(manifest["hydraulic_event_forecast"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
