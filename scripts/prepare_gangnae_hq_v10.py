#!/usr/bin/env python3
"""Prepare georeferenced data for the Gangnae high-quality V10 Blender scene.

The script keeps all online downloads in data/gis/gangnae_hq_v10 so Blender can
rebuild the scene without another network request.  Geometry is projected to
UTM zone 52N (EPSG:32652) and stored as metre offsets from the registered field
centre.  Existing VWorld river-management geometry is used only as an official
reference boundary; visible water comes from OpenStreetMap water geometry.
"""

from __future__ import annotations

import argparse
from array import array
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request

from PIL import Image
from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.ops import unary_union


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
FIELD_PATH = ROOT / "config" / "mvp_farmland.json"
HYDRO_PATH = ROOT / "data" / "processed" / "gangnae_hydro_geometry.json"
HGT_PATH = ROOT / "data" / "terrain" / "N36E127.hgt"
DATA_DIR = ROOT / "data" / "gis" / "gangnae_hq_v10"
RAW_OSM_PATH = DATA_DIR / "osm_context_raw.json"
AERIAL_PATH = DATA_DIR / "esri_world_imagery_z18.jpg"
AERIAL_META_PATH = DATA_DIR / "esri_world_imagery_z18.json"
ATTRIBUTION_PATH = DATA_DIR / "ATTRIBUTION.txt"
CONTEXT_PATH = ROOT / "data" / "processed" / "gangnae_hq_v10_context.json"
REPORT_PATH = ROOT / "output" / "hq_v10" / "preparation_report.json"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
ESRI_TILE = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)
USER_AGENT = "GangnaeFloodDigitalTwinMVP/1.0 (academic contest prototype)"

HGT_GRID_SIZE = 3601
HGT_TILE_WEST = 127.0
HGT_TILE_SOUTH = 36.0
AOI_HALF_SIZE_M = 500.0
TERRAIN_COLUMNS = 129
TERRAIN_ROWS = 129
VERTICAL_EXAGGERATION = 1.35
AERIAL_ZOOM = 18

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)


def load_json(path: Path):
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def request_bytes(url: str, data: bytes | None = None, timeout: int = 90) -> bytes:
    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def polygon_centre(field: dict) -> tuple[float, float]:
    coordinates = field["geometry"]["coordinates"][0]
    if coordinates[0] == coordinates[-1]:
        coordinates = coordinates[:-1]
    return (
        sum(point[0] for point in coordinates) / len(coordinates),
        sum(point[1] for point in coordinates) / len(coordinates),
    )


def local_xy(lon: float, lat: float, origin_utm: tuple[float, float]) -> list[float]:
    x, y = TO_UTM.transform(lon, lat)
    return [round(x - origin_utm[0], 3), round(y - origin_utm[1], 3)]


def local_to_lonlat(
    x: float,
    y: float,
    origin_lon: float,
    origin_lat: float,
) -> tuple[float, float]:
    metres_per_degree_lat = 111_320.0
    metres_per_degree_lon = metres_per_degree_lat * math.cos(math.radians(origin_lat))
    return (
        origin_lon + x / metres_per_degree_lon,
        origin_lat + y / metres_per_degree_lat,
    )


def derive_aoi(field_centre: tuple[float, float]) -> dict:
    lon, lat = field_centre
    origin_x, origin_y = TO_UTM.transform(lon, lat)
    inverse = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)
    west, south = inverse.transform(origin_x - AOI_HALF_SIZE_M, origin_y - AOI_HALF_SIZE_M)
    east, north = inverse.transform(origin_x + AOI_HALF_SIZE_M, origin_y + AOI_HALF_SIZE_M)
    return {
        "bounds_wgs84": [west, south, east, north],
        "bounds_local_m": [-AOI_HALF_SIZE_M, -AOI_HALF_SIZE_M, AOI_HALF_SIZE_M, AOI_HALF_SIZE_M],
        "origin_wgs84": [lon, lat],
        "origin_utm": [origin_x, origin_y],
        "crs": "EPSG:32652",
    }


def tile_float(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    scale = 2**zoom
    x = (lon + 180.0) / 360.0 * scale
    latitude = math.radians(max(-85.05112878, min(85.05112878, lat)))
    y = (1.0 - math.asinh(math.tan(latitude)) / math.pi) / 2.0 * scale
    return x, y


def download_aerial(bounds: list[float], refresh: bool) -> dict:
    if AERIAL_PATH.is_file() and AERIAL_META_PATH.is_file() and not refresh:
        return load_json(AERIAL_META_PATH)

    west, south, east, north = bounds
    x_west, y_north = tile_float(west, north, AERIAL_ZOOM)
    x_east, y_south = tile_float(east, south, AERIAL_ZOOM)
    min_x, max_x = math.floor(x_west), math.floor(x_east)
    min_y, max_y = math.floor(y_north), math.floor(y_south)
    width_tiles = max_x - min_x + 1
    height_tiles = max_y - min_y + 1
    mosaic = Image.new("RGB", (width_tiles * 256, height_tiles * 256))
    downloaded = []

    for tile_y in range(min_y, max_y + 1):
        for tile_x in range(min_x, max_x + 1):
            url = ESRI_TILE.format(z=AERIAL_ZOOM, x=tile_x, y=tile_y)
            payload = request_bytes(url, timeout=45)
            tile_path = DATA_DIR / "tiles" / f"{AERIAL_ZOOM}_{tile_x}_{tile_y}.jpg"
            tile_path.parent.mkdir(parents=True, exist_ok=True)
            tile_path.write_bytes(payload)
            with Image.open(tile_path) as tile:
                mosaic.paste(
                    tile.convert("RGB"),
                    ((tile_x - min_x) * 256, (tile_y - min_y) * 256),
                )
            downloaded.append([tile_x, tile_y])

    left = round((x_west - min_x) * 256)
    right = round((x_east - min_x) * 256)
    top = round((y_north - min_y) * 256)
    bottom = round((y_south - min_y) * 256)
    cropped = mosaic.crop((left, top, right, bottom))
    cropped.save(AERIAL_PATH, quality=94, optimize=True)

    metadata = {
        "provider": "Esri World Imagery",
        "service": "ArcGIS World_Imagery MapServer",
        "source_url_template": ESRI_TILE,
        "zoom": AERIAL_ZOOM,
        "bounds_wgs84": bounds,
        "pixel_size": list(cropped.size),
        "tile_range": [min_x, min_y, max_x, max_y],
        "tile_count": len(downloaded),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "MVP digital-twin terrain texture",
    }
    AERIAL_META_PATH.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metadata


def overpass_query(bounds: list[float]) -> str:
    west, south, east, north = bounds
    bbox = f"{south:.8f},{west:.8f},{north:.8f},{east:.8f}"
    return f"""[out:json][timeout:90];
(
  way[\"building\"]({bbox});
  way[\"highway\"]({bbox});
  way[\"waterway\"]({bbox});
  way[\"natural\"=\"water\"]({bbox});
  way[\"water\"]({bbox});
);
out tags geom;"""


def download_osm(bounds: list[float], refresh: bool) -> dict:
    if RAW_OSM_PATH.is_file() and not refresh:
        return load_json(RAW_OSM_PATH)
    encoded = urllib.parse.urlencode({"data": overpass_query(bounds)}).encode("utf-8")
    payload = request_bytes(OVERPASS_URL, data=encoded, timeout=120)
    RAW_OSM_PATH.write_bytes(payload)
    return json.loads(payload)


def parse_number(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", "."))
    return float(match.group()) if match else None


def building_height(tags: dict) -> float:
    height = parse_number(tags.get("height"))
    if height and 2.0 <= height <= 120.0:
        return height
    levels = parse_number(tags.get("building:levels"))
    if levels and 1 <= levels <= 30:
        return max(3.2, levels * 3.2)
    kind = tags.get("building", "yes")
    if kind in {"industrial", "warehouse", "hangar", "greenhouse"}:
        return 5.5
    if kind in {"apartments", "commercial", "office"}:
        return 12.0
    return 7.2


def road_width(tags: dict) -> float:
    explicit = parse_number(tags.get("width"))
    if explicit and 1.0 <= explicit <= 40.0:
        return explicit
    return {
        "motorway": 14.0,
        "trunk": 12.0,
        "primary": 10.0,
        "secondary": 8.0,
        "tertiary": 7.0,
        "residential": 5.5,
        "unclassified": 5.0,
        "service": 3.6,
        "track": 3.0,
        "construction": 4.0,
        "pedestrian": 2.5,
        "footway": 1.4,
        "path": 1.2,
        "steps": 1.4,
    }.get(tags.get("highway"), 3.0)


def waterway_width(tags: dict) -> float:
    explicit = parse_number(tags.get("width"))
    if explicit and 1.0 <= explicit <= 200.0:
        return explicit
    return {
        "river": 48.0,
        "stream": 8.0,
        "canal": 7.0,
        "ditch": 2.0,
        "drain": 2.0,
    }.get(tags.get("waterway"), 5.0)


def process_osm(osm: dict, origin_utm: tuple[float, float], aoi_shape: Polygon) -> dict:
    buildings = []
    roads = []
    water_polygons = []
    waterways = []
    seen = set()

    for element in osm.get("elements", []):
        if element.get("type") != "way" or element.get("id") in seen:
            continue
        geometry = element.get("geometry") or []
        if len(geometry) < 2:
            continue
        seen.add(element.get("id"))
        tags = element.get("tags") or {}
        coords = [local_xy(item["lon"], item["lat"], origin_utm) for item in geometry]
        is_closed = len(coords) >= 4 and coords[0] == coords[-1]

        if "building" in tags and is_closed:
            shape = Polygon(coords)
            if shape.is_valid and shape.area >= 8 and shape.intersects(aoi_shape):
                clipped = shape.intersection(aoi_shape)
                parts = [clipped] if isinstance(clipped, Polygon) else list(getattr(clipped, "geoms", []))
                for part in parts:
                    if isinstance(part, Polygon) and part.area >= 8:
                        buildings.append({
                            "osm_id": element["id"],
                            "kind": tags.get("building", "yes"),
                            "height_m": round(building_height(tags), 2),
                            "levels": tags.get("building:levels"),
                            "name": tags.get("name"),
                            "polygon": [[round(x, 3), round(y, 3)] for x, y in list(part.exterior.coords)[:-1]],
                        })

        if "highway" in tags:
            shape = LineString(coords)
            clipped = shape.intersection(aoi_shape)
            parts = [clipped] if isinstance(clipped, LineString) else list(getattr(clipped, "geoms", []))
            for part in parts:
                if isinstance(part, LineString) and part.length >= 2:
                    roads.append({
                        "osm_id": element["id"],
                        "highway": tags.get("highway"),
                        "name": tags.get("name"),
                        "bridge": tags.get("bridge") not in (None, "no"),
                        "width_m": road_width(tags),
                        "path": [[round(x, 3), round(y, 3)] for x, y in part.coords],
                    })

        is_water_polygon = is_closed and (
            tags.get("natural") == "water"
            or "water" in tags
            or tags.get("waterway") == "riverbank"
        )
        if is_water_polygon:
            shape = Polygon(coords)
            if shape.is_valid and shape.intersects(aoi_shape):
                clipped = shape.intersection(aoi_shape)
                parts = [clipped] if isinstance(clipped, Polygon) else list(getattr(clipped, "geoms", []))
                for part in parts:
                    if isinstance(part, Polygon) and part.area >= 10:
                        water_polygons.append({
                            "osm_id": element["id"],
                            "name": tags.get("name"),
                            "water": tags.get("water") or tags.get("waterway") or tags.get("natural"),
                            "polygon": [[round(x, 3), round(y, 3)] for x, y in list(part.exterior.coords)[:-1]],
                        })
        elif "waterway" in tags:
            shape = LineString(coords)
            clipped = shape.intersection(aoi_shape)
            parts = [clipped] if isinstance(clipped, LineString) else list(getattr(clipped, "geoms", []))
            for part in parts:
                if isinstance(part, LineString) and part.length >= 2:
                    waterways.append({
                        "osm_id": element["id"],
                        "name": tags.get("name"),
                        "waterway": tags.get("waterway"),
                        "width_m": waterway_width(tags),
                        "path": [[round(x, 3), round(y, 3)] for x, y in part.coords],
                    })

    return {
        "buildings": buildings,
        "roads": roads,
        "water_polygons": water_polygons,
        "waterways": waterways,
    }


def official_reference(
    hydro: dict,
    origin_utm: tuple[float, float],
    aoi_shape: Polygon,
) -> list[dict]:
    old_lon, old_lat = hydro["origin_wgs84"]
    references = []
    for zone in hydro.get("official_zones", []):
        polygons = []
        for polygon in zone.get("polygons", []):
            lonlat = [local_to_lonlat(x, y, old_lon, old_lat) for x, y in polygon["exterior"]]
            projected = [local_xy(lon, lat, origin_utm) for lon, lat in lonlat]
            shape = Polygon(projected)
            if not shape.is_valid:
                shape = shape.buffer(0)
            clipped = shape.intersection(aoi_shape)
            parts = [clipped] if isinstance(clipped, Polygon) else list(getattr(clipped, "geoms", []))
            for part in parts:
                if isinstance(part, Polygon) and part.area >= 10:
                    polygons.append({
                        "exterior": [[round(x, 3), round(y, 3)] for x, y in list(part.exterior.coords)[:-1]]
                    })
        if polygons:
            references.append({
                "id": zone["id"],
                "name": zone["name"],
                "source_layer": zone["source_layer"],
                "classification": zone["classification"],
                "polygons": polygons,
            })
    return references


def read_hgt() -> array:
    expected = HGT_GRID_SIZE * HGT_GRID_SIZE * 2
    if HGT_PATH.stat().st_size != expected:
        raise ValueError(f"Unexpected HGT size: {HGT_PATH.stat().st_size} != {expected}")
    values = array("h")
    with HGT_PATH.open("rb") as source:
        values.fromfile(source, HGT_GRID_SIZE * HGT_GRID_SIZE)
    if sys.byteorder == "little":
        values.byteswap()
    return values


def sample_hgt(values: array, lon: float, lat: float) -> int:
    column = round((lon - HGT_TILE_WEST) * (HGT_GRID_SIZE - 1))
    row = round(((HGT_TILE_SOUTH + 1.0) - lat) * (HGT_GRID_SIZE - 1))
    column = max(0, min(HGT_GRID_SIZE - 1, column))
    row = max(0, min(HGT_GRID_SIZE - 1, row))
    result = int(values[row * HGT_GRID_SIZE + column])
    if result == -32768:
        raise ValueError(f"SRTM void at {lon}, {lat}")
    return result


def terrain_grid(aoi: dict) -> dict:
    west, south, east, north = aoi["bounds_wgs84"]
    origin_utm = tuple(aoi["origin_utm"])
    values = read_hgt()
    raw = []
    elevations = []
    for row in range(TERRAIN_ROWS):
        lat = north - (north - south) * row / (TERRAIN_ROWS - 1)
        for column in range(TERRAIN_COLUMNS):
            lon = west + (east - west) * column / (TERRAIN_COLUMNS - 1)
            x, y = local_xy(lon, lat, origin_utm)
            elevation = sample_hgt(values, lon, lat)
            raw.append([x, y, elevation])
            elevations.append(elevation)
    minimum = min(elevations)
    vertices = [
        [x, y, round((z - minimum) * VERTICAL_EXAGGERATION, 3)]
        for x, y, z in raw
    ]
    return {
        "rows": TERRAIN_ROWS,
        "columns": TERRAIN_COLUMNS,
        "source": str(HGT_PATH),
        "source_resolution": "SRTM 1 arc-second, approximately 30 m",
        "elevation_min_m": minimum,
        "elevation_max_m": max(elevations),
        "vertical_exaggeration": VERTICAL_EXAGGERATION,
        "vertices": vertices,
    }


def project_field(field: dict, origin_utm: tuple[float, float]) -> dict:
    points = field["geometry"]["coordinates"][0]
    if points[0] == points[-1]:
        points = points[:-1]
    return {
        "field_id": field["field_id"],
        "display_name": field["display_name"],
        "geometry_accuracy": field["geometry_accuracy"],
        "area_m2": field["derived_metrics"]["area_m2"],
        "polygon": [local_xy(lon, lat, origin_utm) for lon, lat in points],
    }


def write_attribution():
    ATTRIBUTION_PATH.write_text(
        "\n".join(
            [
                "Gangnae HQ V10 data attribution",
                "",
                "Aerial imagery: Esri World Imagery (retrieved through ArcGIS World_Imagery MapServer).",
                "Vector context: OpenStreetMap contributors, data available under ODbL.",
                "Official river-management zones: VWorld UJ201/UJ301 source data supplied by the project.",
                "Terrain: SRTM 1 arc-second N36E127 HGT, approximately 30 m resolution.",
                "",
                "The official river-management polygons are reference zones, not the current wetted river surface.",
            ]
        ),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="redownload imagery and OSM")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    field = load_json(FIELD_PATH)
    hydro = load_json(HYDRO_PATH)
    centre = polygon_centre(field)
    aoi = derive_aoi(centre)
    origin_utm = tuple(aoi["origin_utm"])
    aoi_shape = box(*aoi["bounds_local_m"])

    aerial = download_aerial(aoi["bounds_wgs84"], args.refresh)
    osm = download_osm(aoi["bounds_wgs84"], args.refresh)
    context = process_osm(osm, origin_utm, aoi_shape)
    official = official_reference(hydro, origin_utm, aoi_shape)
    terrain = terrain_grid(aoi)
    field_local = project_field(field, origin_utm)

    water_shapes = []
    for item in context["water_polygons"]:
        try:
            shape = Polygon(item["polygon"])
            if shape.is_valid:
                water_shapes.append(shape)
        except ValueError:
            continue
    official_shapes = []
    for zone in official:
        for item in zone["polygons"]:
            shape = Polygon(item["exterior"])
            if shape.is_valid:
                official_shapes.append(shape)
    overlap_area = 0.0
    if water_shapes and official_shapes:
        overlap_area = unary_union(water_shapes).intersection(unary_union(official_shapes)).area

    result = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scene": "Gangnae_HQ_V10",
        "georeference": aoi,
        "aerial": {
            **aerial,
            "path": str(AERIAL_PATH),
            "attribution_path": str(ATTRIBUTION_PATH),
        },
        "terrain": terrain,
        "field": field_local,
        "buildings": context["buildings"],
        "roads": context["roads"],
        "water_polygons": context["water_polygons"],
        "waterways": context["waterways"],
        "official_river_reference": official,
        "validation": {
            "aoi_size_m": [1000.0, 1000.0],
            "building_count": len(context["buildings"]),
            "road_count": len(context["roads"]),
            "bridge_count": sum(1 for road in context["roads"] if road["bridge"]),
            "water_polygon_count": len(context["water_polygons"]),
            "waterway_count": len(context["waterways"]),
            "official_zone_count": len(official),
            "visible_water_official_overlap_m2": round(overlap_area, 2),
            "field_inside_aoi": Polygon(field_local["polygon"]).within(aoi_shape),
        },
    }
    CONTEXT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_attribution()

    validation = result["validation"]
    if not validation["field_inside_aoi"]:
        raise RuntimeError("Registered field is outside the V10 AOI")
    if validation["road_count"] == 0:
        raise RuntimeError("No roads were prepared")
    if validation["water_polygon_count"] + validation["waterway_count"] == 0:
        raise RuntimeError("No visible water geometry was prepared")

    report = {
        "status": "ok",
        "context_path": str(CONTEXT_PATH),
        "aerial_path": str(AERIAL_PATH),
        "aerial_pixel_size": aerial["pixel_size"],
        **validation,
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
