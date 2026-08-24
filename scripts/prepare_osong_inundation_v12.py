#!/usr/bin/env python3
"""Generate a terrain-constrained 10-step visual flood progression for V12.

This produces reproducible MVP geometry from the V11 OSM river surface and
SRTM terrain. It does not reuse the old Gangnae V5 inundation percentages.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
CONTEXT_PATH = ROOT / "data" / "processed" / "osong_hq_v11_context.json"
PILOT_PATH = ROOT / "config" / "pilot_area_v11.json"
OUTPUT_PATH = ROOT / "data" / "processed" / "osong_inundation_v12.json"
FIELD_RESULT_PATH = ROOT / "output" / "guidance_v12" / "osong_inundation_v12_field_result.json"
INPUT_PATH = ROOT / "config" / "osong_guidance_input_v12.json"

PROGRESSION_STEPS = 10
TERRAIN_STRIDE = 2
AOI = box(-500, -500, 500, 500)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def polygon_parts(geometry):
    if isinstance(geometry, Polygon):
        return [geometry]
    return [part for part in getattr(geometry, "geoms", []) if isinstance(part, Polygon)]


def terrain_cells(terrain: dict):
    rows = int(terrain["rows"])
    columns = int(terrain["columns"])
    vertices = terrain["vertices"]

    def vertex(row, column):
        return vertices[row * columns + column]

    cells = []
    for row in range(0, rows - 1, TERRAIN_STRIDE):
        next_row = min(rows - 1, row + TERRAIN_STRIDE)
        for column in range(0, columns - 1, TERRAIN_STRIDE):
            next_column = min(columns - 1, column + TERRAIN_STRIDE)
            corners = [
                vertex(row, column),
                vertex(row, next_column),
                vertex(next_row, next_column),
                vertex(next_row, column),
            ]
            polygon = Polygon([(item[0], item[1]) for item in corners])
            centre = polygon.centroid
            elevation = sum(float(item[2]) for item in corners) / 4.0
            cells.append((polygon, centre, elevation))
    return cells


def serialise_polygons(geometry):
    result = []
    for polygon in polygon_parts(geometry):
        if polygon.area < 8:
            continue
        result.append({
            "exterior": [
                [round(x, 3), round(y, 3)]
                for x, y in list(polygon.exterior.coords)[:-1]
            ],
            "area_m2": round(polygon.area, 2),
        })
    return result


def connected_to_river(geometry, river, previous):
    keep = []
    connector = river.buffer(12)
    if previous is not None:
        connector = unary_union([connector, previous.buffer(3)])
    for part in polygon_parts(geometry):
        if part.intersects(connector):
            keep.append(part)
    return unary_union(keep) if keep else river


def build_progression(context: dict):
    river = unary_union([Polygon(item["polygon"]) for item in context["water_polygons"]]).buffer(0)
    field = Polygon(context["field"]["polygon"]).buffer(0)
    cells = terrain_cells(context["terrain"])
    progression = []
    previous = None

    for index in range(1, PROGRESSION_STEPS + 1):
        progress = index / PROGRESSION_STEPS
        buffer_distance = 50.0 + 350.0 * progress
        elevation_cutoff = 12.5 + 9.5 * progress
        reach = river.buffer(buffer_distance)
        selected = [
            polygon
            for polygon, centre, elevation in cells
            if reach.contains(centre) and elevation <= elevation_cutoff
        ]
        merged = unary_union([river, *selected]).buffer(5).buffer(-5).intersection(AOI)
        merged = connected_to_river(merged, river, previous).intersection(AOI).buffer(0)
        if previous is not None:
            merged = unary_union([previous, merged]).buffer(0)
        previous = merged
        field_area = merged.intersection(field).area
        progression.append({
            "step": index,
            "progress": round(progress, 2),
            "buffer_distance_m": round(buffer_distance, 1),
            "relative_elevation_cutoff_m": round(elevation_cutoff, 2),
            "total_area_m2": round(merged.area, 1),
            "field_affected_area_m2": round(field_area, 1),
            "field_affected_percent": round(field_area / field.area * 100.0, 1),
            "polygons": serialise_polygons(merged.simplify(1.0, preserve_topology=True)),
        })
    return progression, field, river


def main():
    context = load_json(CONTEXT_PATH)
    pilot = load_json(PILOT_PATH)
    progression, field, river = build_progression(context)

    areas = [item["total_area_m2"] for item in progression]
    impacts = [item["field_affected_percent"] for item in progression]
    if any(b < a for a, b in zip(areas, areas[1:])):
        raise RuntimeError("Flood area is not monotonic")
    if any(b < a for a, b in zip(impacts, impacts[1:])):
        raise RuntimeError("Field impact is not monotonic")
    if impacts[-1] < 10.0:
        raise RuntimeError(f"Final field impact is too small for the selected scene: {impacts[-1]}%")

    milestones = {
        "attention": progression[2],
        "warning": progression[5],
        "serious": progression[9],
    }
    result = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scene": "Osong_Story_V12",
        "pilot_id": pilot["pilot_id"],
        "selected_candidate": "C19",
        "crs": context["georeference"]["crs"],
        "origin_wgs84": context["georeference"]["origin_wgs84"],
        "method": {
            "name": "terrain_constrained_visual_flood_progression",
            "river_source": "OpenStreetMap merged river surface",
            "terrain_source": "SRTM 1 arc-second",
            "terrain_stride": TERRAIN_STRIDE,
            "note": "MVP visual progression; replace with a validated national-river inundation raster for production depth claims.",
        },
        "field": {
            "field_id": context["field"]["field_id"],
            "source_element_id": context["field"]["source_element_id"],
            "area_m2": round(field.area, 1),
            "geometry_role": context["field"]["role"],
        },
        "river_area_m2": round(river.area, 1),
        "progression": progression,
        "milestones": milestones,
        "validation": {
            "step_count": len(progression),
            "monotonic_area": True,
            "monotonic_field_impact": True,
            "final_field_affected_percent": impacts[-1],
            "old_gangnae_results_reused": False,
        },
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIELD_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    field_result = {
        "status": "ok",
        "pilot_id": pilot["pilot_id"],
        "field_id": context["field"]["field_id"],
        "scenario_method": result["method"],
        "scenario_results": {
            name: {
                "progression_step": item["step"],
                "inundated_area_m2": item["field_affected_area_m2"],
                "inundated_percent": item["field_affected_percent"],
            }
            for name, item in milestones.items()
        },
        "source_path": str(OUTPUT_PATH),
    }
    FIELD_RESULT_PATH.write_text(
        json.dumps(field_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    guidance_input = {
        "schema_version": "1.0",
        "mode": "v12_data_based_mvp",
        "recipient_label": "오송읍 파일럿 농업인",
        "location_label": "충북 청주시 흥덕구 오송읍 미호강 하류",
        "field_id": context["field"]["field_id"],
        "pilot_id": pilot["pilot_id"],
        "forecast": {
            "source": "기상청 단기예보 연동 입력",
            "decision_time_label": "오늘 오전 6시 30분",
            "rain_start_label": "내일 새벽 5시",
            "predicted_24h_rain_mm": 80,
            "is_live": False,
        },
        "hydro": pilot["water_level_stations"],
        "digital_twin_blend": str(ROOT / "blender" / "osong_hq_v11.blend"),
        "field_result": str(FIELD_RESULT_PATH),
        "voice": {"name": "Yuna", "rate": 200},
        "target_duration_seconds": 60,
    }
    INPUT_PATH.write_text(
        json.dumps(guidance_input, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "status": "ok",
        "progression_steps": len(progression),
        "field_impacts_percent": impacts,
        "milestones": {
            name: value["field_affected_percent"] for name, value in milestones.items()
        },
        "output": str(OUTPUT_PATH),
        "field_result": str(FIELD_RESULT_PATH),
        "guidance_input": str(INPUT_PATH),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
