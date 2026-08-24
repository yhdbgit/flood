"""Prepare a continuous, gauge-referenced Osong river surface and terrain mask."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point, Polygon


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
OUTER_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_context_v14_3km.json"
CORE_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_hq_v11_context.json"
STATION_CONFIG_PATH = ROOT / "config" / "hydro_stations.json"
SNAPSHOT_PATH = ROOT / "data" / "runtime" / "hydro_snapshot.json"
OUTPUT_PATH = ROOT / "data" / "processed" / "osong_river_surface_v15.json"
REPORT_PATH = ROOT / "output" / "river_v15" / "preparation_report.json"

UPSTREAM_CODE = "3011665"
DOWNSTREAM_CODE = "3011685"
OUTER_BANK_BLEND_M = 24.0
CORE_BANK_BLEND_M = 10.0
BED_CLEARANCE_SCENE_M = 1.25


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def station_record(snapshot: dict, code: str):
    item = next((row for row in snapshot["stations"] if row["code"] == code), None)
    if item is None:
        raise RuntimeError(f"Station {code} is missing from {SNAPSHOT_PATH}")
    return item


def reference_surface_elevation(station: dict, config: dict) -> float:
    spec = next((row for row in config["stations"] if row["code"] == station["code"]), None)
    if spec is None:
        raise RuntimeError(f"Station {station['code']} is missing from {STATION_CONFIG_PATH}")
    return float(station["gauge_zero_el_m"]) + float(spec["reference_water_level_m"])


def terrain_adjustments(context: dict, river: Polygon, surface_z, object_z: float, blend_m: float):
    mask = river.buffer(blend_m, join_style=2)
    boundary = river.boundary
    changes = []
    inside_count = 0
    for index, item in enumerate(context["terrain"]["vertices"]):
        x, y, local_z = map(float, item)
        point = Point(x, y)
        if not mask.covers(point):
            continue
        current_world_z = local_z + object_z
        bed_world_z = surface_z(x, y) - BED_CLEARANCE_SCENE_M
        if river.covers(point):
            weight = 1.0
            inside_count += 1
        else:
            distance = point.distance(boundary)
            weight = max(0.0, min(1.0, 1.0 - distance / blend_m))
            weight = weight * weight * (3.0 - 2.0 * weight)
        target_world_z = current_world_z * (1.0 - weight) + min(current_world_z, bed_world_z) * weight
        if target_world_z < current_world_z - 1e-6:
            changes.append([index, round(target_world_z - object_z, 4)])
    return changes, inside_count


def main():
    outer = load_json(OUTER_CONTEXT_PATH)
    core = load_json(CORE_CONTEXT_PATH)
    station_config = load_json(STATION_CONFIG_PATH)
    snapshot = load_json(SNAPSHOT_PATH)
    river = Polygon(outer["water_polygons"][0]["polygon"])
    if not river.is_valid:
        river = river.buffer(0)
    if river.is_empty or river.geom_type != "Polygon":
        raise RuntimeError("The V14 merged river polygon is not a usable Polygon")

    origin_x, origin_y = map(float, outer["georeference"]["origin_utm"])
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
    stations = {}
    for code in (UPSTREAM_CODE, DOWNSTREAM_CODE):
        source = station_record(snapshot, code)
        x, y = transformer.transform(float(source["longitude"]), float(source["latitude"]))
        stations[code] = {
            "code": code,
            "name": source["name"],
            "local_xy_m": [x - origin_x, y - origin_y],
            "gauge_zero_el_m": float(source["gauge_zero_el_m"]),
            "reference_water_level_m": next(
                float(row["reference_water_level_m"])
                for row in station_config["stations"]
                if row["code"] == code
            ),
            "reference_surface_el_m": reference_surface_elevation(source, station_config),
        }

    upstream = stations[UPSTREAM_CODE]
    downstream = stations[DOWNSTREAM_CODE]
    ux0, uy0 = upstream["local_xy_m"]
    dx0, dy0 = downstream["local_xy_m"]
    vx, vy = dx0 - ux0, dy0 - uy0
    distance = math.hypot(vx, vy)
    unit_x, unit_y = vx / distance, vy / distance
    upstream_el = upstream["reference_surface_el_m"]
    downstream_el = downstream["reference_surface_el_m"]
    elevation_slope = (downstream_el - upstream_el) / distance
    terrain_min = float(outer["terrain"]["elevation_min_m"])
    exaggeration = float(outer["terrain"]["vertical_exaggeration"])

    def surface_el(x: float, y: float) -> float:
        along = (x - ux0) * unit_x + (y - uy0) * unit_y
        return upstream_el + elevation_slope * along

    def surface_scene_z(x: float, y: float) -> float:
        return (surface_el(x, y) - terrain_min) * exaggeration

    core_alignment_z = (
        float(core["terrain"]["elevation_min_m"])
        - float(outer["terrain"]["elevation_min_m"])
    ) * exaggeration + 0.08
    outer_changes, outer_inside = terrain_adjustments(
        outer, river, surface_scene_z, 0.0, OUTER_BANK_BLEND_M
    )
    core_changes, core_inside = terrain_adjustments(
        core, river, surface_scene_z, core_alignment_z, CORE_BANK_BLEND_M
    )

    boundary = [[round(float(x), 3), round(float(y), 3)] for x, y in list(river.exterior.coords)[:-1]]
    surface_vertices = [
        [x, y, round(surface_scene_z(x, y), 4)]
        for x, y in boundary
    ]
    payload = {
        "schema_version": "1.0",
        "dataset_id": "OSONG-RIVER-SURFACE-V15",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "crs": outer["georeference"]["crs"],
        "origin_utm": outer["georeference"]["origin_utm"],
        "source_geometry": {
            "dataset_id": "OSONG-CONTEXT-V14-3KM",
            "provider": "OpenStreetMap",
            "method": outer["water_surface_processing"]["method"],
            "source_osm_ids": outer["water_surface_processing"]["source_osm_ids"],
            "polygon_vertex_count": len(boundary),
            "polygon_area_m2": round(river.area, 1),
            "hydraulic_survey_boundary": False,
        },
        "surface_model": {
            "method": "linear longitudinal reference-stage plane",
            "upstream_station": upstream,
            "downstream_station": downstream,
            "station_distance_m": round(distance, 3),
            "flow_direction_unit_xy": [round(unit_x, 8), round(unit_y, 8)],
            "elevation_slope_m_per_m": round(elevation_slope, 10),
            "scene_vertical_exaggeration": exaggeration,
            "terrain_elevation_min_m": terrain_min,
            "realtime_applied": False,
            "purpose": "continuous static baseline water surface; realtime delta is a later stage",
        },
        "water_surface": {
            "boundary_xy": boundary,
            "vertices_xyz": surface_vertices,
            "minimum_scene_z": min(item[2] for item in surface_vertices),
            "maximum_scene_z": max(item[2] for item in surface_vertices),
        },
        "terrain_mask": {
            "bed_clearance_scene_m": BED_CLEARANCE_SCENE_M,
            "outer_bank_blend_m": OUTER_BANK_BLEND_M,
            "core_bank_blend_m": CORE_BANK_BLEND_M,
            "outer_object": "Terrain_Osong_Background_3km",
            "outer_adjustments": outer_changes,
            "outer_inside_vertex_count": outer_inside,
            "core_object": "Terrain_Osong_Core_1km",
            "core_object_z": round(core_alignment_z, 4),
            "core_adjustments": core_changes,
            "core_inside_vertex_count": core_inside,
        },
        "limitations": [
            "The planform uses OSM mapped water geometry, not a surveyed wetted-channel boundary.",
            "The baseline plane uses reference gauge stages; no realtime stage delta is applied in V15.",
            "The terrain mask is a rendering correction, not channel bathymetry.",
        ],
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "status": "ok",
        "dataset": str(OUTPUT_PATH),
        "water_polygon_vertices": len(boundary),
        "water_polygon_area_m2": round(river.area, 1),
        "water_scene_z_range": [payload["water_surface"]["minimum_scene_z"], payload["water_surface"]["maximum_scene_z"]],
        "outer_terrain_vertices_adjusted": len(outer_changes),
        "core_terrain_vertices_adjusted": len(core_changes),
        "video_rendered": False,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
