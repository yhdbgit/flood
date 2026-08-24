#!/usr/bin/env python3
"""Prepare a reusable 3 km Osong context around the V11/V13 pilot centre.

The central 1 km high-detail context remains unchanged. This script creates a
lower-detail 3 km background context and records complete source lineage. It
does not invoke Blender and does not render video.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.ops import unary_union

ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
PILOT_V11 = ROOT / "config" / "pilot_area_v11.json"
PILOT_V14 = ROOT / "config" / "pilot_area_v14_3km.json"
FIELD_PATH = ROOT / "config" / "osong_farmland_v11.json"
HYDRO_PATH = ROOT / "data" / "processed" / "osong_hydro_reference_v11.json"
OSM_SOURCE = ROOT / "data" / "gis" / "pilot_selection_v11" / "expanded_osm_raw.json"
CORE_CONTEXT = ROOT / "data" / "processed" / "osong_hq_v11_context.json"
DATA_DIR = ROOT / "data" / "gis" / "osong_context_v14_3km"
AERIAL_PATH = DATA_DIR / "esri_world_imagery_z16.jpg"
AERIAL_META_PATH = DATA_DIR / "esri_world_imagery_z16.json"
ATTRIBUTION_PATH = DATA_DIR / "ATTRIBUTION.txt"
CONTEXT_PATH = ROOT / "data" / "processed" / "osong_context_v14_3km.json"
MANIFEST_PATH = ROOT / "data" / "processed" / "osong_context_v14_3km_manifest.json"
REPORT_PATH = ROOT / "output" / "context_v14_3km" / "preparation_report.json"

OUTER_HALF_SIZE_M = 1500.0
CORE_HALF_SIZE_M = 500.0
OUTER_TERRAIN_GRID = 129
OUTER_AERIAL_ZOOM = 16


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def polygon_parts(geometry):
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return [item for item in getattr(geometry, "geoms", []) if isinstance(item, Polygon)]


def merge_visible_river_surface(context: dict) -> dict:
    shapes = []
    source_ids = set()
    for item in context.get("water_polygons", []):
        polygon = Polygon(item["polygon"])
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if not polygon.is_empty:
            shapes.append(polygon)
            source_ids.add(str(item.get("osm_id")))
    remaining = []
    for item in context.get("waterways", []):
        if item.get("waterway") == "river":
            line = LineString(item["path"])
            shapes.append(line.buffer(float(item.get("width_m", 48.0)) / 2.0, cap_style=2, join_style=2))
            source_ids.add(str(item.get("osm_id")))
        else:
            remaining.append(item)
    if not shapes:
        return context
    clip = box(-OUTER_HALF_SIZE_M, -OUTER_HALF_SIZE_M, OUTER_HALF_SIZE_M, OUTER_HALF_SIZE_M)
    merged = unary_union(shapes).buffer(0).intersection(clip)
    polygons = []
    for index, polygon in enumerate(polygon_parts(merged)):
        if polygon.area < 10:
            continue
        polygons.append({
            "osm_id": "merged:" + ",".join(sorted(source_ids)),
            "name": "미호강 및 합류부",
            "water": "river_merged_surface",
            "polygon": [[round(x, 3), round(y, 3)] for x, y in list(polygon.exterior.coords)[:-1]],
            "merged_part_index": index,
        })
    context["water_polygons"] = polygons
    context["waterways"] = remaining
    context["water_surface_processing"] = {
        "method": "union of OSM water polygons and width-buffered river centrelines",
        "clip_size_m": [3000.0, 3000.0],
        "source_osm_ids": sorted(source_ids),
    }
    return context


def exact_utm_terrain_grid(base, aoi: dict) -> dict:
    """Sample SRTM on an exact 3,000 m UTM square instead of a WGS84 rectangle."""
    origin_x, origin_y = map(float, aoi["origin_utm"])
    inverse = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)
    values = base.read_hgt()
    raw = []
    elevations = []
    for row in range(OUTER_TERRAIN_GRID):
        y = OUTER_HALF_SIZE_M - 2.0 * OUTER_HALF_SIZE_M * row / (OUTER_TERRAIN_GRID - 1)
        for column in range(OUTER_TERRAIN_GRID):
            x = -OUTER_HALF_SIZE_M + 2.0 * OUTER_HALF_SIZE_M * column / (OUTER_TERRAIN_GRID - 1)
            lon, lat = inverse.transform(origin_x + x, origin_y + y)
            elevation = base.sample_hgt(values, lon, lat)
            raw.append([round(x, 3), round(y, 3), elevation])
            elevations.append(elevation)
    minimum = min(elevations)
    return {
        "rows": OUTER_TERRAIN_GRID,
        "columns": OUTER_TERRAIN_GRID,
        "source": str(base.HGT_PATH),
        "source_resolution": "SRTM 1 arc-second, approximately 30 m",
        "sampling_crs": "EPSG:32652 exact metre grid",
        "elevation_min_m": minimum,
        "elevation_max_m": max(elevations),
        "vertical_exaggeration": base.VERTICAL_EXAGGERATION,
        "vertices": [
            [x, y, round((z - minimum) * base.VERTICAL_EXAGGERATION, 3)]
            for x, y, z in raw
        ],
    }


def write_attribution():
    ATTRIBUTION_PATH.write_text("\n".join([
        "Osong reusable 3 km context V14 data attribution",
        "",
        "Outer aerial imagery: Esri World Imagery, zoom 16.",
        "Central aerial imagery: existing V11 Esri World Imagery, zoom 18.",
        "Vector context: OpenStreetMap contributors (ODbL).",
        "Official river/use district: VWorld UJ201 project source.",
        "Terrain: SRTM 1 arc-second N36E127, approximately 30 m.",
        "",
        "The central agricultural polygon is OSM land cover, not a cadastral parcel.",
        "The outer 3 km area is visual context and is not an expanded hydraulic model domain.",
    ]), encoding="utf-8")


def main():
    pilot = load_json(PILOT_V11)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    base = load_module("prepare_osong_context_v14_base", ROOT / "scripts" / "prepare_gangnae_hq_v10.py")
    base.FIELD_PATH = FIELD_PATH
    base.HYDRO_PATH = HYDRO_PATH
    base.DATA_DIR = DATA_DIR
    base.RAW_OSM_PATH = OSM_SOURCE
    base.AERIAL_PATH = AERIAL_PATH
    base.AERIAL_META_PATH = AERIAL_META_PATH
    base.ATTRIBUTION_PATH = ATTRIBUTION_PATH
    base.CONTEXT_PATH = CONTEXT_PATH
    base.REPORT_PATH = REPORT_PATH
    base.AOI_HALF_SIZE_M = OUTER_HALF_SIZE_M
    base.TERRAIN_COLUMNS = OUTER_TERRAIN_GRID
    base.TERRAIN_ROWS = OUTER_TERRAIN_GRID
    base.AERIAL_ZOOM = OUTER_AERIAL_ZOOM
    base.polygon_centre = lambda _field: tuple(pilot["centre_wgs84"])
    base.terrain_grid = lambda aoi: exact_utm_terrain_grid(base, aoi)
    base.write_attribution = write_attribution
    base.main()

    generated_at = datetime.now(timezone.utc).isoformat()
    context = merge_visible_river_surface(load_json(CONTEXT_PATH))
    context["schema_version"] = "1.0"
    context["scene"] = "Osong_Context_V14_3km"
    context["generated_at_utc"] = generated_at
    context["validation"]["aoi_size_m"] = [3000.0, 3000.0]
    context["validation"]["video_rendered"] = False
    context["detail_zones"] = {
        "outer_background": {
            "size_m": [3000.0, 3000.0],
            "bounds_local_m": [-1500.0, -1500.0, 1500.0, 1500.0],
            "terrain_grid": [OUTER_TERRAIN_GRID, OUTER_TERRAIN_GRID],
            "aerial_zoom": OUTER_AERIAL_ZOOM,
            "role": "low-detail visual background outside the story camera frustum",
        },
        "central_precision": {
            "size_m": [1000.0, 1000.0],
            "bounds_local_m": [-500.0, -500.0, 500.0, 500.0],
            "context_path": str(CORE_CONTEXT),
            "aerial_zoom": 18,
            "role": "existing V11/V13 detailed terrain, field, river and inundation focus",
        },
    }
    context["reuse_contract"] = {
        "origin_policy": "same EPSG:32652 origin as V11 and V13",
        "core_data_unchanged": True,
        "outer_context_is_hydraulic_domain": False,
        "video_generated_by_preparation": False,
        "intended_use": "future Blender base-scene and camera-background reuse",
    }
    context["source_lineage"] = {
        "pilot_config": str(PILOT_V11),
        "field_geometry": str(FIELD_PATH),
        "core_context": str(CORE_CONTEXT),
        "osm_raw": str(OSM_SOURCE),
        "terrain_hgt": context["terrain"]["source"],
        "outer_aerial": str(AERIAL_PATH),
        "official_river_reference": str(HYDRO_PATH),
    }
    CONTEXT_PATH.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")

    pilot_v14 = {
        **pilot,
        "schema_version": "1.0",
        "pilot_id": "OSONG-MIHO-AGRI-V14-3KM",
        "display_name": "청주시 오송읍 미호강 파일럿 3km 배경 확장",
        "selection_status": "reusable_3km_visual_context_prepared",
        "aoi_bounds_wgs84": context["georeference"]["bounds_wgs84"],
        "aoi_size_m": [3000.0, 3000.0],
        "core_aoi_size_m": [1000.0, 1000.0],
        "lineage": {
            "derived_from": str(PILOT_V11),
            "centre_unchanged": True,
            "field_unchanged": True,
            "purpose": "hide rectangular terrain edges in wide camera views",
        },
    }
    PILOT_V14.write_text(json.dumps(pilot_v14, ensure_ascii=False, indent=2), encoding="utf-8")

    tracked = [PILOT_V14, CONTEXT_PATH, AERIAL_PATH, AERIAL_META_PATH, ATTRIBUTION_PATH, OSM_SOURCE, CORE_CONTEXT]
    manifest = {
        "schema_version": "1.0",
        "dataset_id": "OSONG-CONTEXT-V14-3KM",
        "generated_at_utc": generated_at,
        "status": "prepared_without_video",
        "coordinate_reference_system": "EPSG:32652",
        "origin_wgs84": context["georeference"]["origin_wgs84"],
        "outer_size_m": [3000.0, 3000.0],
        "core_size_m": [1000.0, 1000.0],
        "files": [
            {"path": str(item), "bytes": item.stat().st_size, "sha256": sha256(item)}
            for item in tracked if item.is_file()
        ],
        "blender_scene": None,
        "video_outputs": [],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    report = load_json(REPORT_PATH)
    report.update({
        "status": "ok",
        "scene": "Osong_Context_V14_3km",
        "aoi_size_m": [3000.0, 3000.0],
        "core_size_m": [1000.0, 1000.0],
        "aerial_zoom": OUTER_AERIAL_ZOOM,
        "terrain_grid": [OUTER_TERRAIN_GRID, OUTER_TERRAIN_GRID],
        "context_path": str(CONTEXT_PATH),
        "manifest_path": str(MANIFEST_PATH),
        "video_rendered": False,
    })
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
