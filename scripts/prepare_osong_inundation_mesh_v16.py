#!/usr/bin/env python3
"""Create terrain-conforming flood and affected-field meshes for V16."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Polygon, box, shape
from shapely.ops import triangulate, unary_union


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
STAGE_PATH = ROOT / "data" / "processed" / "osong_inundation_v16.json"
OUTER_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_context_v14_3km.json"
CORE_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_hq_v11_context.json"
FIELD_PATH = ROOT / "config" / "osong_farmland_v11.json"
OUTPUT_PATH = ROOT / "data" / "processed" / "osong_inundation_mesh_v16.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class TerrainSampler:
    def __init__(self, terrain):
        self.rows = int(terrain["rows"])
        self.columns = int(terrain["columns"])
        self.vertices = terrain["vertices"]
        xs = [float(item[0]) for item in self.vertices]
        ys = [float(item[1]) for item in self.vertices]
        self.min_x, self.max_x = min(xs), max(xs)
        self.min_y, self.max_y = min(ys), max(ys)

    def covers(self, x, y):
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y

    def z(self, x, y):
        u = max(0.0, min(1.0, (x - self.min_x) / (self.max_x - self.min_x)))
        v = max(0.0, min(1.0, (self.max_y - y) / (self.max_y - self.min_y)))
        column_f = u * (self.columns - 1)
        row_f = v * (self.rows - 1)
        c0 = min(self.columns - 2, max(0, math.floor(column_f)))
        r0 = min(self.rows - 2, max(0, math.floor(row_f)))
        dc, dr = column_f - c0, row_f - r0

        def value(row, column):
            return float(self.vertices[row * self.columns + column][2])

        z00, z10 = value(r0, c0), value(r0, c0 + 1)
        z01, z11 = value(r0 + 1, c0), value(r0 + 1, c0 + 1)
        return (z00 * (1.0 - dc) + z10 * dc) * (1.0 - dr) + (z01 * (1.0 - dc) + z11 * dc) * dr


def polygon_parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [item for item in geometry.geoms if item.geom_type == "Polygon"]


def stage_geometry(stage):
    polygons = [Polygon(item["exterior"]).buffer(0) for item in stage["polygons"]]
    return unary_union([item for item in polygons if not item.is_empty]).buffer(0)


def local_field(field, origin_utm):
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
    geometry = shape(field["geometry"])
    points = []
    for lon, lat in geometry.exterior.coords:
        x, y = transformer.transform(float(lon), float(lat))
        points.append((x - origin_utm[0], y - origin_utm[1]))
    return Polygon(points).buffer(0)


def mesh_geometry(geometry, outer, core, core_z, z_offset, cell_m=23.4375):
    if geometry.is_empty:
        return {"vertices": [], "faces": [], "area_m2": 0.0}
    minx, miny, maxx, maxy = geometry.bounds
    start_x = math.floor(minx / cell_m) * cell_m
    start_y = math.floor(miny / cell_m) * cell_m
    vertex_map = {}
    vertices = []
    faces = []

    def terrain_z(x, y):
        value = outer.z(x, y)
        if core.covers(x, y):
            value = max(value, core.z(x, y) + core_z)
        return value + z_offset

    def vertex_index(x, y):
        key = (round(float(x), 4), round(float(y), 4))
        if key not in vertex_map:
            vertex_map[key] = len(vertices)
            vertices.append([key[0], key[1], round(terrain_z(*key), 4)])
        return vertex_map[key]

    x = start_x
    while x < maxx:
        y = start_y
        while y < maxy:
            clipped = geometry.intersection(box(x, y, x + cell_m, y + cell_m))
            for part in polygon_parts(clipped):
                for triangle in triangulate(part):
                    if triangle.area < 0.01 or not part.covers(triangle.representative_point()):
                        continue
                    coords = list(triangle.exterior.coords)[:3]
                    face = [vertex_index(px, py) for px, py in coords]
                    if len(set(face)) == 3:
                        faces.append(face)
            y += cell_m
        x += cell_m
    return {
        "vertices": vertices,
        "faces": faces,
        "area_m2": round(float(geometry.area), 1),
    }


def main():
    stages = load_json(STAGE_PATH)
    outer_context = load_json(OUTER_CONTEXT_PATH)
    core_context = load_json(CORE_CONTEXT_PATH)
    field_config = load_json(FIELD_PATH)
    outer = TerrainSampler(outer_context["terrain"])
    core = TerrainSampler(core_context["terrain"])
    exaggeration = float(outer_context["terrain"]["vertical_exaggeration"])
    core_z = (
        float(core_context["terrain"]["elevation_min_m"])
        - float(outer_context["terrain"]["elevation_min_m"])
    ) * exaggeration + 0.08
    field = local_field(field_config, stages["origin_utm"])
    rendered_stages = []
    for stage in stages["stages"]:
        if stage["code"] == "normal":
            rendered_stages.append({**stage, "flood_mesh": None, "field_impact_mesh": None})
            continue
        geometry = stage_geometry(stage)
        impact = geometry.intersection(field).buffer(0)
        flood_mesh = mesh_geometry(
            geometry,
            outer,
            core,
            core_z,
            z_offset=0.72 + float(stage["visual_depth_cap_m"]) * 0.025,
        )
        impact_mesh = mesh_geometry(
            impact,
            outer,
            core,
            core_z,
            z_offset=1.80 + float(stage["visual_depth_cap_m"]) * 0.025,
            cell_m=15.625,
        )
        rendered_stages.append({
            **stage,
            "flood_mesh": flood_mesh,
            "field_impact_mesh": impact_mesh,
        })
    payload = {
        "schema_version": "1.0",
        "dataset_id": "OSONG-INUNDATION-MESH-V16",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_dataset": stages["dataset_id"],
        "terrain_surface_method": "cell-clipped triangulation draped to max of V14 outer and V11 core terrain",
        "core_alignment_z": round(core_z, 4),
        "stages": rendered_stages,
        "realtime_applied": False,
        "video_rendered": False,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    summary = {
        "status": "ok",
        "dataset": str(OUTPUT_PATH),
        "stages": [
            {
                "code": item["code"],
                "flood_vertices": len(item["flood_mesh"]["vertices"]) if item["flood_mesh"] else 0,
                "flood_faces": len(item["flood_mesh"]["faces"]) if item["flood_mesh"] else 0,
                "impact_vertices": len(item["field_impact_mesh"]["vertices"]) if item["field_impact_mesh"] else 0,
                "impact_faces": len(item["field_impact_mesh"]["faces"]) if item["field_impact_mesh"] else 0,
            }
            for item in rendered_stages
        ],
        "video_rendered": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
