#!/usr/bin/env python3
"""Prepare three auditable V16 inundation states from the official V13 dataset.

The intermediate state is a visual reveal of the official final extent. It is
not presented as a hydraulic time-series prediction.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Polygon, shape
from shapely.ops import unary_union


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
SOURCE_PATH = ROOT / "data" / "processed" / "osong_official_inundation_v13.json"
RIVER_PATH = ROOT / "data" / "processed" / "osong_river_surface_v15.json"
FIELD_PATH = ROOT / "config" / "osong_farmland_v11.json"
OUTPUT_PATH = ROOT / "data" / "processed" / "osong_inundation_v16.json"
REPORT_PATH = ROOT / "output" / "inundation_v16" / "preparation_report.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def polygon_parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [part for part in geometry.geoms if part.geom_type == "Polygon"]


def geometry_from_progression(item: dict):
    polygons = []
    for source in item["polygons"]:
        polygon = Polygon(source["exterior"]).buffer(0)
        if not polygon.is_empty:
            polygons.append(polygon)
    return unary_union(polygons).buffer(0) if polygons else Polygon()


def serialise_polygons(geometry):
    result = []
    for part in polygon_parts(geometry):
        if part.area < 8.0:
            continue
        simplified = part.simplify(1.5, preserve_topology=True)
        result.append({
            "exterior": [
                [round(float(x), 3), round(float(y), 3)]
                for x, y in list(simplified.exterior.coords)[:-1]
            ],
            "area_m2": round(float(part.area), 1),
        })
    return result


def local_field(field: dict, origin_utm):
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
    source = shape(field["geometry"])
    points = []
    for lon, lat in source.exterior.coords:
        x, y = transformer.transform(float(lon), float(lat))
        points.append((x - origin_utm[0], y - origin_utm[1]))
    return Polygon(points).buffer(0)


def build_stage(code: str, label: str, source_item: dict | None, field_geometry, source: dict):
    geometry = geometry_from_progression(source_item) if source_item else Polygon()
    affected_area = geometry.intersection(field_geometry).area if not geometry.is_empty else 0.0
    affected_percent = affected_area / field_geometry.area * 100.0
    return {
        "code": code,
        "label": label,
        "source_progression_step": int(source_item["step"]) if source_item else 0,
        "official_extent_fraction": float(source_item["official_extent_fraction"]) if source_item else 0.0,
        "visual_depth_cap_m": float(source_item["visual_depth_m"]) if source_item else 0.0,
        "total_area_m2": round(float(geometry.area), 1),
        "field_affected_area_m2": round(float(affected_area), 1),
        "field_affected_percent": round(float(affected_percent), 1),
        "polygons": serialise_polygons(geometry),
        "hydraulic_time_series": False,
        "official_final_extent": bool(source_item and int(source_item["step"]) == 10),
    }


def main():
    source = load_json(SOURCE_PATH)
    river = load_json(RIVER_PATH)
    field = load_json(FIELD_PATH)
    origin_utm = [float(value) for value in river["origin_utm"]]
    field_geometry = local_field(field, origin_utm)
    intermediate_source = source["progression"][4]
    maximum_source = source["progression"][9]
    stages = [
        build_stage("normal", "평상시", None, field_geometry, source),
        build_stage("intermediate", "중간 침수 시각화", intermediate_source, field_geometry, source),
        build_stage("maximum", "공식 최대 침수범위", maximum_source, field_geometry, source),
    ]
    maximum = stages[-1]
    source_geometry_percent = float(maximum_source["field_affected_percent"])
    if abs(maximum["field_affected_percent"] - source_geometry_percent) > 0.2:
        raise RuntimeError("Recomputed maximum field impact does not match the V13 source geometry")

    payload = {
        "schema_version": "1.0",
        "dataset_id": "OSONG-INUNDATION-V16",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "crs": river["crs"],
        "origin_utm": origin_utm,
        "source": source["source"],
        "method": {
            "name": "three_state_official_floodmap_visualisation",
            "normal": "V15 continuous baseline river only",
            "intermediate": "V13 step 5; gradual reveal constrained inside official final extent",
            "maximum": "official 100-year national-river flood-map final extent",
            "hydraulic_time_series": False,
            "realtime_stage_applied": False,
            "visual_depth_cap_m": float(source["method"]["visual_depth_cap_m"]),
            "visual_depth_cap_reason": source["method"]["cap_reason"],
        },
        "field": {
            "field_id": field["field_id"],
            "display_name": field["display_name"],
            "geometry_role": "OSM landuse=farmland reference, not cadastral parcel",
            "area_m2": round(float(field_geometry.area), 1),
            "official_pixel_affected_percent": float(source["field"]["official_flood_affected_percent"]),
            "maximum_geometry_affected_percent": maximum["field_affected_percent"],
            "depth_class_counts": source["field"]["depth_class_counts"],
            "maximum_official_class_code": source["field"]["maximum_official_class_code"],
            "maximum_official_class_label": source["field"]["maximum_official_class_label"],
        },
        "stages": stages,
        "limitations": [
            "The registered field is an OSM farmland polygon, not a cadastral parcel.",
            "The intermediate state is a visual reveal inside the official final extent, not a hydraulic forecast timestamp.",
            "The maximum state is a 100-year frequency hazard-map scenario, not the footprint of the next rainfall event.",
            "Realtime river-stage data is not applied in V16.",
        ],
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "status": "ok",
        "dataset": str(OUTPUT_PATH),
        "stages": [
            {
                "code": item["code"],
                "area_m2": item["total_area_m2"],
                "field_affected_percent": item["field_affected_percent"],
                "polygon_count": len(item["polygons"]),
            }
            for item in stages
        ],
        "maximum_official_pixel_affected_percent": payload["field"]["official_pixel_affected_percent"],
        "realtime_applied": False,
        "video_rendered": False,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
