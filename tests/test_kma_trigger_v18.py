#!/usr/bin/env python3
"""Deterministic tests for the V18 KMA forecast and trigger contract."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kma_forecast_v18 import KST, latlon_to_grid, normalize_next_day_forecast, parse_pcp
from prepare_guidance_context_v18 import build_guidance_context, read_json
from run_kma_trigger_v18 import record_trigger


def make_document(values, base_date="20260825", target_date="20260826"):
    items = []
    for hour, value in enumerate(values):
        items.append({
            "baseDate": base_date,
            "baseTime": "0500",
            "category": "PCP",
            "fcstDate": target_date,
            "fcstTime": f"{hour:02d}00",
            "fcstValue": value,
            "nx": 66,
            "ny": 105,
        })
    items.append({
        "baseDate": base_date,
        "baseTime": "0500",
        "category": "SKY",
        "fcstDate": target_date,
        "fcstTime": "0000",
        "fcstValue": "4",
        "nx": 66,
        "ny": 105,
    })
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
            "body": {"dataType": "JSON", "items": {"item": items}},
        }
    }


class KmaTriggerV18Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = read_json(ROOT / "config" / "kma_trigger_v18.json")
        cls.field = read_json(ROOT / cls.config["inputs"]["field"])
        cls.inundation = read_json(ROOT / cls.config["inputs"]["inundation"])
        cls.hydrology = read_json(ROOT / cls.config["inputs"]["hydrology"])
        cls.guidance = read_json(ROOT / cls.config["inputs"]["guidance"])
        cls.shelter_route = read_json(ROOT / cls.config["inputs"]["shelter_route"])
        cls.now = datetime(2026, 8, 25, 6, 0, tzinfo=KST)
        cls.base = datetime(2026, 8, 25, 5, 0, tzinfo=KST)

    def forecast(self, values):
        return normalize_next_day_forecast(
            make_document(values), self.base, 66, 105, self.now, source_mode="fixture"
        )

    def context(self, forecast, history=None, now=None):
        return build_guidance_context(
            self.config,
            self.field,
            self.inundation,
            forecast,
            self.hydrology,
            self.guidance,
            self.shelter_route,
            history or {"schema_version": "1.0", "events": []},
            now or self.now,
        )

    def test_registered_field_grid(self):
        lon, lat = self.field["derived_metrics"]["centre_wgs84"]
        self.assertEqual(latlon_to_grid(lat, lon), (66, 105))

    def test_pcp_parser_preserves_ranges(self):
        self.assertEqual(parse_pcp("강수없음")["estimate_mm"], 0.0)
        self.assertEqual(parse_pcp("1.0mm 미만")["estimate_mm"], 0.5)
        self.assertEqual(parse_pcp("30.0~50.0mm")["estimate_mm"], 40.0)
        self.assertIsNone(parse_pcp("50.0mm 이상")["upper_bound_mm"])

    def test_complete_80mm_forecast_triggers(self):
        forecast = self.forecast(["3.0"] * 23 + ["11.0"])
        self.assertEqual(forecast["status"], "complete")
        self.assertEqual(forecast["coverage"]["received_hour_count"], 24)
        self.assertEqual(forecast["rain_24h"]["representative_estimate_mm"], 80.0)
        context = self.context(forecast)
        self.assertEqual(context["status"], "ready")
        self.assertTrue(context["trigger"]["should_generate_video"])
        self.assertFalse(context["hydrology"]["used_for_trigger"])
        self.assertEqual(context["inundation"]["condition_role"], "official_hazard_overlap_proxy")

    def test_below_80mm_does_not_trigger(self):
        context = self.context(self.forecast(["3.0"] * 24))
        self.assertEqual(context["status"], "not_triggered")
        self.assertFalse(context["trigger"]["should_generate_video"])
        self.assertIn("RAIN_BELOW_THRESHOLD", context["trigger"]["reason_codes"])

    def test_incomplete_forecast_is_unavailable(self):
        context = self.context(self.forecast(["3.0"] * 23))
        self.assertEqual(context["status"], "unavailable")
        self.assertIn("FORECAST_INCOMPLETE", context["trigger"]["reason_codes"])

    def test_recent_dispatch_activates_cooldown(self):
        history = {
            "schema_version": "1.0",
            "events": [{
                "event_id": "recent",
                "field_id": self.field["field_id"],
                "target_date": "2026-08-26",
                "dispatched_at": (self.now - timedelta(hours=1)).isoformat(),
                "status": "delivered",
            }],
        }
        context = self.context(self.forecast(["3.0"] * 23 + ["11.0"]), history)
        self.assertEqual(context["status"], "cooldown")
        self.assertFalse(context["trigger"]["should_generate_video"])
        self.assertTrue(context["trigger"]["cooldown"]["active"])

    def test_expired_cooldown_allows_trigger(self):
        history = {
            "schema_version": "1.0",
            "events": [{
                "event_id": "old",
                "field_id": self.field["field_id"],
                "target_date": "2026-08-23",
                "dispatched_at": (self.now - timedelta(hours=49)).isoformat(),
                "status": "delivered",
            }],
        }
        context = self.context(self.forecast(["3.0"] * 23 + ["11.0"]), history)
        self.assertEqual(context["status"], "ready")

    def test_record_trigger_writes_no_credentials(self):
        context = self.context(self.forecast(["3.0"] * 23 + ["11.0"])
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "history.json"
            event = record_trigger(path, context, self.now)
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["events"][0]["event_id"], event["event_id"])
        self.assertNotIn("serviceKey", json.dumps(saved))

    def test_context_satisfies_required_schema_keys(self):
        context = self.context(self.forecast(["3.0"] * 23 + ["11.0"])
        )
        schema = read_json(ROOT / "config" / "guidance_context_v18.schema.json")
        self.assertTrue(set(schema["required"]).issubset(context))
        self.assertEqual(context["schema_version"], "1.0")
        self.assertFalse(context["inundation"]["hydraulic_event_forecast"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
