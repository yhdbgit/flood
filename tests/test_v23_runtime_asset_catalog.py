from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
from v23_runtime_asset_catalog import RuntimeAssetCatalog  # noqa: E402


class RuntimeAssetCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = RuntimeAssetCatalog.load(root=ROOT / "runtime_assets" / "v23")

    def test_all_three_fields_have_independent_cached_media(self):
        flood_ids = set()
        overlay_ids = set()
        for suffix in ("001", "002", "003"):
            selected = self.catalog.select(f"OSONG-FIELD-DEMO-{suffix}", "caution")
            flood_ids.add(selected["field_flood"]["asset_id"])
            overlay_ids.add(selected["field_overlay"]["asset_id"])
            self.assertTrue(selected["field_background"]["path"].endswith(".mp4"))
        self.assertEqual(len(flood_ids), 3)
        self.assertEqual(len(overlay_ids), 3)

    def test_unsupported_scenario_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            self.catalog.select("OSONG-FIELD-DEMO-001", "severe")


if __name__ == "__main__":
    unittest.main()
