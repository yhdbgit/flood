#!/usr/bin/env python3
"""Prepare reusable V19 terrain and shelter data without rendering video.

The V19 scene uses one 12 km low-detail regional terrain around the midpoint
between the registered Osong field and Osong-eup Welfare Center, plus two
1 km high-detail zones.  The existing V11 field core is reused verbatim; this
script only downloads/prepares the regional background and shelter core.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import urllib.error

from pyproj import Transformer
from shapely.geometry import box


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
BASE_SCRIPT = ROOT / "scripts" / "prepare_gangnae_hq_v10.py"
PILOT_PATH = ROOT / "config" / "pilot_area_v14_3km.json"
FIELD_CORE_PATH = ROOT / "data" / "processed" / "osong_hq_v11_context.json"

DATA_ROOT = ROOT / "data" / "gis" / "osong_shelter_v19"
OUTER_DIR = DATA_ROOT / "outer_12km"
SHELTER_DIR = DATA_ROOT / "shelter_hq_1km"
OUTER_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_shelter_v19_outer.json"
SHELTER_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_shelter_v19_hq.json"
MANIFEST_PATH = ROOT / "data" / "processed" / "osong_shelter_v19_manifest.json"
REPORT_PATH = ROOT / "output" / "shelter_v19" / "preparation_report.json"

OUTER_SIZE_M = 12_000.0
OUTER_GRID = 193
OUTER_AERIAL_ZOOM = 15
SHELTER_SIZE_M = 1_000.0
SHELTER_GRID = 129
SHELTER_AERIAL_ZOOM = 18

SHELTER = {
    "id": "OSONG-EUP-WELFARE-CENTER",
    "name": "오송읍복지회관",
    "lon": 127.3241937,
    "lat": 36.60890936,
    "capacity": 262,
    "selection_role": "pilot shelter visualization target",
}


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


def exact_terrain_grid(base, origin_utm, half_size: float, grid: int) -> dict:
    """Sample the existing SRTM tile on an exact UTM metre grid."""
    inverse = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)
    values = base.read_hgt()
    raw = []
    elevations = []
    for row in range(grid):
        y = half_size - 2.0 * half_size * row / (grid - 1)
        for column in range(grid):
            x = -half_size + 2.0 * half_size * column / (grid - 1)
            lon, lat = inverse.transform(origin_utm[0] + x, origin_utm[1] + y)
            elevation = base.sample_hgt(values, lon, lat)
            raw.append([round(x, 3), round(y, 3), elevation])
            elevations.append(elevation)
    minimum = min(elevations)
    return {
        "rows": grid,
        "columns": grid,
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


def bounds_for(origin_utm, half_size: float):
    inverse = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)
    west, south = inverse.transform(origin_utm[0] - half_size, origin_utm[1] - half_size)
    east, north = inverse.transform(origin_utm[0] + half_size, origin_utm[1] + half_size)
    return [west, south, east, north]


def configure_imagery(base, directory: Path, zoom: int, stem: str):
    directory.mkdir(parents=True, exist_ok=True)
    base.DATA_DIR = directory
    base.AERIAL_ZOOM = zoom
    base.AERIAL_PATH = directory / f"{stem}_z{zoom}.jpg"
    base.AERIAL_META_PATH = directory / f"{stem}_z{zoom}.json"
    base.RAW_OSM_PATH = directory / "osm_context_raw.json"


def download_osm_with_fallback(base, bounds, refresh: bool):
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.nchc.org.tw/api/interpreter",
    ]
    last_error = None
    for attempt, endpoint in enumerate(endpoints, start=1):
        base.OVERPASS_URL = endpoint
        try:
            return base.download_osm(bounds, refresh)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            last_error = error
            if attempt < len(endpoints):
                time.sleep(2)
    raise RuntimeError(f"All Overpass endpoints failed: {last_error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    base = load_module("prepare_osong_shelter_v19_base", BASE_SCRIPT)
    pilot = load_json(PILOT_PATH)
    field_core = load_json(FIELD_CORE_PATH)
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
    to_wgs = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)

    field_origin = tuple(float(v) for v in pilot["centre_utm52n"])
    shelter_utm = to_utm.transform(SHELTER["lon"], SHELTER["lat"])
    shelter_local = [shelter_utm[0] - field_origin[0], shelter_utm[1] - field_origin[1]]
    outer_origin = (
        (field_origin[0] + shelter_utm[0]) / 2.0,
        (field_origin[1] + shelter_utm[1]) / 2.0,
    )
    outer_origin_wgs = to_wgs.transform(*outer_origin)

    # 12 km regional terrain: aerial + SRTM only.  This is a visual horizon,
    # not a hydraulic domain, and intentionally excludes heavy OSM geometry.
    configure_imagery(base, OUTER_DIR, OUTER_AERIAL_ZOOM, "esri_world_imagery")
    outer_bounds = bounds_for(outer_origin, OUTER_SIZE_M / 2.0)
    outer_aerial = base.download_aerial(outer_bounds, args.refresh)
    outer = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scene": "Osong_Shelter_V19_Outer",
        "georeference": {
            "bounds_wgs84": outer_bounds,
            "bounds_local_m": [
                -OUTER_SIZE_M / 2.0,
                -OUTER_SIZE_M / 2.0,
                OUTER_SIZE_M / 2.0,
                OUTER_SIZE_M / 2.0,
            ],
            "origin_wgs84": list(outer_origin_wgs),
            "origin_utm": list(outer_origin),
            "crs": "EPSG:32652",
        },
        "aerial": {
            **outer_aerial,
            "path": str(base.AERIAL_PATH),
        },
        "terrain": exact_terrain_grid(base, outer_origin, OUTER_SIZE_M / 2.0, OUTER_GRID),
        "validation": {
            "aoi_size_m": [OUTER_SIZE_M, OUTER_SIZE_M],
            "role": "regional visual background; not hydraulic model domain",
            "video_rendered": False,
        },
    }
    OUTER_CONTEXT_PATH.write_text(json.dumps(outer, ensure_ascii=False, indent=2), encoding="utf-8")

    # 1 km shelter core: high-resolution aerial and local roads/buildings.
    configure_imagery(base, SHELTER_DIR, SHELTER_AERIAL_ZOOM, "esri_world_imagery")
    shelter_bounds = bounds_for(shelter_utm, SHELTER_SIZE_M / 2.0)
    shelter_aerial = base.download_aerial(shelter_bounds, args.refresh)
    shelter_osm = download_osm_with_fallback(base, shelter_bounds, args.refresh)
    shelter_aoi = box(-SHELTER_SIZE_M / 2.0, -SHELTER_SIZE_M / 2.0, SHELTER_SIZE_M / 2.0, SHELTER_SIZE_M / 2.0)
    vectors = base.process_osm(shelter_osm, shelter_utm, shelter_aoi)
    shelter_context = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scene": "Osong_Shelter_V19_HQ",
        "georeference": {
            "bounds_wgs84": shelter_bounds,
            "bounds_local_m": [-500.0, -500.0, 500.0, 500.0],
            "origin_wgs84": [SHELTER["lon"], SHELTER["lat"]],
            "origin_utm": list(shelter_utm),
            "crs": "EPSG:32652",
        },
        "aerial": {**shelter_aerial, "path": str(base.AERIAL_PATH)},
        "terrain": exact_terrain_grid(base, shelter_utm, SHELTER_SIZE_M / 2.0, SHELTER_GRID),
        "buildings": vectors["buildings"],
        "roads": vectors["roads"],
        "water_polygons": vectors["water_polygons"],
        "waterways": vectors["waterways"],
        "shelter": {
            **SHELTER,
            "utm52n": list(shelter_utm),
            "local_from_field_origin_m": [round(v, 3) for v in shelter_local],
        },
        "validation": {
            "aoi_size_m": [SHELTER_SIZE_M, SHELTER_SIZE_M],
            "building_count": len(vectors["buildings"]),
            "road_count": len(vectors["roads"]),
            "shelter_at_hq_origin": True,
            "video_rendered": False,
        },
    }
    if not shelter_context["roads"]:
        raise RuntimeError("No roads were prepared around Osong-eup Welfare Center")
    SHELTER_CONTEXT_PATH.write_text(
        json.dumps(shelter_context, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    generated_at = datetime.now(timezone.utc).isoformat()
    tracked = [
        OUTER_CONTEXT_PATH,
        SHELTER_CONTEXT_PATH,
        Path(outer["aerial"]["path"]),
        Path(shelter_context["aerial"]["path"]),
        FIELD_CORE_PATH,
    ]
    manifest = {
        "schema_version": "1.0",
        "dataset_id": "OSONG-SHELTER-V19",
        "generated_at_utc": generated_at,
        "status": "prepared_without_video",
        "coordinate_reference_system": "EPSG:32652",
        "field_origin_utm52n": list(field_origin),
        "outer_origin_utm52n": list(outer_origin),
        "shelter": shelter_context["shelter"],
        "detail_zones": {
            "regional_background": {"size_m": [12000.0, 12000.0], "aerial_zoom": 15},
            "field_hq_reused": {"size_m": [1000.0, 1000.0], "context": str(FIELD_CORE_PATH)},
            "shelter_hq_new": {"size_m": [1000.0, 1000.0], "context": str(SHELTER_CONTEXT_PATH)},
        },
        "reuse_contract": {
            "field_core_unchanged": True,
            "regional_background_is_hydraulic_domain": False,
            "flood_animation_included": False,
            "camera_animation_planned": True,
            "video_generated_by_preparation": False,
        },
        "files": [
            {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in tracked if path.is_file()
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "status": "ok",
        "outer_context": str(OUTER_CONTEXT_PATH),
        "shelter_context": str(SHELTER_CONTEXT_PATH),
        "manifest": str(MANIFEST_PATH),
        "field_core_reused": str(FIELD_CORE_PATH),
        "outer_size_m": [12000.0, 12000.0],
        "shelter_hq_size_m": [1000.0, 1000.0],
        "shelter_local_from_field_origin_m": [round(v, 3) for v in shelter_local],
        "shelter_building_count": len(vectors["buildings"]),
        "shelter_road_count": len(vectors["roads"]),
        "flood_animation_included": False,
        "video_rendered": False,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
