#!/usr/bin/env python3
"""Prepare the selected Osong/Miho V11 GIS scene without touching V9/V10.

The selected agricultural geometry is the actual OSM landuse=farmland way
inside the C19 AOI.  It is deliberately labelled as land-cover reference,
not as a cadastral ownership parcel.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from pyproj import Transformer
import shapefile
from shapely.geometry import LineString, MultiPolygon, Polygon, box, shape
from shapely.ops import transform, unary_union


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
PILOT_PATH = ROOT / "config" / "pilot_area_v11.json"
OSM_PATH = ROOT / "data" / "gis" / "pilot_selection_v11" / "expanded_osm_raw.json"
UJ201_DIR = ROOT / "data" / "source" / "hydro" / "UJ201"

FIELD_PATH = ROOT / "config" / "osong_farmland_v11.json"
HYDRO_PATH = ROOT / "data" / "processed" / "osong_hydro_reference_v11.json"
CONTEXT_PATH = ROOT / "data" / "processed" / "osong_hq_v11_context.json"
DATA_DIR = ROOT / "data" / "gis" / "osong_hq_v11"
REPORT_PATH = ROOT / "output" / "hq_v11" / "preparation_report.json"
ATTRIBUTION_PATH = DATA_DIR / "ATTRIBUTION.txt"

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
TO_WGS = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)
NATIVE_TO_UTM = Transformer.from_crs("EPSG:5174", "EPSG:32652", always_xy=True)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def polygon_parts(geometry):
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return [item for item in getattr(geometry, "geoms", []) if isinstance(item, Polygon)]


def select_osm_farmland(raw: dict, pilot: dict) -> tuple[dict, Polygon]:
    centre_x, centre_y = pilot["centre_utm52n"]
    # Keep a small inset so Blender's strict inside-AOI validation remains true.
    aoi = box(centre_x - 497, centre_y - 497, centre_x + 497, centre_y + 497)
    candidates = []
    for element in raw.get("elements", []):
        tags = element.get("tags") or {}
        geometry = element.get("geometry") or []
        if element.get("type") != "way" or tags.get("landuse") != "farmland":
            continue
        if len(geometry) < 4:
            continue
        points = [TO_UTM.transform(item["lon"], item["lat"]) for item in geometry]
        if points[0] != points[-1]:
            points.append(points[0])
        polygon = Polygon(points)
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        clipped = polygon.intersection(aoi)
        for part in polygon_parts(clipped):
            if part.area >= 1000:
                candidates.append((part.area, element, part))
    if not candidates:
        raise RuntimeError("No OSM farmland polygon intersects the selected C19 AOI")
    _, element, selected = max(candidates, key=lambda item: item[0])
    return element, selected


def write_field(element: dict, polygon: Polygon, pilot: dict) -> dict:
    coordinates = [list(TO_WGS.transform(x, y)) for x, y in polygon.exterior.coords]
    centre_lon, centre_lat = TO_WGS.transform(polygon.centroid.x, polygon.centroid.y)
    result = {
        "schema_version": "1.0",
        "field_id": "OSONG-OSM-FARMLAND-378002205",
        "display_name": "오송읍 미호강 북측 농경지 토지이용 구역",
        "owner_display_name": "V11 파일럿 농업인",
        "registration_status": "pilot_landcover_selected",
        "geometry_accuracy": "osm_landuse_farmland_not_cadastral",
        "source": {
            "provider": "OpenStreetMap contributors",
            "element_type": element.get("type"),
            "element_id": element.get("id"),
            "tag": "landuse=farmland",
            "derivation": "largest actual OSM farmland polygon clipped 3 m inside the selected C19 AOI",
        },
        "geometry": {"type": "Polygon", "coordinates": [coordinates]},
        "derived_metrics": {
            "area_m2": round(polygon.area, 1),
            "centre_wgs84": [centre_lon, centre_lat],
            "aoi_centre_wgs84": pilot["centre_wgs84"],
        },
        "limitations": [
            "This is an OSM agricultural land-cover polygon, not a cadastral ownership parcel.",
            "Replace this geometry with user registration or cadastral data before production use.",
        ],
    }
    FIELD_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def write_official_reference(pilot: dict) -> dict:
    centre_x, centre_y = pilot["centre_utm52n"]
    clip = box(centre_x - 500, centre_y - 500, centre_x + 500, centre_y + 500)
    shp_path = next(UJ201_DIR.glob("*.shp"))
    reader = shapefile.Reader(str(shp_path), encoding="euc-kr", encodingErrors="replace")
    fields = [field[0] for field in reader.fields[1:]]
    parts = []
    source_records = []
    for item in reader.iterShapeRecords():
        properties = dict(zip(fields, item.record))
        if "미호강" not in str(properties.get("ALIAS", "")):
            continue
        geometry = shape(item.shape.__geo_interface__)
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        geometry = transform(NATIVE_TO_UTM.transform, geometry).intersection(clip)
        for polygon in polygon_parts(geometry):
            if polygon.area < 10:
                continue
            parts.append({
                "exterior": [
                    [round(x - centre_x, 3), round(y - centre_y, 3)]
                    for x, y in list(polygon.exterior.coords)[:-1]
                ]
            })
        source_records.append(properties)
    if not parts:
        raise RuntimeError("Official VWorld UJ201 Miho River zone does not intersect C19")
    result = {
        "schema_version": "1.0",
        "origin_wgs84": pilot["centre_wgs84"],
        "origin_utm52n": pilot["centre_utm52n"],
        "official_zones": [{
            "id": "riverzone_miho_v11",
            "name": "미호강",
            "source_layer": "VWorld UJ201",
            "classification": "river/use district",
            "polygons": parts,
        }],
        "source_shapefile": str(shp_path),
        "matched_record_count": len(source_records),
    }
    HYDRO_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def update_pilot_config(pilot: dict, field: dict):
    pilot["selection_status"] = "final_pilot_aoi_and_osm_farmland_selected"
    pilot["representative_field"] = {
        "status": "selected_osm_landcover_reference",
        "field_id": field["field_id"],
        "source_element_id": field["source"]["element_id"],
        "area_m2": field["derived_metrics"]["area_m2"],
        "geometry_path": str(FIELD_PATH),
        "accuracy": field["geometry_accuracy"],
        "production_replacement_required": True,
    }
    PILOT_PATH.write_text(json.dumps(pilot, ensure_ascii=False, indent=2), encoding="utf-8")



def merge_visible_river_surface(context: dict) -> dict:
    # Union OSM river polygons and width-buffered river centrelines.
    shapes = []
    source_ids = set()
    for item in context.get("water_polygons", []):
        polygon = Polygon(item["polygon"])
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if not polygon.is_empty:
            shapes.append(polygon)
            source_ids.add(str(item.get("osm_id")))
    remaining_waterways = []
    for item in context.get("waterways", []):
        if item.get("waterway") == "river":
            line = LineString(item["path"])
            shapes.append(line.buffer(float(item.get("width_m", 48.0)) / 2.0, cap_style=2, join_style=2))
            source_ids.add(str(item.get("osm_id")))
        else:
            remaining_waterways.append(item)
    if not shapes:
        return context
    merged = unary_union(shapes).buffer(0).intersection(box(-500, -500, 500, 500))
    polygons = []
    for index, polygon in enumerate(polygon_parts(merged)):
        if polygon.area < 10:
            continue
        polygons.append({
            "osm_id": "merged:" + ",".join(sorted(source_ids)),
            "name": "미호강 및 합류부",
            "water": "river_merged_surface",
            "polygon": [[round(x, 3), round(y, 3)] for x, y in list(polygon.exterior.coords)[:-1]],
            "merged_part_index": index,
        })
    context["water_polygons"] = polygons
    context["waterways"] = remaining_waterways
    context["water_surface_processing"] = {
        "method": "union of OSM water polygons and width-buffered river centrelines",
        "source_osm_ids": sorted(source_ids),
        "purpose": "remove overlapping coplanar river surfaces in Blender",
    }
    context["validation"]["water_polygon_count"] = len(polygons)
    context["validation"]["waterway_count"] = len(remaining_waterways)
    return context

def main():
    pilot = load_json(PILOT_PATH)
    raw = load_json(OSM_PATH)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    element, farmland_polygon = select_osm_farmland(raw, pilot)
    field = write_field(element, farmland_polygon, pilot)
    hydro = write_official_reference(pilot)
    update_pilot_config(pilot, field)

    v10 = load_module("prepare_gangnae_hq_v10_base", ROOT / "scripts" / "prepare_gangnae_hq_v10.py")
    v10.FIELD_PATH = FIELD_PATH
    v10.HYDRO_PATH = HYDRO_PATH
    v10.DATA_DIR = DATA_DIR
    v10.RAW_OSM_PATH = OSM_PATH
    v10.AERIAL_PATH = DATA_DIR / "esri_world_imagery_z18.jpg"
    v10.AERIAL_META_PATH = DATA_DIR / "esri_world_imagery_z18.json"
    v10.ATTRIBUTION_PATH = ATTRIBUTION_PATH
    v10.CONTEXT_PATH = CONTEXT_PATH
    v10.REPORT_PATH = REPORT_PATH
    v10.polygon_centre = lambda _field: tuple(pilot["centre_wgs84"])
    v10.official_reference = lambda _hydro, _origin, _aoi: hydro["official_zones"]

    def write_attribution_v11():
        ATTRIBUTION_PATH.write_text(
            "\n".join([
                "Osong HQ V11 data attribution",
                "",
                "Aerial imagery: Esri World Imagery.",
                "Vector context and agricultural land-cover: OpenStreetMap contributors (ODbL).",
                "Official river/use district: VWorld UJ201 supplied by the project.",
                "Terrain: SRTM 1 arc-second N36E127, approximately 30 m.",
                "",
                "The highlighted agricultural area is OSM land cover, not a cadastral parcel.",
                "The official river polygon is a management/use district, not a live water surface.",
            ]),
            encoding="utf-8",
        )

    v10.write_attribution = write_attribution_v11
    v10.main()

    context = merge_visible_river_surface(load_json(CONTEXT_PATH))
    context["scene"] = "Osong_HQ_V11"
    context["pilot"] = {
        "pilot_id": pilot["pilot_id"],
        "candidate_id": pilot["selected_candidate_id"],
        "display_name": pilot["display_name"],
        "administrative_area": pilot["administrative_area"],
    }
    context["field"]["role"] = "OSM agricultural land-cover reference; not cadastral"
    context["field"]["source_element_id"] = element.get("id")
    context["validation"]["selected_candidate_is_c19"] = pilot["selected_candidate_id"] == "C19"
    context["validation"]["farmland_source_is_osm"] = element.get("id") == 378002205
    CONTEXT_PATH.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")

    report = load_json(REPORT_PATH)
    report.update({
        "scene": "Osong_HQ_V11",
        "pilot_id": pilot["pilot_id"],
        "selected_candidate": pilot["selected_candidate_id"],
        "farmland_source_element_id": element.get("id"),
        "farmland_area_m2": field["derived_metrics"]["area_m2"],
        "field_geometry_is_cadastral": False,
        "official_reference_part_count": sum(len(z["polygons"]) for z in hydro["official_zones"]),
    })
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
