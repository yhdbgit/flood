#!/usr/bin/env python3
"""Prepare official river zones and OSM centerlines for Blender.

This script runs outside Blender with the project virtual environment. It keeps
all GIS dependencies out of Blender's bundled Python and emits plain JSON in
the same local-metre coordinate system as the terrain-v1 scene.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys

try:
    import shapefile
    from pyproj import Transformer
    from shapely.geometry import box, shape
    from shapely.ops import transform
except ImportError as exc:
    raise SystemExit(
        "Run with /Users/hyeokjae/Desktop/ICTCB/.venv/bin/python "
        "(pyshp, shapely, and pyproj are required)."
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
TERRAIN_REPORT = ROOT / "output" / "terrain_validation_report.json"
UJ201_DIR = ROOT / "data" / "source" / "hydro" / "UJ201"
UJ301_DIR = ROOT / "data" / "source" / "hydro" / "UJ301"
OSM_PATH = (
    ROOT
    / "archive"
    / "source_data_20260822"
    / "pilot_gangnae"
    / "gangnae_osm_context.geojson"
)
OUTPUT_PATH = ROOT / "data" / "processed" / "gangnae_hydro_geometry.json"

METRES_PER_DEGREE_LAT = 111_320.0


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def local_converter(bounds):
    min_lon, min_lat, max_lon, max_lat = bounds
    centre_lon = (min_lon + max_lon) / 2.0
    centre_lat = (min_lat + max_lat) / 2.0
    metres_per_degree_lon = METRES_PER_DEGREE_LAT * math.cos(
        math.radians(centre_lat)
    )

    def to_local(lon, lat, z=None):
        x = (lon - centre_lon) * metres_per_degree_lon
        y = (lat - centre_lat) * METRES_PER_DEGREE_LAT
        if z is None:
            return x, y
        return x, y, z

    return to_local, centre_lon, centre_lat, metres_per_degree_lon


def shape_records(path: Path):
    reader = shapefile.Reader(str(path), encoding="euc-kr", encodingErrors="replace")
    field_names = [field[0] for field in reader.fields[1:]]
    for item in reader.iterShapeRecords():
        properties = dict(zip(field_names, item.record))
        geometry = shape(item.shape.__geo_interface__)
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        yield properties, geometry


def polygon_loops(geometry):
    polygons = (
        list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
    )
    result = []
    for polygon in polygons:
        result.append(
            {
                "exterior": [[round(x, 3), round(y, 3)] for x, y in polygon.exterior.coords],
                "holes": [
                    [[round(x, 3), round(y, 3)] for x, y in ring.coords]
                    for ring in polygon.interiors
                ],
            }
        )
    return result


def line_parts(geometry):
    lines = list(geometry.geoms) if geometry.geom_type == "MultiLineString" else [geometry]
    return [
        [[round(x, 3), round(y, 3)] for x, y in line.coords]
        for line in lines
        if len(line.coords) >= 2
    ]


def main():
    report = load_json(TERRAIN_REPORT)
    bounds = report["bounds_wgs84"]
    aoi_wgs = box(*bounds)
    to_local, centre_lon, centre_lat, metres_per_degree_lon = local_converter(bounds)
    native_to_wgs = Transformer.from_crs(5174, 4326, always_xy=True).transform
    wgs_to_native = Transformer.from_crs(4326, 5174, always_xy=True).transform
    aoi_native = transform(wgs_to_native, aoi_wgs)

    uj201_path = next(UJ201_DIR.glob("*.shp"))
    uj301_path = next(UJ301_DIR.glob("*.shp"))
    zones = []
    zone_native = {}

    for properties, geometry in shape_records(uj201_path):
        alias = str(properties.get("ALIAS", "")).strip()
        mnum = str(properties.get("MNUM", "")).strip()
        if "미호강" not in alias or "UJB100" not in mnum:
            continue
        clipped = geometry.intersection(aoi_native)
        if clipped.is_empty:
            continue
        clipped_wgs = transform(native_to_wgs, clipped)
        clipped_local = transform(to_local, clipped_wgs)
        zones.append(
            {
                "id": "riverzone_miho",
                "name": "미호강",
                "official_alias": alias,
                "source_layer": "UJ201",
                "classification": "UJB100",
                "mnum": mnum,
                "intersection_area_m2": round(clipped.area, 1),
                "polygons": polygon_loops(clipped_local),
            }
        )
        zone_native["미호강"] = clipped

    small_zones = []
    for properties, geometry in shape_records(uj301_path):
        alias = str(properties.get("ALIAS", "")).strip()
        mnum = str(properties.get("MNUM", "")).strip()
        if "UJC100" not in mnum or not geometry.intersects(aoi_native):
            continue
        clipped = geometry.intersection(aoi_native)
        if clipped.is_empty or clipped.area < 1.0:
            continue
        display_name = alias.removesuffix("구역") if alias else "이름없는 소하천"
        clipped_wgs = transform(native_to_wgs, clipped)
        clipped_local = transform(to_local, clipped_wgs)
        item = {
            "id": f"smallriver_{len(small_zones) + 1:02d}",
            "name": display_name,
            "official_alias": alias,
            "source_layer": "UJ301",
            "classification": "UJC100",
            "mnum": mnum,
            "intersection_area_m2": round(clipped.area, 1),
            "polygons": polygon_loops(clipped_local),
        }
        small_zones.append(item)
        zone_native[display_name] = clipped

    small_zones.sort(key=lambda item: (-item["intersection_area_m2"], item["name"]))
    zones.extend(small_zones)

    osm = load_json(OSM_PATH)
    centerlines = []
    overlap_checks = []
    for feature in osm.get("features", []):
        properties = feature.get("properties") or {}
        source_name = properties.get("name")
        if source_name not in {"미호강", "노송천"}:
            continue
        geometry_wgs = shape(feature["geometry"]).intersection(aoi_wgs)
        if geometry_wgs.is_empty:
            continue
        display_name = "태성천" if source_name == "노송천" else source_name
        geometry_local = transform(to_local, geometry_wgs)
        width = 76.0 if display_name == "미호강" else 11.0
        centerlines.append(
            {
                "id": f"centerline_{'miho' if display_name == '미호강' else 'taeseong'}",
                "name": display_name,
                "source_name": source_name,
                "source": "OpenStreetMap",
                "review": properties.get("review"),
                "visual_width_m": width,
                "parts": line_parts(geometry_local),
            }
        )
        target = zone_native.get(display_name)
        if target is not None:
            geometry_native = transform(wgs_to_native, geometry_wgs)
            total_length = geometry_native.length
            overlap_length = geometry_native.intersection(target).length
            overlap_checks.append(
                {
                    "centerline": source_name,
                    "official_zone": display_name,
                    "length_m": round(total_length, 1),
                    "overlap_m": round(overlap_length, 1),
                    "coverage_percent": (
                        round(overlap_length / total_length * 100.0, 1)
                        if total_length
                        else 0.0
                    ),
                }
            )

    names = [item["name"] for item in small_zones]
    expected_names = {
        "태성천",
        "다락천",
        "도장골천",
        "탑연천",
        "월곡천",
        "당산천",
        "궁현천",
        "부량천",
        "상발천",
    }
    if len([item for item in zones if item["source_layer"] == "UJ201"]) != 1:
        raise RuntimeError("Expected exactly one official Miho river zone")
    if set(names) != expected_names:
        raise RuntimeError(
            f"Unexpected UJ301 AOI names: expected={sorted(expected_names)}, actual={sorted(names)}"
        )
    if {item["name"] for item in centerlines} != {"미호강", "태성천"}:
        raise RuntimeError("Expected Miho and Taeseong centerlines")

    payload = {
        "schema_version": 1,
        "coordinate_system": "Gangnae local metres",
        "terrain_bounds_wgs84": bounds,
        "origin_wgs84": [centre_lon, centre_lat],
        "metres_per_degree": {
            "longitude": metres_per_degree_lon,
            "latitude": METRES_PER_DEGREE_LAT,
        },
        "terrain": {
            "elevation_min_m": report["elevation_min_m"],
            "elevation_max_m": report["elevation_max_m"],
            "vertical_exaggeration": report["vertical_exaggeration"],
            "dimensions_m": report["terrain_dimensions_m"],
        },
        "official_zones": zones,
        "centerlines": centerlines,
        "validation": {
            "official_river_zone_count": 1,
            "official_small_river_zone_count": len(small_zones),
            "centerline_count": len(centerlines),
            "small_river_names": names,
            "overlap_checks": overlap_checks,
            "osm_name_note": "OSM 노송천 중심선은 공식 태성천구역과 대응함",
        },
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[hydro-geometry] ok zones={len(zones)} centerlines={len(centerlines)} "
        f"wrote={OUTPUT_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
