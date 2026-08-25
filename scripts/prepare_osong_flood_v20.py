#!/usr/bin/env python3
"""Prepare V20 continuous river and ten terrain-conforming flood meshes.

The official 100-year flood-map extent is used as an internal spatial bound.
The output contains blue water surfaces only; it does not reproduce the
hazard-map colour overlay and does not claim a hydraulic timestamp forecast.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Polygon, box, shape
from shapely.ops import triangulate, unary_union

ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
SOURCE_PATH = ROOT / "data" / "processed" / "osong_official_inundation_v13.json"
RIVER_PATH = ROOT / "data" / "processed" / "osong_river_surface_v15.json"
OUTER_PATH = ROOT / "data" / "processed" / "osong_shelter_v19_outer.json"
FIELD_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_hq_v11_context.json"
FIELD_CONFIG_PATH = ROOT / "config" / "osong_farmland_v11.json"
V19_MANIFEST_PATH = ROOT / "data" / "processed" / "osong_shelter_v19_manifest.json"
OUTPUT_PATH = ROOT / "data" / "processed" / "osong_flood_v20.json"
MANIFEST_PATH = ROOT / "data" / "processed" / "osong_flood_v20_manifest.json"
REPORT_PATH = ROOT / "output" / "flood_v20" / "preparation_report.json"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class TerrainSampler:
    def __init__(self, terrain, offset=(0.0, 0.0)):
        self.rows = int(terrain["rows"])
        self.columns = int(terrain["columns"])
        self.vertices = terrain["vertices"]
        self.offset = tuple(map(float, offset))
        xs = [float(item[0]) + self.offset[0] for item in self.vertices]
        ys = [float(item[1]) + self.offset[1] for item in self.vertices]
        self.min_x, self.max_x = min(xs), max(xs)
        self.min_y, self.max_y = min(ys), max(ys)

    def covers(self, x, y):
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y

    def z(self, x, y):
        x -= self.offset[0]
        y -= self.offset[1]
        local_xs = (self.min_x - self.offset[0], self.max_x - self.offset[0])
        local_ys = (self.min_y - self.offset[1], self.max_y - self.offset[1])
        u = max(0.0, min(1.0, (x - local_xs[0]) / (local_xs[1] - local_xs[0])))
        v = max(0.0, min(1.0, (local_ys[1] - y) / (local_ys[1] - local_ys[0])))
        cf, rf = u * (self.columns - 1), v * (self.rows - 1)
        c0 = min(self.columns - 2, max(0, math.floor(cf)))
        r0 = min(self.rows - 2, max(0, math.floor(rf)))
        dc, dr = cf - c0, rf - r0

        def value(row, column):
            return float(self.vertices[row * self.columns + column][2])

        z00, z10 = value(r0, c0), value(r0, c0 + 1)
        z01, z11 = value(r0 + 1, c0), value(r0 + 1, c0 + 1)
        north = z00 * (1.0 - dc) + z10 * dc
        south = z01 * (1.0 - dc) + z11 * dc
        return north * (1.0 - dr) + south * dr


def polygon_parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [item for item in geometry.geoms if item.geom_type == "Polygon"]


def progression_geometry(item):
    polygons = [Polygon(source["exterior"]).buffer(0) for source in item["polygons"]]
    return unary_union([item for item in polygons if not item.is_empty]).buffer(0)


def local_field(field, origin_utm):
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
    source = shape(field["geometry"])
    points = []
    for lon, lat in source.exterior.coords:
        x, y = transformer.transform(float(lon), float(lat))
        points.append((x - origin_utm[0], y - origin_utm[1]))
    return Polygon(points).buffer(0)


def mesh_geometry(geometry, terrain_z, z_offset, cell_m=24.0):
    if geometry.is_empty:
        return {"vertices": [], "faces": [], "area_m2": 0.0}
    minx, miny, maxx, maxy = geometry.bounds
    start_x = math.floor(minx / cell_m) * cell_m
    start_y = math.floor(miny / cell_m) * cell_m
    vertex_map = {}
    vertices, faces = [], []

    def index_for(x, y):
        key = (round(float(x), 4), round(float(y), 4))
        if key not in vertex_map:
            vertex_map[key] = len(vertices)
            vertices.append([key[0], key[1], round(terrain_z(*key) + z_offset, 4)])
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
                    face = [index_for(px, py) for px, py in list(triangle.exterior.coords)[:3]]
                    if len(set(face)) == 3:
                        faces.append(face)
            y += cell_m
        x += cell_m
    return {"vertices": vertices, "faces": faces, "area_m2": round(float(geometry.area), 1)}


def main():
    source = load_json(SOURCE_PATH)
    river_source = load_json(RIVER_PATH)
    outer_context = load_json(OUTER_PATH)
    field_context = load_json(FIELD_CONTEXT_PATH)
    field_config = load_json(FIELD_CONFIG_PATH)
    v19_manifest = load_json(V19_MANIFEST_PATH)

    field_origin = tuple(map(float, v19_manifest["field_origin_utm52n"]))
    outer_origin = tuple(map(float, v19_manifest["outer_origin_utm52n"]))
    outer_offset = (outer_origin[0] - field_origin[0], outer_origin[1] - field_origin[1])
    outer = TerrainSampler(outer_context["terrain"], outer_offset)
    core = TerrainSampler(field_context["terrain"])
    exaggeration = float(outer_context["terrain"]["vertical_exaggeration"])
    core_z = (
        float(field_context["terrain"]["elevation_min_m"])
        - float(outer_context["terrain"]["elevation_min_m"])
    ) * exaggeration + 0.18

    def terrain_z(x, y):
        value = outer.z(x, y)
        if core.covers(x, y):
            value = max(value, core.z(x, y) + core_z)
        return value

    river_geometry = Polygon(river_source["water_surface"]["boundary_xy"]).buffer(0)
    if river_geometry.is_empty:
        raise RuntimeError("V15 continuous river boundary is empty")
    river_mesh = mesh_geometry(river_geometry, terrain_z, z_offset=0.52, cell_m=20.0)

    field_geometry = local_field(field_config, field_origin)
    stages = []
    for item in source["progression"]:
        geometry = progression_geometry(item)
        affected = geometry.intersection(field_geometry).area / field_geometry.area * 100.0
        stages.append({
            "step": int(item["step"]),
            "official_extent_fraction": float(item["official_extent_fraction"]),
            "visual_depth_cap_m": float(item["visual_depth_m"]),
            "field_affected_percent": round(float(affected), 1),
            "water_mesh": mesh_geometry(
                geometry,
                terrain_z,
                z_offset=0.70 + float(item["visual_depth_m"]) * 0.035,
                cell_m=24.0,
            ),
        })
    if len(stages) != 10 or not stages[-1]["water_mesh"]["faces"]:
        raise RuntimeError("V20 requires ten non-empty official-bound flood stages")

    payload = {
        "schema_version": "1.0",
        "dataset_id": "OSONG-FLOOD-V20",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "crs": "EPSG:32652",
        "origin_policy": "metre offsets from the V19 registered-field origin",
        "field_origin_utm52n": list(field_origin),
        "outer_origin_offset_m": [round(v, 3) for v in outer_offset],
        "terrain_surface_method": "V19 12km terrain with V11 field HQ max-surface overlay",
        "river": {
            "source_dataset": river_source["dataset_id"],
            "source_provider": river_source["source_geometry"]["provider"],
            "geometry_role": "continuous visual baseline river surface",
            "hydraulic_survey_boundary": False,
            "mesh": river_mesh,
        },
        "flood": {
            "source": source["source"],
            "spatial_constraint": "inside official 100-year flood-map final extent",
            "display_policy": "blue water only; official hazard-map class colours hidden",
            "hydraulic_time_series": False,
            "stages": stages,
        },
        "field": {
            "field_id": field_config["field_id"],
            "geometry_role": "OSM farmland reference, not cadastral parcel",
            "area_m2": round(float(field_geometry.area), 1),
            "maximum_affected_percent": stages[-1]["field_affected_percent"],
        },
        "limitations": [
            "The ten stages are a gradual visual reveal inside the official final extent, not hydraulic timestamps.",
            "The 100-year flood map constrains the maximum footprint but its class-colour overlay is not displayed.",
            "The baseline river uses OSM planform geometry and terrain draping, not surveyed bathymetry.",
            "The registered field is OSM agricultural land cover, not a cadastral ownership parcel.",
        ],
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tracked = [SOURCE_PATH, RIVER_PATH, OUTER_PATH, FIELD_CONTEXT_PATH, FIELD_CONFIG_PATH, OUTPUT_PATH]
    manifest = {
        "schema_version": "1.0",
        "dataset_id": "OSONG-FLOOD-V20-MANIFEST",
        "generated_at_utc": payload["generated_at_utc"],
        "status": "prepared_without_blender_or_video",
        "source_v19_blend": str(ROOT / "blender" / "osong_shelter_v19.blend"),
        "source_v19_unchanged": True,
        "hazard_map_overlay_visible": False,
        "hydraulic_time_series": False,
        "files": [
            {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in tracked
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "status": "ok",
        "dataset": str(OUTPUT_PATH),
        "manifest": str(MANIFEST_PATH),
        "river_vertices": len(river_mesh["vertices"]),
        "river_faces": len(river_mesh["faces"]),
        "stages": [
            {
                "step": item["step"],
                "vertices": len(item["water_mesh"]["vertices"]),
                "faces": len(item["water_mesh"]["faces"]),
                "field_affected_percent": item["field_affected_percent"],
            }
            for item in stages
        ],
        "maximum_field_affected_percent": stages[-1]["field_affected_percent"],
        "hazard_map_overlay_visible": False,
        "video_rendered": False,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
