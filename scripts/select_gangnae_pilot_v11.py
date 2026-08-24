#!/usr/bin/env python3
"""Select a defensible 1 km Miho River agricultural pilot AOI.

The script downloads one expanded OpenStreetMap snapshot, samples candidate
centres along the actual Miho River centreline, scores them, downloads aerial
images for the five strongest candidates, and writes a selected V11 pilot
configuration without changing the current V9/V10 field configuration.
"""

from __future__ import annotations

from array import array
from datetime import datetime, timezone
import io
import json
import math
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw, ImageFont
from pyproj import Transformer
import shapefile
from shapely.geometry import LineString, MultiLineString, Polygon, box, shape
from shapely.ops import linemerge, polygonize, transform, unary_union


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
WORK_DIR = ROOT / "data" / "gis" / "pilot_selection_v11"
RAW_OSM_PATH = WORK_DIR / "expanded_osm_raw.json"
REPORT_DIR = ROOT / "output" / "pilot_selection_v11"
RESULT_JSON = REPORT_DIR / "pilot_candidates.json"
CONTACT_SHEET = REPORT_DIR / "pilot_candidates_contact_sheet.jpg"
REPORT_MD = REPORT_DIR / "pilot_selection_report.md"
SELECTED_CONFIG = ROOT / "config" / "pilot_area_v11.json"

UJ201_DIR = ROOT / "data" / "source" / "hydro" / "UJ201"
HGT_PATH = ROOT / "data" / "terrain" / "N36E127.hgt"
HYDRO_SNAPSHOT_PATH = ROOT / "data" / "runtime" / "hydro_snapshot.json"
FLOODMAP_META_PATH = (
    ROOT / "archive" / "source_data_20260822" / "pilot_gangnae" /
    "floodmap_50yr_z16_mosaic.json"
)

SEARCH_BOUNDS = [127.305, 36.575, 127.365, 36.632]
AOI_HALF_M = 500.0
MIN_CANDIDATE_SPACING_M = 700.0
TOP_COUNT = 5
AERIAL_ZOOM = 17
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
ESRI_TILE = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)
USER_AGENT = "GangnaeFloodDigitalTwinMVP/1.0 (academic contest prototype)"

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
TO_WGS = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)
NATIVE_TO_UTM = Transformer.from_crs("EPSG:5174", "EPSG:32652", always_xy=True)

HGT_GRID_SIZE = 3601
HGT_TILE_WEST = 127.0
HGT_TILE_SOUTH = 36.0


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def request_bytes(url, data=None, timeout=120):
    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def overpass_query():
    west, south, east, north = SEARCH_BOUNDS
    bbox = f"{south},{west},{north},{east}"
    return f"""[out:json][timeout:120];
(
  way[\"waterway\"=\"river\"]({bbox});
  way[\"natural\"=\"water\"]({bbox});
  way[\"water\"=\"river\"]({bbox});
  way[\"landuse\"=\"farmland\"]({bbox});
  relation[\"landuse\"=\"farmland\"]({bbox});
  way[\"highway\"]({bbox});
  way[\"building\"]({bbox});
);
out tags geom;"""


def fetch_osm(refresh=False):
    if RAW_OSM_PATH.is_file() and not refresh:
        return load_json(RAW_OSM_PATH)
    payload = request_bytes(
        OVERPASS_URL,
        urllib.parse.urlencode({"data": overpass_query()}).encode("utf-8"),
    )
    RAW_OSM_PATH.write_bytes(payload)
    return json.loads(payload)


def projected_points(geometry):
    result = []
    for item in geometry or []:
        if "lon" not in item or "lat" not in item:
            continue
        result.append(TO_UTM.transform(item["lon"], item["lat"]))
    return result


def safe_polygon(points):
    if len(points) < 4:
        return None
    if points[0] != points[-1]:
        points = points + [points[0]]
    polygon = Polygon(points)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    return polygon if not polygon.is_empty and polygon.area >= 5 else None


def relation_farmland(element):
    closed = []
    open_lines = []
    for member in element.get("members", []):
        if member.get("type") != "way" or member.get("role", "") not in {"", "outer"}:
            continue
        points = projected_points(member.get("geometry"))
        if len(points) < 2:
            continue
        if len(points) >= 4 and points[0] == points[-1]:
            polygon = safe_polygon(points)
            if polygon:
                closed.append(polygon)
        else:
            open_lines.append(LineString(points))
    if open_lines:
        merged = unary_union(open_lines)
        closed.extend(list(polygonize(merged)))
    if not closed:
        return []
    unioned = unary_union(closed)
    return list(unioned.geoms) if unioned.geom_type == "MultiPolygon" else [unioned]


def parse_osm(osm):
    river_lines = []
    water_polygons = []
    farmland = []
    roads = []
    buildings = []

    for element in osm.get("elements", []):
        tags = element.get("tags") or {}
        if element.get("type") == "relation" and tags.get("landuse") == "farmland":
            farmland.extend(relation_farmland(element))
            continue
        if element.get("type") != "way":
            continue
        points = projected_points(element.get("geometry"))
        if len(points) < 2:
            continue
        closed = len(points) >= 4 and points[0] == points[-1]
        name = str(tags.get("name", ""))

        if tags.get("waterway") == "river" and ("미호" in name or not name):
            river_lines.append(LineString(points))
        if closed and (tags.get("natural") == "water" or tags.get("water") == "river"):
            polygon = safe_polygon(points)
            if polygon:
                water_polygons.append(polygon)
        if closed and tags.get("landuse") == "farmland":
            polygon = safe_polygon(points)
            if polygon:
                farmland.append(polygon)
        if "highway" in tags:
            roads.append({
                "geometry": LineString(points),
                "kind": tags.get("highway"),
                "bridge": tags.get("bridge") not in (None, "no"),
            })
        if closed and "building" in tags:
            polygon = safe_polygon(points)
            if polygon:
                buildings.append(polygon)

    if not river_lines:
        raise RuntimeError("No Miho River centreline was returned by OSM")
    return {
        "river": unary_union(river_lines),
        "water": unary_union(water_polygons) if water_polygons else Polygon(),
        "farmland": unary_union(farmland) if farmland else Polygon(),
        "roads": roads,
        "buildings": unary_union(buildings) if buildings else Polygon(),
    }


def official_miho_zone():
    path = next(UJ201_DIR.glob("*.shp"))
    reader = shapefile.Reader(str(path), encoding="euc-kr", encodingErrors="replace")
    fields = [field[0] for field in reader.fields[1:]]
    matches = []
    for record in reader.iterShapeRecords():
        props = dict(zip(fields, record.record))
        if "미호강" not in str(props.get("ALIAS", "")):
            continue
        geometry = shape(record.shape.__geo_interface__)
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        matches.append(transform(NATIVE_TO_UTM.transform, geometry))
    if not matches:
        raise RuntimeError("Official Miho UJ201 zone not found")
    return unary_union(matches)


def read_hgt():
    values = array("h")
    with HGT_PATH.open("rb") as source:
        values.fromfile(source, HGT_GRID_SIZE * HGT_GRID_SIZE)
    if sys.byteorder == "little":
        values.byteswap()
    return values


def sample_hgt(values, lon, lat):
    column = round((lon - HGT_TILE_WEST) * (HGT_GRID_SIZE - 1))
    row = round(((HGT_TILE_SOUTH + 1.0) - lat) * (HGT_GRID_SIZE - 1))
    column = max(0, min(HGT_GRID_SIZE - 1, column))
    row = max(0, min(HGT_GRID_SIZE - 1, row))
    value = int(values[row * HGT_GRID_SIZE + column])
    return None if value == -32768 else value


def flatness(values, centre_x, centre_y):
    samples = []
    for dx in (-400, -200, 0, 200, 400):
        for dy in (-400, -200, 0, 200, 400):
            lon, lat = TO_WGS.transform(centre_x + dx, centre_y + dy)
            value = sample_hgt(values, lon, lat)
            if value is not None:
                samples.append(value)
    return max(samples) - min(samples) if samples else 999


def station_data():
    snapshot = load_json(HYDRO_SNAPSHOT_PATH)
    station = next(item for item in snapshot["stations"] if item["code"] == snapshot["primary_station_code"])
    x, y = TO_UTM.transform(station["longitude"], station["latitude"])
    return station, (x, y)


def longest_lines(geometry):
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return sorted(geometry.geoms, key=lambda item: item.length, reverse=True)
    merged = linemerge(geometry)
    if isinstance(merged, LineString):
        return [merged]
    return sorted(getattr(merged, "geoms", []), key=lambda item: item.length, reverse=True)


def generate_centres(river, station_xy):
    points = []
    for line in longest_lines(river):
        if line.length < 300:
            continue
        offset = 250.0
        while offset < line.length:
            point = line.interpolate(offset)
            lon, lat = TO_WGS.transform(point.x, point.y)
            if SEARCH_BOUNDS[0] <= lon <= SEARCH_BOUNDS[2] and SEARCH_BOUNDS[1] <= lat <= SEARCH_BOUNDS[3]:
                points.append((point.x, point.y))
            offset += 450.0
    nearest = river.interpolate(river.project(shape({"type": "Point", "coordinates": station_xy}))) if isinstance(river, LineString) else None
    if nearest:
        points.append((nearest.x, nearest.y))
    unique = []
    for point in points:
        if all(math.hypot(point[0] - other[0], point[1] - other[1]) >= 180 for other in unique):
            unique.append(point)
    return unique


def score_candidate(index, centre, layers, official_zone, hgt_values, station_xy):
    x, y = centre
    aoi = box(x - AOI_HALF_M, y - AOI_HALF_M, x + AOI_HALF_M, y + AOI_HALF_M)
    central = box(x - 250, y - 250, x + 250, y + 250)
    farmland_area = layers["farmland"].intersection(aoi).area
    official_area = official_zone.intersection(aoi).area
    water_area = layers["water"].intersection(aoi).area
    river_length = layers["river"].intersection(aoi).length
    river_central_length = layers["river"].intersection(central).length
    motorway_length = sum(
        road["geometry"].intersection(aoi).length
        for road in layers["roads"]
        if road["kind"] in {"motorway", "motorway_link", "trunk", "trunk_link"}
    )
    other_road_length = sum(
        road["geometry"].intersection(aoi).length
        for road in layers["roads"]
        if road["kind"] not in {"motorway", "motorway_link", "trunk", "trunk_link"}
    )
    building_area = layers["buildings"].intersection(aoi).area
    station_distance = math.hypot(x - station_xy[0], y - station_xy[1])
    elevation_range = flatness(hgt_values, x, y)

    farmland_score = min(1.0, farmland_area / 550_000.0)
    motorway_score = max(0.0, 1.0 - motorway_length / 1_500.0)
    official_score = min(1.0, official_area / 250_000.0)
    river_score = min(1.0, river_length / 1_000.0) * 0.65 + min(1.0, river_central_length / 350.0) * 0.35
    station_score = max(0.0, 1.0 - station_distance / 5_000.0)
    flat_score = max(0.0, 1.0 - elevation_range / 45.0)
    sparse_build_score = max(0.0, 1.0 - building_area / 80_000.0)

    total = (
        farmland_score * 30
        + motorway_score * 20
        + official_score * 15
        + river_score * 15
        + station_score * 10
        + flat_score * 5
        + sparse_build_score * 5
    )
    lon, lat = TO_WGS.transform(x, y)
    return {
        "id": f"C{index:02d}",
        "centre_wgs84": [lon, lat],
        "centre_utm52n": [x, y],
        "aoi_bounds_wgs84": list(TO_WGS.transform(x - AOI_HALF_M, y - AOI_HALF_M))
        + list(TO_WGS.transform(x + AOI_HALF_M, y + AOI_HALF_M)),
        "score": round(total, 2),
        "metrics": {
            "farmland_area_m2": round(farmland_area, 1),
            "farmland_percent": round(farmland_area / 10_000.0, 1),
            "official_river_zone_area_m2": round(official_area, 1),
            "visible_water_area_m2": round(water_area, 1),
            "river_length_m": round(river_length, 1),
            "river_central_length_m": round(river_central_length, 1),
            "motorway_length_m": round(motorway_length, 1),
            "other_road_length_m": round(other_road_length, 1),
            "building_area_m2": round(building_area, 1),
            "station_distance_m": round(station_distance, 1),
            "elevation_range_m": elevation_range,
        },
        "component_scores": {
            "farmland": round(farmland_score * 30, 2),
            "motorway_avoidance": round(motorway_score * 20, 2),
            "official_river_zone": round(official_score * 15, 2),
            "river_visibility": round(river_score * 15, 2),
            "station_proximity": round(station_score * 10, 2),
            "flatness": round(flat_score * 5, 2),
            "low_building_density": round(sparse_build_score * 5, 2),
        },
    }


def select_spaced(candidates):
    selected = []
    for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True):
        x, y = candidate["centre_utm52n"]
        if all(
            math.hypot(x - other["centre_utm52n"][0], y - other["centre_utm52n"][1])
            >= MIN_CANDIDATE_SPACING_M
            for other in selected
        ):
            selected.append(candidate)
        if len(selected) == TOP_COUNT:
            break
    for rank, candidate in enumerate(selected, 1):
        candidate["rank"] = rank
    return selected


def tile_float(lon, lat, zoom):
    scale = 2**zoom
    x = (lon + 180.0) / 360.0 * scale
    lat_rad = math.radians(max(-85.05112878, min(85.05112878, lat)))
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * scale
    return x, y


def aerial_for(candidate):
    west, south, east, north = candidate["aoi_bounds_wgs84"]
    xw, yn = tile_float(west, north, AERIAL_ZOOM)
    xe, ys = tile_float(east, south, AERIAL_ZOOM)
    min_x, max_x = math.floor(xw), math.floor(xe)
    min_y, max_y = math.floor(yn), math.floor(ys)
    mosaic = Image.new("RGB", ((max_x - min_x + 1) * 256, (max_y - min_y + 1) * 256))
    for tile_y in range(min_y, max_y + 1):
        for tile_x in range(min_x, max_x + 1):
            payload = request_bytes(ESRI_TILE.format(z=AERIAL_ZOOM, x=tile_x, y=tile_y), timeout=45)
            tile = Image.open(io.BytesIO(payload)).convert("RGB")
            mosaic.paste(tile, ((tile_x - min_x) * 256, (tile_y - min_y) * 256))
    crop = (
        round((xw - min_x) * 256),
        round((yn - min_y) * 256),
        round((xe - min_x) * 256),
        round((ys - min_y) * 256),
    )
    image = mosaic.crop(crop).resize((900, 900), Image.Resampling.LANCZOS)
    path = WORK_DIR / f"{candidate['id']}_aerial_z{AERIAL_ZOOM}.jpg"
    image.save(path, quality=92)
    candidate["aerial_path"] = str(path)
    return image


def pixel_xy(lon, lat, bounds, size):
    west, south, east, north = bounds
    return (
        (lon - west) / (east - west) * size[0],
        (north - lat) / (north - south) * size[1],
    )


def draw_geometry(draw, geometry, bounds, size, colour, width=3, fill=None):
    if geometry.is_empty:
        return
    clipped_wgs = transform(TO_WGS.transform, geometry)
    geometries = list(clipped_wgs.geoms) if hasattr(clipped_wgs, "geoms") else [clipped_wgs]
    for item in geometries:
        if isinstance(item, Polygon):
            points = [pixel_xy(lon, lat, bounds, size) for lon, lat in item.exterior.coords]
            if fill:
                draw.polygon(points, fill=fill)
            draw.line(points, fill=colour, width=width, joint="curve")
        elif isinstance(item, LineString):
            points = [pixel_xy(lon, lat, bounds, size) for lon, lat in item.coords]
            if len(points) >= 2:
                draw.line(points, fill=colour, width=width, joint="curve")


def font(size):
    path = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def candidate_visual(candidate, image, layers, official_zone, station_xy):
    bounds = candidate["aoi_bounds_wgs84"]
    x, y = candidate["centre_utm52n"]
    aoi = box(x - AOI_HALF_M, y - AOI_HALF_M, x + AOI_HALF_M, y + AOI_HALF_M)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    draw_geometry(draw, layers["farmland"].intersection(aoi), bounds, image.size, (40, 255, 60, 220), 3, (30, 220, 50, 45))
    draw_geometry(draw, official_zone.intersection(aoi), bounds, image.size, (0, 225, 255, 230), 4)
    draw_geometry(draw, layers["river"].intersection(aoi), bounds, image.size, (0, 80, 255, 255), 8)
    for road in layers["roads"]:
        if road["kind"] in {"motorway", "motorway_link", "trunk", "trunk_link"}:
            draw_geometry(draw, road["geometry"].intersection(aoi), bounds, image.size, (255, 25, 20, 230), 5)
    station_point = shape({"type": "Point", "coordinates": station_xy})
    if station_point.within(aoi):
        lon, lat = TO_WGS.transform(*station_xy)
        px, py = pixel_xy(lon, lat, bounds, image.size)
        draw.ellipse((px - 12, py - 12, px + 12, py + 12), fill=(255, 220, 0, 255), outline=(0, 0, 0, 255), width=3)
    composed = Image.alpha_composite(image.convert("RGBA"), overlay)
    panel = Image.new("RGBA", (900, 1050), (20, 24, 29, 255))
    panel.paste(composed, (0, 0))
    text = ImageDraw.Draw(panel)
    metrics = candidate["metrics"]
    title = f"{candidate['id']}  점수 {candidate['score']:.1f}"
    details = (
        f"농경지 {metrics['farmland_percent']:.1f}%  |  미호강 {metrics['river_length_m']:.0f}m  |  "
        f"고속도로 {metrics['motorway_length_m']:.0f}m\n"
        f"관측소 {metrics['station_distance_m']:.0f}m  |  표고차 {metrics['elevation_range_m']}m  |  "
        f"중심 {candidate['centre_wgs84'][0]:.5f}, {candidate['centre_wgs84'][1]:.5f}"
    )
    text.text((24, 920), title, font=font(38), fill=(255, 255, 255, 255))
    text.multiline_text((24, 970), details, font=font(22), fill=(220, 226, 232, 255), spacing=6)
    out = REPORT_DIR / f"{candidate['id']}_evaluation.jpg"
    panel.convert("RGB").save(out, quality=93)
    candidate["evaluation_image"] = str(out)
    return panel.convert("RGB")


def contact_sheet(images):
    cell_w, cell_h = 900, 1050
    columns = 2
    rows = math.ceil(len(images) / columns)
    sheet = Image.new("RGB", (cell_w * columns, cell_h * rows), (12, 15, 18))
    for index, image in enumerate(images):
        sheet.paste(image, ((index % columns) * cell_w, (index // columns) * cell_h))
    sheet.save(CONTACT_SHEET, quality=92)


def report_markdown(selected, station, floodmap_meta):
    winner = selected[0]
    rows = []
    for item in selected:
        m = item["metrics"]
        rows.append(
            f"| {item['rank']} | {item['id']} | {item['score']:.1f} | "
            f"{m['farmland_percent']:.1f}% | {m['river_length_m']:.0f}m | "
            f"{m['motorway_length_m']:.0f}m | {m['station_distance_m']:.0f}m | "
            f"{m['elevation_range_m']}m |"
        )
    REPORT_MD.write_text(
        "\n".join(
            [
                "# 미호강 농업 홍수 디지털트윈 파일럿 재선정 V11",
                "",
                "## 평가 원칙",
                "",
                "실제 미호강이 화면 중앙을 통과하고, 연속 농경지가 넓으며, 고속도로와 건축물이 적고, 공식 UJ201 하천구역 및 수위관측소와 연결되는 1km 구역을 우선한다.",
                "",
                "| 순위 | 후보 | 총점 | 농경지 | 미호강 길이 | 고속도로 | 관측소 거리 | 표고차 |",
                "|---:|---|---:|---:|---:|---:|---:|---:|",
                *rows,
                "",
                "## 자동 선정 결과",
                "",
                f"- 최종 후보: **{winner['id']}**",
                f"- 중심좌표: `{winner['centre_wgs84'][0]:.7f}, {winner['centre_wgs84'][1]:.7f}`",
                f"- 연결 관측소: {station['name']} ({station['code']}), 약 {winner['metrics']['station_distance_m']:.0f}m",
                f"- 농경지 비율: {winner['metrics']['farmland_percent']:.1f}%",
                f"- AOI 내 미호강 길이: {winner['metrics']['river_length_m']:.0f}m",
                f"- 고속도로 길이: {winner['metrics']['motorway_length_m']:.0f}m",
                "",
                "## 주의",
                "",
                "- OSM 농경지는 토지피복 참고값이며 지적 필지가 아니다. V11 장면에서는 대표 농경지 후보를 시각적으로 고른 뒤 실제 등록 경계로 교체해야 한다.",
                "- 기존 홍수 PNG는 지방하천 50년 빈도 레이어다. 국가하천 미호강의 범람 근거로 점수에 사용하지 않았다.",
                f"- 제외된 홍수지도 메타데이터: `{floodmap_meta['dataset']}`",
                "- 자동 점수 1위는 항공영상 비교 결과와 함께 최종 검토해야 한다.",
            ]
        ),
        encoding="utf-8",
    )


def main():
    refresh = "--refresh" in sys.argv
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    osm = fetch_osm(refresh=refresh)
    layers = parse_osm(osm)
    official_zone = official_miho_zone()
    station, station_xy = station_data()
    hgt_values = read_hgt()
    centres = generate_centres(layers["river"], station_xy)
    candidates = [
        score_candidate(index + 1, centre, layers, official_zone, hgt_values, station_xy)
        for index, centre in enumerate(centres)
    ]
    selected = select_spaced(candidates)
    if len(selected) < TOP_COUNT:
        raise RuntimeError(f"Only {len(selected)} spaced candidates were generated")

    visuals = []
    for candidate in selected:
        aerial = aerial_for(candidate)
        visuals.append(candidate_visual(candidate, aerial, layers, official_zone, station_xy))
    contact_sheet(visuals)

    floodmap_meta = load_json(FLOODMAP_META_PATH)
    winner = selected[0]
    payload = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "Miho centreline sampling and weighted GIS screening",
        "weights": {
            "farmland": 30,
            "motorway_avoidance": 20,
            "official_river_zone": 15,
            "river_visibility": 15,
            "station_proximity": 10,
            "flatness": 5,
            "low_building_density": 5,
        },
        "primary_station": {
            "code": station["code"],
            "name": station["name"],
            "longitude": station["longitude"],
            "latitude": station["latitude"],
        },
        "candidate_count": len(candidates),
        "top_candidates": selected,
        "selected_candidate_id": winner["id"],
        "excluded_evidence": {
            "floodmap_dataset": floodmap_meta["dataset"],
            "reason": "local-river scenario layer is not treated as a national Miho River inundation model",
        },
        "contact_sheet": str(CONTACT_SHEET),
    }
    RESULT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_markdown(selected, station, floodmap_meta)
    SELECTED_CONFIG.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "pilot_id": "MIHO-AGRI-V11",
                "selection_status": "gis_screened_requires_visual_confirmation",
                "selected_candidate_id": winner["id"],
                "centre_wgs84": winner["centre_wgs84"],
                "aoi_bounds_wgs84": winner["aoi_bounds_wgs84"],
                "aoi_size_m": [1000.0, 1000.0],
                "river": "미호강",
                "water_level_station": {"code": station["code"], "name": station["name"]},
                "field_geometry_status": "not_selected_do_not_reuse_mvp_farmland",
                "source_report": str(RESULT_JSON),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "ok",
        "generated_candidates": len(candidates),
        "top_candidates": [
            {"rank": item["rank"], "id": item["id"], "score": item["score"], "centre": item["centre_wgs84"]}
            for item in selected
        ],
        "selected": winner["id"],
        "contact_sheet": str(CONTACT_SHEET),
        "config": str(SELECTED_CONFIG),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
