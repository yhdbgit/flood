#!/usr/bin/env python3
"""Select OSM farmland demo fields that intersect the official flood extent."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from pyproj import Geod, Transformer
from shapely.geometry import Polygon, box, shape
from shapely.ops import transform


ROOT = Path(__file__).resolve().parents[1]
OSM_PATH = ROOT / "data" / "gis" / "pilot_selection_v11" / "expanded_osm_raw.json"
ROUTE_PATH = ROOT / "data" / "processed" / "osong_shelter_route_v13.geojson"
REGISTRY_PATH = ROOT / "data" / "v23" / "fields" / "field_registry_v23.json"
SCENE_PACK_PATH = ROOT / "config" / "scene_pack_registry_v23.json"
DEFAULT_OUTPUT = ROOT / "data" / "v23" / "fields" / "flood_demo_field_candidates_v23.json"
TO_UTM52N = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
GEOD = Geod(ellps="WGS84")


def _polygon_from_way(element: Dict[str, Any]) -> Polygon | None:
    geometry = element.get("geometry") or []
    if len(geometry) < 4:
        return None
    points = [(float(item["lon"]), float(item["lat"])) for item in geometry]
    if points[0] != points[-1]:
        points.append(points[0])
    polygon = Polygon(points)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    return polygon if polygon.geom_type == "Polygon" and not polygon.is_empty else None


def _distance_m(first: List[float], second: List[float]) -> float:
    return abs(GEOD.inv(first[0], first[1], second[0], second[1])[2])


def select_candidates(min_area_m2: float = 1_500.0, min_intersection_ratio: float = 0.2) -> Dict[str, Any]:
    raw = json.loads(OSM_PATH.read_text(encoding="utf-8"))
    route = json.loads(ROUTE_PATH.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    pack = json.loads(SCENE_PACK_PATH.read_text(encoding="utf-8"))["scene_packs"][0]
    flood_feature = next(
        item for item in route["features"]
        if item.get("properties", {}).get("kind") == "official_flood_extent"
    )
    flood_utm = transform(TO_UTM52N.transform, shape(flood_feature["geometry"]))
    scene_bounds = box(*pack["scene_zone"]["bounds_wgs84"])
    hq_bounds = box(*pack["scene_zone"]["hq_core_bounds_wgs84"])
    existing = registry["fields"]
    existing_sources = {int(item["source"]["element_id"]) for item in existing}
    existing_centres = [item["derived_metrics"]["centre_wgs84"] for item in existing]

    candidates = []
    for element in raw.get("elements", []):
        tags = element.get("tags") or {}
        if element.get("type") != "way" or tags.get("landuse") != "farmland":
            continue
        polygon = _polygon_from_way(element)
        if polygon is None or not scene_bounds.covers(polygon.centroid):
            continue
        polygon_utm = transform(TO_UTM52N.transform, polygon)
        if polygon_utm.area < min_area_m2:
            continue
        intersection_area = polygon_utm.intersection(flood_utm).area
        ratio = intersection_area / polygon_utm.area
        if ratio < min_intersection_ratio:
            continue
        centre = [float(polygon.centroid.x), float(polygon.centroid.y)]
        candidates.append({
            "element_id": int(element["id"]),
            "already_registered": int(element["id"]) in existing_sources,
            "centre_wgs84": centre,
            "area_m2": round(float(polygon_utm.area), 1),
            "official_flood_intersection_area_m2": round(float(intersection_area), 1),
            "official_flood_intersection_percent": round(float(ratio * 100.0), 4),
            "inside_hq_core": bool(hq_bounds.covers(polygon.centroid)),
            "nearest_existing_field_distance_m": round(min(_distance_m(centre, value) for value in existing_centres), 1),
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[float(x), float(y)] for x, y in polygon.exterior.coords]],
            },
            "source_tags": tags,
        })
    candidates.sort(key=lambda item: (
        not item["inside_hq_core"],
        item["already_registered"],
        -item["official_flood_intersection_percent"],
        -item["area_m2"],
    ))
    return {
        "schema_version": "1.0",
        "status": "candidate_analysis",
        "source": {
            "farmland": "archived OpenStreetMap landuse=farmland ways",
            "flood_extent": "environment ministry national-river 100-year flood-map extent",
        },
        "selection_policy": {
            "minimum_area_m2": min_area_m2,
            "minimum_official_flood_intersection_ratio": min_intersection_ratio,
            "prefer_inside_existing_hq_core": True,
            "exclude_current_registered_sources_from_replacement": True,
        },
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-area-m2", type=float, default=1_500.0)
    parser.add_argument("--min-intersection-ratio", type=float, default=0.2)
    args = parser.parse_args()
    result = select_candidates(args.min_area_m2, args.min_intersection_ratio)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    available = [item for item in result["candidates"] if not item["already_registered"]]
    print(json.dumps({
        "status": "ok",
        "candidate_count": result["candidate_count"],
        "available_count": len(available),
        "recommended_element_ids": [item["element_id"] for item in available[:2]],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
