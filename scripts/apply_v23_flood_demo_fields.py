#!/usr/bin/env python3
"""Apply the reviewed V23 flood-demo field selection and GIS risk metrics."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Dict

from pyproj import Geod, Transformer
from shapely.geometry import shape
from shapely.ops import transform


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "data" / "v23" / "fields" / "field_registry_v23.json"
CANDIDATES_PATH = ROOT / "data" / "v23" / "fields" / "flood_demo_field_candidates_v23.json"
ROUTE_PATH = ROOT / "data" / "processed" / "osong_shelter_route_v13.geojson"
AUDIT_PATH = ROOT / "data" / "v23" / "fields" / "field_selection_audit_v23.json"
STALE_MANIFESTS = (
    ROOT / "data" / "v23" / "field_assets" / "field_assets_manifest_v23.json",
    ROOT / "data" / "v23" / "flood_assets" / "flood_assets_manifest_v23.json",
    ROOT / "data" / "v23" / "composition_assets" / "composition_assets_manifest_v23.json",
)
REPLACEMENT_FIELD_ID = "OSONG-FIELD-DEMO-003"
REPLACEMENT_ELEMENT_ID = 662073267
TO_UTM52N = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
GEOD = Geod(ellps="WGS84")


def _distance_m(first: list[float], second: list[float]) -> float:
    return abs(GEOD.inv(first[0], first[1], second[0], second[1])[2])


def _metrics(geometry: Dict[str, Any], flood_utm) -> Dict[str, Any]:
    polygon = shape(geometry)
    polygon_utm = transform(TO_UTM52N.transform, polygon)
    intersection_area = polygon_utm.intersection(flood_utm).area
    ratio = intersection_area / polygon_utm.area if polygon_utm.area else 0.0
    return {
        "area_m2": round(float(polygon_utm.area), 1),
        "centre_wgs84": [round(float(polygon.centroid.x), 10), round(float(polygon.centroid.y), 10)],
        "bounds_wgs84": [round(float(value), 10) for value in polygon.bounds],
        "official_flood_intersection_area_m2": round(float(intersection_area), 1),
        "official_flood_intersection_percent": round(float(ratio * 100.0), 4),
        "official_flood_intersection_source": "environment_ministry_national_river_100_year_extent",
    }


def apply_selection() -> tuple[Dict[str, Any], Dict[str, Any]]:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    candidates = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))["candidates"]
    route = json.loads(ROUTE_PATH.read_text(encoding="utf-8"))
    selected = next(item for item in candidates if item["element_id"] == REPLACEMENT_ELEMENT_ID)
    flood_feature = next(
        item for item in route["features"]
        if item.get("properties", {}).get("kind") == "official_flood_extent"
    )
    flood_utm = transform(TO_UTM52N.transform, shape(flood_feature["geometry"]))

    before = deepcopy(next(item for item in registry["fields"] if item["field_id"] == REPLACEMENT_FIELD_ID))
    for field in registry["fields"]:
        if field["field_id"] == REPLACEMENT_FIELD_ID:
            field["geometry"] = selected["geometry"]
            field["display_name"] = "오송 미호강 북측 데모 농경지 3 (침수범위 교차)"
            field["source"] = {
                "provider": "OpenStreetMap contributors",
                "element_type": "way",
                "element_id": REPLACEMENT_ELEMENT_ID,
                "tag": "landuse=farmland",
                "derivation": "Unmodified closed OSM way selected by official 100-year flood-extent intersection",
            }
        field["derived_metrics"] = _metrics(field["geometry"], flood_utm)
        field["shelter"]["distance_m"] = round(
            _distance_m(field["derived_metrics"]["centre_wgs84"], field["shelter"]["location_wgs84"]), 1
        )
        field["asset_binding"]["preparation_status"] = "pending"

    after = deepcopy(next(item for item in registry["fields"] if item["field_id"] == REPLACEMENT_FIELD_ID))
    audit = {
        "schema_version": "1.0",
        "status": "selection_applied_assets_pending",
        "reason": "All demo fields must intersect the official flood extent for semantic personalization proofs.",
        "replacement": {
            "field_id": REPLACEMENT_FIELD_ID,
            "old_element_id": before["source"]["element_id"],
            "new_element_id": after["source"]["element_id"],
            "old_centre_wgs84": before["derived_metrics"]["centre_wgs84"],
            "new_centre_wgs84": after["derived_metrics"]["centre_wgs84"],
        },
        "official_intersection_percent_by_field_id": {
            item["field_id"]: item["derived_metrics"]["official_flood_intersection_percent"]
            for item in registry["fields"]
        },
        "media_policy": {
            "existing_v23_stage7_movies_are_stale": True,
            "full_mp4_render_before_low_resolution_proof_approval": False,
        },
    }
    return registry, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--audit", type=Path, default=AUDIT_PATH)
    args = parser.parse_args()
    registry, audit = apply_selection()
    args.registry.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    for path in STALE_MANIFESTS:
        if path.is_file():
            document = json.loads(path.read_text(encoding="utf-8"))
            document["status"] = "stale_field_selection_changed"
            document["stale_reason"] = "Field 003 geometry and field-specific camera coverage changed; cached media must not be selected."
            path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "registry": str(args.registry),
        "audit": str(args.audit),
        "intersection_percent_by_field_id": audit["official_intersection_percent_by_field_id"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
