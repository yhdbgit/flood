#!/usr/bin/env python3
"""Prepare the selective high-detail V21 field/river visual core.

V21 keeps the V20 story/camera contract but replaces the 1 km field core with
a 1.5 km z19 imagery core and a carved, continuously graded Miho River.  The
water surface is a visual engineering surface, not surveyed bathymetry or a
hydraulic time series.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random

from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon, box, shape
from shapely.ops import triangulate, unary_union


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
BASE_SCRIPT = ROOT / "scripts" / "prepare_gangnae_hq_v10.py"
FIELD_CONFIG_PATH = ROOT / "config" / "osong_farmland_v11.json"
FIELD_V11_PATH = ROOT / "data" / "processed" / "osong_hq_v11_context.json"
OUTER_V19_PATH = ROOT / "data" / "processed" / "osong_shelter_v19_outer.json"
V19_MANIFEST_PATH = ROOT / "data" / "processed" / "osong_shelter_v19_manifest.json"
RIVER_V15_PATH = ROOT / "data" / "processed" / "osong_river_surface_v15.json"
FLOOD_V13_PATH = ROOT / "data" / "processed" / "osong_official_inundation_v13.json"
OSM_RAW_PATH = ROOT / "data" / "gis" / "pilot_selection_v11" / "expanded_osm_raw.json"

DATA_DIR = ROOT / "data" / "gis" / "osong_visual_v21" / "field_river_hq_1500m"
AERIAL_PATH = DATA_DIR / "esri_world_imagery_z19.jpg"
AERIAL_META_PATH = DATA_DIR / "esri_world_imagery_z19.json"
ATTRIBUTION_PATH = DATA_DIR / "ATTRIBUTION.txt"
CONTEXT_PATH = ROOT / "data" / "processed" / "osong_visual_v21_context.json"
MANIFEST_PATH = ROOT / "data" / "processed" / "osong_visual_v21_manifest.json"
REPORT_PATH = ROOT / "output" / "visual_v21" / "preparation_report.json"

CORE_SIZE_M = 1500.0
HALF = CORE_SIZE_M / 2.0
GRID = 257
AERIAL_ZOOM = 19
VERTICAL_EXAGGERATION = 1.35
CHANNEL_DEPTH_M = 2.4
MAX_WATER_SLOPE = 0.0015

TO_WGS = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)


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
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [part for part in geometry.geoms if part.geom_type == "Polygon"]


def bounds_for(origin):
    west, south = TO_WGS.transform(origin[0] - HALF, origin[1] - HALF)
    east, north = TO_WGS.transform(origin[0] + HALF, origin[1] + HALF)
    return [west, south, east, north]


def exact_terrain(base, origin):
    values = base.read_hgt()
    raw = []
    elevations = []
    for row in range(GRID):
        y = HALF - CORE_SIZE_M * row / (GRID - 1)
        for column in range(GRID):
            x = -HALF + CORE_SIZE_M * column / (GRID - 1)
            lon, lat = TO_WGS.transform(origin[0] + x, origin[1] + y)
            elevation = float(base.sample_hgt(values, lon, lat))
            raw.append([x, y, elevation])
            elevations.append(elevation)
    minimum = min(elevations)
    return {
        "rows": GRID,
        "columns": GRID,
        "source": str(base.HGT_PATH),
        "source_resolution": "SRTM 1 arc-second, approximately 30 m; resampled only",
        "mesh_spacing_m": round(CORE_SIZE_M / (GRID - 1), 4),
        "elevation_min_m": minimum,
        "elevation_max_m": max(elevations),
        "vertical_exaggeration": VERTICAL_EXAGGERATION,
        "vertices": [
            [round(x, 4), round(y, 4), round((z - minimum) * VERTICAL_EXAGGERATION, 4)]
            for x, y, z in raw
        ],
    }


class GridSampler:
    def __init__(self, terrain, offset=(0.0, 0.0)):
        self.rows = int(terrain["rows"])
        self.columns = int(terrain["columns"])
        self.vertices = terrain["vertices"]
        self.offset = tuple(map(float, offset))
        self.local_min_x = min(v[0] for v in self.vertices)
        self.local_max_x = max(v[0] for v in self.vertices)
        self.local_min_y = min(v[1] for v in self.vertices)
        self.local_max_y = max(v[1] for v in self.vertices)
        self.min_x = self.local_min_x + self.offset[0]
        self.max_x = self.local_max_x + self.offset[0]
        self.min_y = self.local_min_y + self.offset[1]
        self.max_y = self.local_max_y + self.offset[1]

    def covers(self, x, y):
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y

    def z(self, x, y):
        x -= self.offset[0]
        y -= self.offset[1]
        u = max(0.0, min(1.0, (x - self.local_min_x) / (self.local_max_x - self.local_min_x)))
        v = max(0.0, min(1.0, (self.local_max_y - y) / (self.local_max_y - self.local_min_y)))
        cf, rf = u * (self.columns - 1), v * (self.rows - 1)
        c0 = min(self.columns - 2, max(0, math.floor(cf)))
        r0 = min(self.rows - 2, max(0, math.floor(rf)))
        dc, dr = cf - c0, rf - r0

        def value(row, column):
            return float(self.vertices[row * self.columns + column][2])

        z00, z10 = value(r0, c0), value(r0, c0 + 1)
        z01, z11 = value(r0 + 1, c0), value(r0 + 1, c0 + 1)
        return (z00 * (1 - dc) + z10 * dc) * (1 - dr) + (z01 * (1 - dc) + z11 * dc) * dr


def river_geometry(origin, visual_bounds):
    # Use the original full OSM visible-water polygon instead of V15's 3 km
    # crop. This keeps the river outside the camera frame and avoids a visible
    # square cut at the selective-HQ boundary.
    osm = load_json(OSM_RAW_PATH)
    polygons = []
    centreline_ribbons = []
    for element in osm.get("elements", []):
        tags = element.get("tags", {})
        points = []
        for point in element.get("geometry", []):
            x, y = TO_UTM.transform(float(point["lon"]), float(point["lat"]))
            points.append((x - origin[0], y - origin[1]))
        if tags.get("natural") == "water" and tags.get("water") == "river" and len(points) >= 4:
            geometry = Polygon(points).buffer(0)
            if not geometry.is_empty:
                polygons.extend(polygon_parts(geometry))
        if tags.get("waterway") == "river" and tags.get("name") == "미호강" and len(points) >= 2:
            # A centreline ribbon fills missing OSM riverbank segments while the
            # polygon still supplies the real planform width and islands.
            full_width = max(70.0, float(tags.get("width", 0.0) or 0.0))
            centreline_ribbons.append(LineString(points).buffer(full_width / 2.0, cap_style=2, join_style=2))
    if not polygons or not centreline_ribbons:
        raise RuntimeError("No full OSM Miho River polygon/centreline pair was found")
    # The largest polygon is the main channel; centreline ribbons enforce
    # continuity where OSM riverbank coverage is incomplete.
    geometry = unary_union([max(polygons, key=lambda polygon: polygon.area), *centreline_ribbons]).buffer(0)
    geometry = geometry.intersection(box(*visual_bounds)).buffer(0)
    geometry = geometry.buffer(3.0, join_style=2).buffer(-3.0, join_style=2).simplify(0.8, preserve_topology=True)
    parts = [part for part in polygon_parts(geometry) if part.area >= 80]
    if not parts:
        raise RuntimeError("No usable Miho River water geometry intersects the V21 visual domain")
    return unary_union(parts).buffer(0)


def progression_geometry(item):
    polygons = [Polygon(source["exterior"]).buffer(0) for source in item["polygons"]]
    geometry = unary_union([polygon for polygon in polygons if not polygon.is_empty]).buffer(0)
    # Close narrow raster cracks and discard only tiny internal speckles. Large
    # dry islands remain because they may be meaningful high ground.
    geometry = geometry.buffer(35.0, join_style=2).buffer(-35.0, join_style=2).buffer(0)
    cleaned = []
    for polygon in polygon_parts(geometry):
        holes = [ring.coords[:] for ring in polygon.interiors if Polygon(ring).area >= 180.0]
        rebuilt = Polygon(polygon.exterior.coords[:], holes).buffer(0)
        cleaned.extend(part for part in polygon_parts(rebuilt) if part.area >= 80.0)
    return unary_union(cleaned).buffer(0)


def fit_water_plane(terrain, river):
    sampler = GridSampler(terrain)
    points = []
    minx, miny, maxx, maxy = river.bounds
    y = math.floor(miny / 18.0) * 18.0
    while y <= maxy:
        x = math.floor(minx / 18.0) * 18.0
        while x <= maxx:
            if river.covers(Point(x, y)):
                points.append((x, y, sampler.z(x, y)))
            x += 18.0
        y += 18.0
    if len(points) < 30:
        raise RuntimeError("Too few terrain samples to fit the V21 river surface")

    centre = (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )
    centred = [(p[0] - centre[0], p[1] - centre[1]) for p in points]
    covariance_xx = sum(x * x for x, _y in centred) / len(centred)
    covariance_yy = sum(y * y for _x, y in centred) / len(centred)
    covariance_xy = sum(x * y for x, y in centred) / len(centred)
    angle = 0.5 * math.atan2(2.0 * covariance_xy, covariance_xx - covariance_yy)
    axis = (math.cos(angle), math.sin(angle))
    t = [x * axis[0] + y * axis[1] for x, y in centred]
    z = [p[2] for p in points]
    bin_count = 14
    step = (max(t) - min(t)) / bin_count
    bins = [min(t) + step * index for index in range(bin_count + 1)]
    samples = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        values = sorted(value for value, position in zip(z, t) if lo <= position <= hi)
        if len(values) >= 3:
            percentile_index = min(len(values) - 1, round((len(values) - 1) * 0.18))
            samples.append(((lo + hi) / 2.0, float(values[percentile_index])))
    if len(samples) < 4:
        raise RuntimeError("V21 water-plane fit did not produce enough longitudinal bins")
    mean_t = sum(p[0] for p in samples) / len(samples)
    mean_z = sum(p[1] for p in samples) / len(samples)
    denominator = sum((p[0] - mean_t) ** 2 for p in samples)
    slope = sum((p[0] - mean_t) * (p[1] - mean_z) for p in samples) / denominator
    slope = max(-MAX_WATER_SLOPE, min(MAX_WATER_SLOPE, slope))
    intercept = mean_z - slope * mean_t
    # Raise the robust low line slightly so the surface sits above the carved bed.
    intercept = float(intercept + 0.35)
    a = slope * axis[0]
    b = slope * axis[1]
    c = intercept - a * centre[0] - b * centre[1]
    return {"a": a, "b": b, "c": c, "slope_m_per_m": abs(slope), "sample_count": len(points)}


def plane_z(plane, x, y):
    return float(plane["a"]) * x + float(plane["b"]) * y + float(plane["c"])


def carve_terrain(terrain, river, plane):
    original_z = [float(vertex[2]) for vertex in terrain["vertices"]]
    carved = []
    changed = 0
    for x, y, z in terrain["vertices"]:
        point = Point(float(x), float(y))
        target = float(z)
        if river.covers(point):
            edge_distance = point.distance(river.boundary)
            depth = min(CHANNEL_DEPTH_M, 0.45 + edge_distance * 0.16)
            target = min(target, plane_z(plane, x, y) - depth)
        if target < float(z) - 0.001:
            changed += 1
        carved.append([float(x), float(y), round(target, 4)])
    result = dict(terrain)
    result["vertices"] = carved
    result["channel_carve"] = {
        "method": "lower terrain vertices inside cleaned river polygon beneath a robust longitudinal water plane",
        "maximum_visual_depth_m": CHANNEL_DEPTH_M,
        "changed_vertex_count": changed,
        "original_z_range_scene_m": [round(min(original_z), 4), round(max(original_z), 4)],
        "carved_z_range_scene_m": [round(min(v[2] for v in carved), 4), round(max(v[2] for v in carved), 4)],
    }
    return result


def mesh_geometry(geometry, z_function, cell_m=10.0):
    vertices = []
    faces = []
    vertex_map = {}

    def index_for(x, y):
        key = (round(float(x), 4), round(float(y), 4))
        if key not in vertex_map:
            vertex_map[key] = len(vertices)
            vertices.append([key[0], key[1], round(z_function(*key), 4)])
        return vertex_map[key]

    for polygon in polygon_parts(geometry):
        minx, miny, maxx, maxy = polygon.bounds
        x = math.floor(minx / cell_m) * cell_m
        while x < maxx:
            y = math.floor(miny / cell_m) * cell_m
            while y < maxy:
                clipped = polygon.intersection(box(x, y, x + cell_m, y + cell_m))
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


def project_field(field, origin):
    geometry = shape(field["geometry"])
    points = []
    for lon, lat in geometry.exterior.coords:
        x, y = TO_UTM.transform(float(lon), float(lat))
        points.append([round(x - origin[0], 3), round(y - origin[1], 3)])
    return {
        "field_id": field["field_id"],
        "display_name": field["display_name"],
        "geometry_accuracy": field["geometry_accuracy"],
        "area_m2": round(float(Polygon(points).area), 1),
        "polygon": points[:-1] if points[0] == points[-1] else points,
    }


def vegetation_points(river, field, roads, terrain, field_align):
    exclusion = field.buffer(18.0)
    for road in roads:
        exclusion = unary_union([exclusion, LineString(road["path"]).buffer(max(3.0, road["width_m"] / 2 + 2.0))])
    ring = river.buffer(34.0).difference(river.buffer(7.0)).difference(exclusion).buffer(0)
    sampler = GridSampler(terrain)
    rng = random.Random(210825)
    points = []
    minx, miny, maxx, maxy = ring.bounds
    y = miny
    while y <= maxy:
        x = minx
        while x <= maxx:
            px = x + rng.uniform(-7.0, 7.0)
            py = y + rng.uniform(-7.0, 7.0)
            if ring.covers(Point(px, py)) and rng.random() < 0.56:
                points.append({
                    "x": round(px, 3),
                    "y": round(py, 3),
                    "z": round(sampler.z(px, py) + field_align, 3),
                    "height_m": round(rng.uniform(5.5, 11.5), 2),
                    "crown_m": round(rng.uniform(2.6, 5.2), 2),
                    "placement_accuracy": "procedural bank vegetation, not surveyed individual tree",
                })
            x += 24.0
        y += 24.0
    return points[:220]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    base = load_module("prepare_osong_visual_v21_base", BASE_SCRIPT)
    v19_manifest = load_json(V19_MANIFEST_PATH)
    field_config = load_json(FIELD_CONFIG_PATH)
    outer = load_json(OUTER_V19_PATH)
    origin = tuple(float(v) for v in v19_manifest["field_origin_utm52n"])
    bounds = bounds_for(origin)
    aoi = box(-HALF, -HALF, HALF, HALF)

    base.DATA_DIR = DATA_DIR
    base.AERIAL_ZOOM = AERIAL_ZOOM
    base.AERIAL_PATH = AERIAL_PATH
    base.AERIAL_META_PATH = AERIAL_META_PATH
    aerial = base.download_aerial(bounds, args.refresh)

    osm = load_json(OSM_RAW_PATH)
    vectors = base.process_osm(osm, origin, aoi)
    terrain = exact_terrain(base, origin)
    outer_origin = tuple(float(v) for v in v19_manifest["outer_origin_utm52n"])
    outer_offset = (outer_origin[0] - origin[0], outer_origin[1] - origin[1])
    outer_sampler = GridSampler(outer["terrain"], outer_offset)
    visual_bounds = (
        outer_sampler.min_x,
        outer_sampler.min_y,
        outer_sampler.max_x,
        outer_sampler.max_y,
    )
    visual_river = river_geometry(origin, visual_bounds)
    core_river = visual_river.intersection(aoi).buffer(0)
    plane = fit_water_plane(terrain, core_river)
    carved_terrain = carve_terrain(terrain, core_river, plane)
    field = project_field(field_config, origin)
    field_shape = Polygon(field["polygon"]).buffer(0)
    field_align = (
        float(carved_terrain["elevation_min_m"]) - float(outer["terrain"]["elevation_min_m"])
    ) * VERTICAL_EXAGGERATION + 0.18
    core_sampler = GridSampler(carved_terrain)

    def terrain_world_z(x, y):
        value = outer_sampler.z(x, y)
        if core_sampler.covers(x, y):
            value = max(value, core_sampler.z(x, y) + field_align)
        return value

    def river_surface_z(x, y):
        fitted = plane_z(plane, x, y) + field_align + 0.12
        # The 12 km regional terrain remains beneath the selective HQ tile.
        # Keep the water above both surfaces so neither terrain layer can poke
        # through and visually split the river.
        return max(fitted, outer_sampler.z(x, y) + 1.50)

    river_mesh = mesh_geometry(visual_river, river_surface_z, 6.0)
    bank_lines = [
        [[round(x, 3), round(y, 3)] for x, y in polygon.exterior.coords]
        for polygon in polygon_parts(core_river)
    ]
    vegetation = vegetation_points(core_river, field_shape, vectors["roads"], carved_terrain, field_align)

    flood_source = load_json(FLOOD_V13_PATH)
    flood_stages = []
    for item in flood_source["progression"]:
        geometry = progression_geometry(item)
        depth = float(item["visual_depth_m"])

        def flood_z(x, y, stage_depth=depth):
            smooth_level = plane_z(plane, x, y) + field_align + 0.22 + stage_depth * 0.14
            return max(smooth_level, terrain_world_z(x, y) + 0.78)

        stage_mesh = mesh_geometry(geometry, flood_z, 6.0)
        flood_stages.append({
            "step": int(item["step"]),
            "official_extent_fraction": float(item["official_extent_fraction"]),
            "visual_depth_cap_m": depth,
            "field_affected_percent": float(item["field_affected_percent"]),
            "mesh": stage_mesh,
            "hole_count": sum(len(part.interiors) for part in polygon_parts(geometry)),
        })

    old_v20 = load_json(ROOT / "data" / "processed" / "osong_flood_v20.json")
    old_z = [float(v[2]) for v in old_v20["river"]["mesh"]["vertices"]]
    new_z = [float(v[2]) for v in river_mesh["vertices"]]
    new_core_z = [
        float(v[2]) for v in river_mesh["vertices"]
        if -HALF <= float(v[0]) <= HALF and -HALF <= float(v[1]) <= HALF
    ]
    generated = datetime.now(timezone.utc).isoformat()
    context = {
        "schema_version": "1.0",
        "dataset_id": "OSONG-VISUAL-V21",
        "generated_at_utc": generated,
        "crs": "EPSG:32652",
        "origin_utm52n": list(origin),
        "georeference": {
            "bounds_wgs84": bounds,
            "bounds_local_m": [-HALF, -HALF, HALF, HALF],
            "origin_utm": list(origin),
            "origin_wgs84": list(TO_WGS.transform(*origin)),
            "crs": "EPSG:32652",
        },
        "aerial": {**aerial, "path": str(AERIAL_PATH), "attribution_path": str(ATTRIBUTION_PATH)},
        "terrain": carved_terrain,
        "field": field,
        "buildings": vectors["buildings"],
        "roads": vectors["roads"],
        "river": {
            "source": "cleaned OSM visible-water polygon reinforced by the mapped Miho River centreline",
            "source_is_surveyed_bankline": False,
            "continuous_polygon_count": len(polygon_parts(visual_river)),
            "visual_extent_policy": "full OSM visible-water main channel clipped only to the 12 km regional terrain; carve limited to 1.5 km HQ core",
            "boundary_lines": bank_lines,
            "water_plane": plane,
            "mesh": river_mesh,
            "old_v20_z_range_scene_m": [round(min(old_z), 3), round(max(old_z), 3)],
            "new_v21_z_range_scene_m": [round(min(new_core_z), 3), round(max(new_core_z), 3)],
            "full_visual_z_range_scene_m": [round(min(new_z), 3), round(max(new_z), 3)],
            "hydraulic_model": False,
        },
        "flood": {
            "source": flood_source["source"],
            "stage_count": len(flood_stages),
            "spatial_constraint": "official 100-year final extent used as the maximum visual bound",
            "hydraulic_time_series": False,
            "surface_method": "smoothed official progression footprint above terrain and the fitted river plane",
            "stages": flood_stages,
        },
        "vegetation": vegetation,
        "quality_zones": {
            "field_river_hq": {"size_m": [CORE_SIZE_M, CORE_SIZE_M], "aerial_zoom": AERIAL_ZOOM},
            "regional_background_reused": {"size_m": [12000.0, 12000.0], "source": str(OUTER_V19_PATH)},
        },
        "validation": {
            "building_count": len(vectors["buildings"]),
            "road_count": len(vectors["roads"]),
            "vegetation_instance_count": len(vegetation),
            "river_vertex_count": len(river_mesh["vertices"]),
            "river_face_count": len(river_mesh["faces"]),
            "river_hole_count": sum(len(p.interiors) for p in polygon_parts(visual_river)),
            "river_z_spread_reduction_percent": round((1 - (max(new_core_z) - min(new_core_z)) / (max(old_z) - min(old_z))) * 100, 2),
            "flood_stage_count": len(flood_stages),
            "flood_stage_hole_counts": [stage["hole_count"] for stage in flood_stages],
            "video_rendered": False,
        },
        "limitations": [
            "The z19 aerial is a 2D orthographic texture, not photogrammetric 3D geometry.",
            "The source DEM remains SRTM 30 m; the denser mesh is resampling, not new elevation measurement.",
            "The river bank is OSM-derived visible-water geometry and is not a surveyed bankline.",
            "Outside the 1.5 km carved core, the river surface is raised above the regional terrain to prevent terrain intersections.",
            "The fitted river plane and channel carve are visual corrections, not bathymetry or hydraulic simulation.",
            "The ten flood stages are a gradual visual reveal inside the official final extent, not hydraulic timestamps.",
            "Vegetation points are deterministic procedural scenery, not surveyed individual trees.",
        ],
    }
    CONTEXT_PATH.write_text(json.dumps(context, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    ATTRIBUTION_PATH.write_text(
        "\n".join([
            "Osong selective high-detail V21 attribution",
            "",
            "Aerial imagery: Esri World Imagery, z19.",
            "Road, building and visible-water geometry: OpenStreetMap contributors (ODbL).",
            "Terrain: SRTM 1 arc-second N36E127, approximately 30 m; resampled for mesh continuity.",
            "River management reference available from VWorld UJ201; not used as the visible water surface.",
        ]),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1.0",
        "dataset_id": "OSONG-VISUAL-V21-MANIFEST",
        "generated_at_utc": generated,
        "status": "prepared_without_blender_or_video",
        "source_v20_blend": str(ROOT / "blender" / "osong_flood_v20.blend"),
        "source_v20_unchanged": True,
        "selective_hq_policy": True,
        "files": [
            {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in (CONTEXT_PATH, AERIAL_PATH, AERIAL_META_PATH, ATTRIBUTION_PATH, RIVER_V15_PATH, FIELD_CONFIG_PATH)
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "status": "ok",
        "context": str(CONTEXT_PATH),
        "manifest": str(MANIFEST_PATH),
        "hq_size_m": [CORE_SIZE_M, CORE_SIZE_M],
        "aerial_zoom": AERIAL_ZOOM,
        "aerial_pixels": aerial["pixel_size"],
        "terrain_mesh": [GRID, GRID],
        "terrain_source_resolution": carved_terrain["source_resolution"],
        "buildings": len(vectors["buildings"]),
        "roads": len(vectors["roads"]),
        "vegetation_instances": len(vegetation),
        "river_vertices": len(river_mesh["vertices"]),
        "river_faces": len(river_mesh["faces"]),
        "river_holes": context["validation"]["river_hole_count"],
        "old_river_z_spread_scene_m": round(max(old_z) - min(old_z), 3),
        "new_river_z_spread_scene_m": round(max(new_core_z) - min(new_core_z), 3),
        "full_visual_river_z_spread_scene_m": round(max(new_z) - min(new_z), 3),
        "river_z_spread_reduction_percent": context["validation"]["river_z_spread_reduction_percent"],
        "channel_vertices_changed": carved_terrain["channel_carve"]["changed_vertex_count"],
        "video_rendered": False,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
