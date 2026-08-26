#!/usr/bin/env python3
"""Prepare deterministic V23 field overlay and camera inputs from registrations."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List

from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import transform, unary_union

from v23_field_registry import FieldRegistry
from v23_scene_pack_registry import ScenePackRegistry


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "v23" / "field_assets" / "field_asset_plan_v23.json"
SCENE_PACK_ID = "OSONG-MIHO-SCENE-PACK-V23"
OFFICIAL_FLOOD_PATH = ROOT / "data" / "processed" / "osong_shelter_route_v13.geojson"
OSM_PATH = ROOT / "data" / "gis" / "pilot_selection_v11" / "expanded_osm_raw.json"
TO_UTM52N = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)


def _parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [part for part in geometry.geoms if part.geom_type == "Polygon"]


def _official_flood_and_river():
    route = json.loads(OFFICIAL_FLOOD_PATH.read_text(encoding="utf-8"))
    feature = next(item for item in route["features"] if item.get("properties", {}).get("kind") == "official_flood_extent")
    official = transform(TO_UTM52N.transform, shape(feature["geometry"])).buffer(0)
    raw = json.loads(OSM_PATH.read_text(encoding="utf-8"))
    rivers = []
    for element in raw.get("elements", []):
        tags = element.get("tags") or {}
        geometry = element.get("geometry") or []
        if element.get("type") != "way" or len(geometry) < 2:
            continue
        is_river = tags.get("waterway") == "river"
        if not is_river:
            continue
        points = [(float(item["lon"]), float(item["lat"])) for item in geometry]
        source = LineString(points)
        if not source.is_empty:
            rivers.append(transform(TO_UTM52N.transform, source))
    if not rivers:
        raise ValueError("OSM river geometry is unavailable")
    return official, unary_union(rivers)


def _field_flood_stages(field, origin_utm52n):
    polygon = transform(TO_UTM52N.transform, shape(field["geometry"]))
    official, river = _field_flood_stages.context
    final = official.intersection(polygon.buffer(500.0)).buffer(0)
    parts = [part for part in _parts(final) if part.area >= 80.0]
    final = unary_union(parts).buffer(0)
    if final.is_empty:
        raise ValueError(f"No official flood extent near {field['field_id']}")
    boundary_points = [Point(x, y) for part in _parts(final) for x, y in part.exterior.coords]
    minimum_distance = final.distance(river)
    maximum_distance = max(point.distance(river) for point in boundary_points)
    stages = []
    for step in range(1, 11):
        threshold = max(25.0, minimum_distance + (maximum_distance - minimum_distance) * step / 10.0 + 2.0)
        revealed = final.intersection(river.buffer(threshold)).buffer(0)
        polygons = []
        for part in _parts(revealed):
            if part.area < 30.0:
                continue
            simplified = part.simplify(2.0, preserve_topology=True)
            polygons.append([
                [round(float(x - origin_utm52n[0]), 3), round(float(y - origin_utm52n[1]), 3)]
                for x, y in simplified.exterior.coords
            ])
        stages.append({
            "step": step,
            "river_distance_threshold_m": round(threshold, 2),
            "revealed_area_m2": round(float(revealed.area), 1),
            "polygons_local_xy_m": polygons,
        })
    stages[-1]["revealed_area_m2"] = round(float(final.area), 1)
    return stages, round(float(final.area), 1)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _open_ring(coordinates: List[List[float]]) -> List[List[float]]:
    ring = [list(map(float, point)) for point in coordinates]
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    if len(ring) < 3:
        raise ValueError("field polygon needs at least three distinct vertices")
    return ring


def build_field_asset_plan(
    fields: FieldRegistry | None = None,
    scenes: ScenePackRegistry | None = None,
) -> Dict[str, Any]:
    fields = fields or FieldRegistry.load()
    scenes = scenes or ScenePackRegistry.load()
    pack = scenes.get(SCENE_PACK_ID)
    _field_flood_stages.context = _official_flood_and_river()
    origin_utm52n = pack["scene_zone"]["coordinate_origin_utm52n"]
    items = []
    for field_id in sorted(fields._fields):
        field = fields.get(field_id)
        resolved = scenes.resolve_field(field)
        if resolved["scene_pack_id"] != SCENE_PACK_ID:
            continue
        ring_wgs84 = _open_ring(field["geometry"]["coordinates"][0])
        ring_local = [scenes.local_xy(SCENE_PACK_ID, lon, lat) for lon, lat in ring_wgs84]
        centre_lon, centre_lat = field["derived_metrics"]["centre_wgs84"]
        centre = scenes.local_xy(SCENE_PACK_ID, centre_lon, centre_lat)
        xs = [point[0] for point in ring_local]
        ys = [point[1] for point in ring_local]
        width = max(xs) - min(xs)
        depth = max(ys) - min(ys)
        diagonal = math.hypot(width, depth)
        focus_distance = _clamp(max(width, depth) * 1.45, 190.0, 950.0)
        focus_height = _clamp(diagonal * 0.92, 150.0, 760.0)
        approach_distance = _clamp(focus_distance * 1.75, 420.0, 1550.0)
        border_width = _clamp(math.sqrt(float(field["derived_metrics"]["area_m2"])) * 0.012, 0.8, 4.5)
        lens = 62.0 if diagonal < 120.0 else 58.0 if diagonal < 420.0 else 54.0
        slug = field_id.lower().replace("-", "_")
        profile_id = f"V23-{field_id}-CAMERA"
        flood_stages, flood_area = _field_flood_stages(field, origin_utm52n)
        items.append({
            "field_id": field_id,
            "owner_user_id": field["owner_user_id"],
            "display_name": field["display_name"],
            "scene_pack_id": SCENE_PACK_ID,
            "geometry_accuracy": field["geometry_accuracy"],
            "area_m2": field["derived_metrics"]["area_m2"],
            "polygon_wgs84": ring_wgs84,
            "polygon_local_xy_m": [[round(x, 4), round(y, 4)] for x, y in ring_local],
            "centre_wgs84": [centre_lon, centre_lat],
            "centre_local_xy_m": [round(centre[0], 4), round(centre[1], 4)],
            "bounds_local_m": [round(min(xs), 4), round(min(ys), 4), round(max(xs), 4), round(max(ys), 4)],
            "dimensions_m": [round(width, 3), round(depth, 3)],
            "diagonal_m": round(diagonal, 3),
            "overlay": {
                "asset_id": f"V23-FIELD-OVERLAY-{field_id}",
                "collection": f"V23_FIELD_{slug.upper()}",
                "fill_object": f"FieldFill_{field_id}_V23",
                "boundary_object": f"FieldBoundary_{field_id}_V23",
                "label_object": f"FieldLabel_{field_id}_V23",
                "rgba_view_layer": f"V23_FIELD_{field_id[-3:]}_RGBA",
                "composite_view_layer": f"V23_FIELD_{field_id[-3:]}_COMPOSITE",
                "border_width_m": round(border_width, 3),
            },
            "camera_profile": {
                "camera_profile_id": profile_id,
                "camera_object": f"Camera_{field_id}_V23",
                "target_object": f"CameraTarget_{field_id}_V23",
                "lens_mm": lens,
                "clip_start_m": 1.0,
                "clip_end_m": 50000.0,
                "focus_distance_m": round(focus_distance, 3),
                "focus_height_m": round(focus_height, 3),
                "approach_distance_m": round(approach_distance, 3),
                "field_segment_frames": [1, 120, 240, 241, 320, 400, 600, 640, 719],
                "profile_role": "registration-time reusable field-only overview and focus camera",
            },
            "flood_overlay": {
                "asset_id": f"V23-FIELD-FLOOD-{field_id}",
                "collection": f"V23_FIELD_FLOOD_{slug.upper()}",
                "rgba_view_layer": f"V23_FLOOD_{field_id[-3:]}_RGBA",
                "official_local_extent_area_m2": flood_area,
                "official_field_intersection_percent": field["derived_metrics"]["official_flood_intersection_percent"],
                "progression_method": "official extent clipped to 500 m field buffer and revealed by distance from OSM river",
                "hydraulic_time_series": False,
                "stages": flood_stages,
            },
            "shelter_id": field["shelter"]["shelter_id"],
        })
    if len(items) != 3:
        raise ValueError(f"expected three V23 demo fields, got {len(items)}")
    return {
        "schema_version": "1.0",
        "status": "planned",
        "scene_pack_id": SCENE_PACK_ID,
        "scene_version": pack["scene_version"],
        "coordinate_system": {
            "source_crs": "EPSG:4326",
            "projected_crs": pack["scene_zone"]["projected_crs"],
            "origin_utm52n": pack["scene_zone"]["coordinate_origin_utm52n"],
            "blender_units": "metres",
        },
        "generation_policy": {
            "when": "field_registration_or_scene_pack_preparation",
            "trigger_time_full_blender_render": False,
            "one_scene_pack_contains_multiple_field_assets": True,
            "only_requested_field_overlay_is_enabled_for_output": True,
        },
        "fields": items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare V23 field overlay/camera inputs")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    document = build_field_asset_plan()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "output": str(args.output),
        "field_count": len(document["fields"]),
        "camera_profile_ids": [item["camera_profile"]["camera_profile_id"] for item in document["fields"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
