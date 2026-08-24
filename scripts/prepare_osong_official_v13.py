#!/usr/bin/env python3
"""Prepare an official-map-constrained Osong V13 flood scenario and safe route.

The final flood extent/depth class comes from the Ministry of Environment
national-river 100-year flood-map tiles. Intermediate frames only reveal that
official final extent gradually; they are not a hydraulic time-series model.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess

import cv2
import networkx as nx
import numpy as np
from PIL import Image
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon, box, mapping, shape
from shapely.ops import unary_union
from shapely.prepared import prep


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
CONTEXT_PATH = ROOT / "data/processed/osong_hq_v11_context.json"
FIELD_PATH = ROOT / "config/osong_farmland_v11.json"
RAW_DIR = ROOT / "data/gis/osong_v13"
TILE_DIR = RAW_DIR / "floodmap_kum_100yr_202601_z17"
SHELTER_RAW_PATH = RAW_DIR / "temporary_disaster_shelters.json"
ROADS_RAW_PATH = RAW_DIR / "osm_roads.json"
OUTPUT_PATH = ROOT / "data/processed/osong_official_inundation_v13.json"
ROUTE_PATH = ROOT / "data/processed/osong_shelter_route_v13.geojson"

ZOOM = 17
ROUTE_BOUNDS = (127.295, 36.575, 127.330, 36.615)
TILE_URL = (
    "https://www.floodmap.go.kr/floodmap_tiles_repo2/nation/kum/"
    "nation_kum_100yr/202601/{z}/{x}/{y}.png"
)
DEPTH_CLASSES = {
    1: {"rgb": (253, 251, 199), "label": "0.5m 이하", "lower_m": 0.0, "upper_m": 0.5},
    2: {"rgb": (230, 255, 153), "label": "0.5~1.0m", "lower_m": 0.5, "upper_m": 1.0},
    3: {"rgb": (56, 254, 253), "label": "1.0~2.0m", "lower_m": 1.0, "upper_m": 2.0},
    4: {"rgb": (206, 154, 254), "label": "2.0~5.0m", "lower_m": 2.0, "upper_m": 5.0},
    5: {"rgb": (206, 63, 135), "label": "5.0m 이상", "lower_m": 5.0, "upper_m": None},
}
SELECTED_SHELTER_NAME = "오송읍복지회관"
VISUAL_DEPTH_CAP_M = 2.0
PROGRESSION_STEPS = 10


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def lonlat_to_tile_pixel(lon: float, lat: float, zoom: int):
    scale = 2**zoom
    x = (lon + 180.0) / 360.0 * scale
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * scale
    return x, y


def global_pixel_to_lonlat(px: float, py: float, zoom: int):
    size = 256.0 * 2**zoom
    lon = px / size * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * py / size))))
    return lon, lat


def tile_range(bounds):
    left, bottom, right, top = bounds
    x0, y0 = lonlat_to_tile_pixel(left, top, ZOOM)
    x1, y1 = lonlat_to_tile_pixel(right, bottom, ZOOM)
    return int(x0), int(y0), int(x1), int(y1)


def download_tile(item):
    x, y = item
    path = TILE_DIR / f"{x}_{y}.png"
    if path.is_file():
        return path
    url = TILE_URL.format(z=ZOOM, x=x, y=y)
    completed = subprocess.run(
        ["/usr/bin/curl", "-L", "--fail", "--silent", "--show-error", url],
        check=True,
        capture_output=True,
    )
    body = completed.stdout
    if not body.startswith(b"\x89PNG"):
        raise RuntimeError(f"Official flood-map tile is not PNG: {url}")
    path.write_bytes(body)
    return path


def build_mosaic(bounds):
    x0, y0, x1, y1 = tile_range(bounds)
    TILE_DIR.mkdir(parents=True, exist_ok=True)
    items = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    with ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(download_tile, items))
    mosaic = Image.new("RGBA", ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256))
    for x, y in items:
        tile = Image.open(TILE_DIR / f"{x}_{y}.png").convert("RGBA")
        mosaic.paste(tile, ((x - x0) * 256, (y - y0) * 256))
    return mosaic, (x0, y0, x1, y1)


def classify_mosaic(mosaic: Image.Image):
    rgba = np.asarray(mosaic, dtype=np.int16)
    rgb = rgba[:, :, :3]
    alpha = rgba[:, :, 3]
    result = np.zeros(alpha.shape, dtype=np.uint8)
    best = np.full(alpha.shape, 10_000, dtype=np.int32)
    for code, meta in DEPTH_CLASSES.items():
        colour = np.array(meta["rgb"], dtype=np.int16)
        distance = np.sum((rgb - colour) ** 2, axis=2)
        choose = (alpha >= 128) & (distance < best) & (distance <= 55**2)
        result[choose] = code
        best[choose] = distance[choose]
    return result


def pixel_to_utm(px, py, tile_bounds, transformer):
    x0, y0, _x1, _y1 = tile_bounds
    lon, lat = global_pixel_to_lonlat(x0 * 256 + px, y0 * 256 + py, ZOOM)
    return transformer.transform(lon, lat)


def mask_to_geometry(mask, tile_bounds, transformer, min_area=4.0):
    contours, _hierarchy = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    polygons = []
    for contour in contours:
        if len(contour) < 3:
            continue
        points = [pixel_to_utm(float(p[0][0]), float(p[0][1]), tile_bounds, transformer) for p in contour]
        polygon = Polygon(points).buffer(0)
        if not polygon.is_empty and polygon.area >= min_area:
            polygons.append(polygon)
    return unary_union(polygons).buffer(0) if polygons else Polygon()


def sample_field_classes(classified, tile_bounds, field_wgs84, transformer):
    field_utm = shape(field_wgs84)
    field_utm = Polygon([transformer.transform(x, y) for x, y in field_utm.exterior.coords])
    minx, miny, maxx, maxy = field_utm.bounds
    inverse = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)
    left, bottom = inverse.transform(minx, miny)
    right, top = inverse.transform(maxx, maxy)
    fx0, fy0 = lonlat_to_tile_pixel(left, top, ZOOM)
    fx1, fy1 = lonlat_to_tile_pixel(right, bottom, ZOOM)
    x0, y0, _x1, _y1 = tile_bounds
    col0 = max(0, int((fx0 - x0) * 256) - 2)
    col1 = min(classified.shape[1] - 1, int((fx1 - x0) * 256) + 2)
    row0 = max(0, int((fy0 - y0) * 256) - 2)
    row1 = min(classified.shape[0] - 1, int((fy1 - y0) * 256) + 2)
    counts = {code: 0 for code in DEPTH_CLASSES}
    dry = 0
    for row in range(row0, row1 + 1):
        for col in range(col0, col1 + 1):
            utm = pixel_to_utm(col + 0.5, row + 0.5, tile_bounds, transformer)
            if not field_utm.contains(Point(utm)):
                continue
            code = int(classified[row, col])
            if code:
                counts[code] += 1
            else:
                dry += 1
    total = dry + sum(counts.values())
    if total == 0:
        raise RuntimeError("No flood-map pixels sampled inside the registered field")
    return field_utm, counts, dry, total


def local_polygons(geometry, origin_utm):
    polygons = []
    parts = [geometry] if isinstance(geometry, Polygon) else list(getattr(geometry, "geoms", []))
    for part in parts:
        if not isinstance(part, Polygon) or part.area < 8:
            continue
        simplified = part.simplify(1.5, preserve_topology=True)
        polygons.append({
            "exterior": [[round(x - origin_utm[0], 3), round(y - origin_utm[1], 3)] for x, y in list(simplified.exterior.coords)[:-1]],
            "area_m2": round(part.area, 1),
        })
    return polygons


def build_progression(final_flood, river_local, field_utm, origin_utm):
    river_utm = Polygon()
    river_parts = []
    for item in river_local:
        river_parts.append(Polygon([(x + origin_utm[0], y + origin_utm[1]) for x, y in item["polygon"]]))
    if river_parts:
        river_utm = unary_union(river_parts).buffer(0)
    max_distance = max(
        final_flood.boundary.distance(river_utm),
        max((Point(x, y).distance(river_utm) for x, y in final_flood.envelope.exterior.coords), default=0),
    )
    # Ensure the last frame exactly reaches the official extent.
    progression = []
    previous = river_utm.intersection(final_flood)
    for step in range(1, PROGRESSION_STEPS + 1):
        progress = step / PROGRESSION_STEPS
        if step == PROGRESSION_STEPS:
            geometry = final_flood
        else:
            geometry = final_flood.intersection(river_utm.buffer(max_distance * progress))
            geometry = unary_union([previous, geometry]).buffer(0)
        previous = geometry
        affected = geometry.intersection(field_utm).area
        progression.append({
            "step": step,
            "progress": round(progress, 2),
            "visual_depth_m": round(VISUAL_DEPTH_CAP_M * progress, 2),
            "official_extent_fraction": round(geometry.area / final_flood.area, 4),
            "total_area_m2": round(geometry.area, 1),
            "field_affected_area_m2": round(affected, 1),
            "field_affected_percent": round(affected / field_utm.area * 100.0, 1),
            "polygons": local_polygons(geometry, origin_utm),
        })
    return progression


def haversine_m(a, b):
    lon1, lat1 = a
    lon2, lat2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(h))


def select_shelter():
    shelters = read_json(SHELTER_RAW_PATH)["resultList"]
    matches = [item for item in shelters if item.get("fclty_nm") == SELECTED_SHELTER_NAME]
    if not matches:
        raise RuntimeError(f"Shelter not found: {SELECTED_SHELTER_NAME}")
    item = matches[0]
    return {
        "name": item["fclty_nm"],
        "facility_type": item["fclty_se"],
        "capacity": item["reside_ablty"],
        "address": item["detail_adres"],
        "lon": float(item["lo"]),
        "lat": float(item["la"]),
        "source": "생활안전지도 재해구호시설 API",
    }


def build_safe_route(osm, final_flood, field_utm, shelter, transformer):
    nodes = {int(e["id"]): (float(e["lon"]), float(e["lat"])) for e in osm["elements"] if e["type"] == "node"}
    graph = nx.Graph()
    flood_buffer = final_flood.simplify(2.0, preserve_topology=True).buffer(10.0)
    prepared_flood = prep(flood_buffer)
    exposed_edge_count = 0
    allowed_highways = {
        "primary", "secondary", "tertiary", "unclassified", "residential", "service",
        "living_street", "track", "path", "footway", "pedestrian", "steps",
        "primary_link", "secondary_link", "tertiary_link",
    }
    for way in (e for e in osm["elements"] if e["type"] == "way"):
        tags = way.get("tags", {})
        if tags.get("highway") not in allowed_highways or tags.get("access") in {"no", "private"}:
            continue
        way_nodes = [int(n) for n in way.get("nodes", []) if int(n) in nodes]
        for a, b in zip(way_nodes, way_nodes[1:]):
            a_ll, b_ll = nodes[a], nodes[b]
            a_xy, b_xy = transformer.transform(*a_ll), transformer.transform(*b_ll)
            edge = LineString([a_xy, b_xy])
            exposed = prepared_flood.intersects(edge)
            if exposed:
                exposed_edge_count += 1
            # Prefer dry roads strongly, but retain a route out of the field because
            # the registered field itself lies inside the mapped flood extent.
            graph.add_edge(
                a, b,
                weight=edge.length * (25.0 if exposed else 1.0),
                distance=edge.length,
                flood_exposed=exposed,
                highway=tags.get("highway"),
                name=tags.get("name", ""),
            )
    if graph.number_of_edges() == 0:
        raise RuntimeError("No road graph was created")

    field_centre = field_utm.centroid
    shelter_xy = Point(transformer.transform(shelter["lon"], shelter["lat"]))
    safe_nodes = list(graph.nodes)
    end = min(safe_nodes, key=lambda n: Point(transformer.transform(*nodes[n])).distance(shelter_xy))
    shelter_component = nx.node_connected_component(graph, end)
    start = min(shelter_component, key=lambda n: Point(transformer.transform(*nodes[n])).distance(field_centre))
    path = nx.shortest_path(graph, start, end, weight="weight")
    route_ll = [nodes[n] for n in path]
    flooded_length = 0.0
    last_exposed_index = -1
    for index, (a, b) in enumerate(zip(path, path[1:])):
        edge_data = graph.get_edge_data(a, b)
        if edge_data.get("flood_exposed"):
            flooded_length += float(edge_data["distance"])
            last_exposed_index = index
    safe_start_index = min(len(path) - 1, last_exposed_index + 1)
    safe_route_ll = route_ll[safe_start_index:]
    start_ll = nodes[start]
    field_ll = (127.30407966188604, 36.585605060076986)
    route_length = sum(haversine_m(a, b) for a, b in zip(route_ll, route_ll[1:]))
    return {
        "route": route_ll,
        "safe_route_after_last_flood_crossing": safe_route_ll,
        "route_length_m": round(route_length, 1),
        "flood_exposed_length_m": round(flooded_length, 1),
        "field_to_route_start_m": round(haversine_m(field_ll, start_ll), 1),
        "safe_start": route_ll[safe_start_index],
        "safe_tail_length_m": round(sum(haversine_m(a, b) for a, b in zip(safe_route_ll, safe_route_ll[1:])), 1),
        "shelter_snap_distance_m": round(Point(transformer.transform(*nodes[end])).distance(shelter_xy), 1),
        "flood_exposed_road_edges": exposed_edge_count,
        "fully_flood_free_route_available": flooded_length < 1.0,
        "route_selection": "minimum-cost route with 25x penalty on official flood-map intersections",
        "usage_condition": "대상 필지가 침수예상구역 안에 있으므로 반드시 비가 시작되기 전에 이용; 침수 후 안전경로로 사용 금지",
    }

def write_route_geojson(route, shelter, final_flood, inverse):
    safe_tail_points = route["safe_route_after_last_flood_crossing"]
    safe_tail_geometry = LineString(safe_tail_points) if len(safe_tail_points) >= 2 else Point(safe_tail_points[0])
    flood_wgs84 = []
    parts = [final_flood] if isinstance(final_flood, Polygon) else list(getattr(final_flood, "geoms", []))
    for part in parts:
        flood_wgs84.append(Polygon([inverse.transform(x, y) for x, y in part.exterior.coords]).buffer(0))
    features = [
        {"type": "Feature", "properties": {"kind": "pre_rain_route", "length_m": route["route_length_m"], "flood_exposed_length_m": route["flood_exposed_length_m"]}, "geometry": mapping(LineString(route["route"]))},
        {"type": "Feature", "properties": {"kind": "flood_free_tail", "length_m": route["safe_tail_length_m"]}, "geometry": mapping(safe_tail_geometry)},
        {"type": "Feature", "properties": {"kind": "safe_start"}, "geometry": mapping(Point(route["safe_start"]))},
        {"type": "Feature", "properties": {"kind": "shelter", **shelter}, "geometry": mapping(Point(shelter["lon"], shelter["lat"]))},
        {"type": "Feature", "properties": {"kind": "official_flood_extent", "scenario": "국가하천 100년 빈도"}, "geometry": mapping(unary_union(flood_wgs84))},
    ]
    ROUTE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROUTE_PATH.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    for path in (CONTEXT_PATH, FIELD_PATH, SHELTER_RAW_PATH, ROADS_RAW_PATH):
        if not path.is_file():
            raise FileNotFoundError(path)
    context = read_json(CONTEXT_PATH)
    field = read_json(FIELD_PATH)
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
    inverse = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)
    mosaic, tiles = build_mosaic(ROUTE_BOUNDS)
    classified = classify_mosaic(mosaic)
    final_flood = mask_to_geometry(classified > 0, tiles, transformer)
    if final_flood.is_empty:
        raise RuntimeError("Official flood-map extent is empty")
    field_utm, counts, dry, total = sample_field_classes(classified, tiles, field["geometry"], transformer)
    max_code = max((code for code, count in counts.items() if count), default=0)
    affected_percent = round((total - dry) / total * 100.0, 1)
    origin_utm = context["georeference"]["origin_utm"]
    scene_bounds = box(
        origin_utm[0] - 500.0, origin_utm[1] - 500.0,
        origin_utm[0] + 500.0, origin_utm[1] + 500.0,
    )
    scene_flood = final_flood.intersection(scene_bounds).buffer(0)
    progression = build_progression(scene_flood, context["water_polygons"], field_utm, origin_utm)
    shelter = select_shelter()
    shelter_class = 0
    sx, sy = lonlat_to_tile_pixel(shelter["lon"], shelter["lat"], ZOOM)
    col = int((sx - tiles[0]) * 256)
    row = int((sy - tiles[1]) * 256)
    if 0 <= row < classified.shape[0] and 0 <= col < classified.shape[1]:
        shelter_class = int(classified[row, col])
    if shelter_class:
        raise RuntimeError(f"Selected shelter lies in official flood class {shelter_class}")
    route = build_safe_route(read_json(ROADS_RAW_PATH), final_flood, field_utm, shelter, transformer)
    write_route_geojson(route, shelter, final_flood, inverse)

    result = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scene": "Osong_Official_Story_V13",
        "crs": "EPSG:32652",
        "origin_wgs84": context["georeference"]["origin_wgs84"],
        "source": {
            "provider": "환경부 홍수위험지도 정보시스템",
            "dataset": "국가하천 홍수위험지도 금강권역 100년 빈도",
            "tile_url_template": TILE_URL,
            "publication": "202601",
            "zoom": ZOOM,
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "official_depth_legend": {str(k): v for k, v in DEPTH_CLASSES.items()},
        },
        "method": {
            "name": "official_floodmap_extent_with_gradual_visual_reveal",
            "final_extent": "official 100-year national-river flood-map pixels",
            "intermediate_frames": "distance-based reveal constrained inside the official final extent",
            "hydraulic_time_series": False,
            "visual_depth_cap_m": VISUAL_DEPTH_CAP_M,
            "cap_reason": "Conservative lower-bound display for the field's official 2.0~5.0m class; avoids claiming an unavailable exact depth.",
        },
        "field": {
            "field_id": field["field_id"],
            "geometry_role": field["geometry_accuracy"],
            "area_m2": round(field_utm.area, 1),
            "official_flood_affected_percent": affected_percent,
            "pixel_samples": total,
            "dry_samples": dry,
            "depth_class_counts": counts,
            "maximum_official_class_code": max_code,
            "maximum_official_class_label": DEPTH_CLASSES[max_code]["label"] if max_code else "침수 색상 없음",
        },
        "progression": progression,
        "shelter": {**shelter, "official_flood_class_code": shelter_class, "outside_official_flood_extent": shelter_class == 0},
        "route": route,
        "validation": {
            "progression_steps": len(progression),
            "monotonic_area": all(a["total_area_m2"] <= b["total_area_m2"] for a, b in zip(progression, progression[1:])),
            "final_extent_matches_official": True,
            "shelter_outside_official_flood_extent": shelter_class == 0,
            "fully_flood_free_route_available": route["fully_flood_free_route_available"],
            "field_is_cadastral": False,
        },
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "field_affected_percent": affected_percent,
        "field_depth_class": result["field"]["maximum_official_class_label"],
        "visual_depth_cap_m": VISUAL_DEPTH_CAP_M,
        "shelter": shelter["name"],
        "route_length_m": route["route_length_m"],
        "flood_exposed_length_m": route["flood_exposed_length_m"],
        "output": str(OUTPUT_PATH),
        "route_geojson": str(ROUTE_PATH),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
