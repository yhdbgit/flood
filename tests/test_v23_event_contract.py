#!/usr/bin/env python3
"""Contract tests for trusted upstream V23 trigger events."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
from v23_event_contract import EventContractError, load_and_validate_event, validate_event  # noqa: E402


class V23EventContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.valid_path = ROOT / "data" / "v23" / "events" / "valid_forecast_and_hydrology.json"
        cls.valid_event = json.loads(cls.valid_path.read_text(encoding="utf-8"))

    def test_valid_event_is_accepted_without_trigger_recalculation(self):
        accepted = load_and_validate_event(self.valid_path)
        self.assertEqual(accepted["event_id"], "FLOOD-2026-08-27-OSONG-001")
        self.assertNotIn("should_generate_video", accepted)

    def test_forecast_only_event_is_accepted(self):
        event = deepcopy(self.valid_event)
        event.pop("hydrology_summary")
        self.assertEqual(validate_event(event)["scenario_id"], "caution")

    def test_hydrology_only_event_is_accepted(self):
        event = deepcopy(self.valid_event)
        event.pop("forecast_summary")
        self.assertEqual(validate_event(event)["field_id"], "OSONG-FIELD-DEMO-001")

    def test_missing_field_id_is_rejected(self):
        event = deepcopy(self.valid_event)
        event.pop("field_id")
        with self.assertRaisesRegex(EventContractError, "field_id is required"):
            validate_event(event)

    def test_naive_datetime_is_rejected(self):
        event = deepcopy(self.valid_event)
        event["requested_at"] = "2026-08-26T06:00:02"
        with self.assertRaisesRegex(EventContractError, "must include a timezone"):
            validate_event(event)

    def test_event_without_forecast_or_hydrology_is_rejected(self):
        event = deepcopy(self.valid_event)
        event.pop("forecast_summary")
        event.pop("hydrology_summary")
        with self.assertRaisesRegex(EventContractError, "at least one"):
            validate_event(event)

    def test_internal_trigger_decision_fields_are_rejected(self):
        path = ROOT / "data" / "v23" / "events" / "invalid_internal_trigger_fields.json"
        with self.assertRaises(EventContractError) as raised:
            load_and_validate_event(path)
        message = str(raised.exception)
        self.assertIn("event.should_generate_video is not allowed", message)
        self.assertIn("event.rain_threshold_mm is not allowed", message)
        self.assertIn("event.cooldown_hours is not allowed", message)

    def test_validator_returns_a_defensive_copy(self):
        accepted = validate_event(self.valid_event)
        accepted["source"]["system_id"] = "changed"
        self.assertEqual(self.valid_event["source"]["system_id"], "team-trigger-service")


if __name__ == "__main__":
    unittest.main(verbosity=2)
