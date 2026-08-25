#!/usr/bin/env python3
"""Prepare V22 selective 3D structures for the field and shelter look-dev.

Verified OSM footprints remain authoritative vector objects.  Roofs detected
from the z19 aerial are explicitly stored as image-derived visual proxies and
must not be presented as surveyed buildings or cadastral structures.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
from pyproj import Transformer
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
V21_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_visual_v21_context.json"
SHELTER_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_shelter_v19_hq.json"
OUTER_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_shelter_v19_outer.json"
CONTEXT_PATH = ROOT / "data" / "processed" / "osong_visual_v22_context.json"
MANIFEST_PATH = ROOT / "data" / "processed" / "osong_visual_v22_manifest.json"
REPORT_PATH = ROOT / "output" / "visual_v22" / "preparation_report.json"
DEBUG_PATH = ROOT / "output" / "visual_v22" / "image_proxy_candidates.png"

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
CORE_SIZE_M = 1500.0
HALF = CORE_SIZE_M / 2.0


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ordered_box(points):
    centre_x = sum(point[0] for point in points) / len(points)
    centre_y = sum(point[1] for point in points) / len(points)
    return sorted(points, key=lambda point: math.atan2(point[1] - centre_y, point[0] - centre_x))


def pixel_to_local(u, v, width, height, bounds, origin):
    west, south, east, north = map(float, bounds)
    lon = west + float(u) / width * (east - west)
    lat = north - float(v) / height * (north - south)
    x, y = TO_UTM.transform(lon, lat)
    return [round(x - origin[0], 3), round(y - origin[1], 3)]


def river_geometry_from_mesh(mesh):
    polygons = []
    vertices = mesh["vertices"]
    for face in mesh["faces"]:
        polygon = Polygon([(vertices[index][0], vertices[index][1]) for index in face]).buffer(0)
        if not polygon.is_empty and polygon.area > 0.01:
            polygons.append(polygon)
    return unary_union(polygons).buffer(0)


def image_proxy_candidates(v21):
    image_path = Path(v21["aerial"]["path"])
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"Cannot read V21 aerial image: {image_path}")
    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    white = ((saturation < 55) & (value > 150)).astype(np.uint8) * 255
    cyan = (
        (hue >= 75) & (hue <= 115) &
        (saturation >= 22) & (saturation <= 150) &
        (value > 105)
    ).astype(np.uint8) * 255
    mask = cv2.bitwise_or(white, cyan)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    scale_x = CORE_SIZE_M / width
    scale_y = CORE_SIZE_M / height
    mean_scale = (scale_x + scale_y) / 2.0
    origin = tuple(map(float, v21["origin_utm52n"]))
    river = river_geometry_from_mesh(v21["river"]["mesh"])
    roads = unary_union([
        LineString(road["path"]).buffer(max(2.5, float(road["width_m"]) / 2.0 + 1.5))
        for road in v21["roads"] if len(road["path"]) >= 2
    ]).buffer(0)

    candidates = []
    for contour in contours:
        area_px = float(cv2.contourArea(contour))
        rect = cv2.minAreaRect(contour)
        (_cx, _cy), (side_a, side_b), _angle = rect
        if side_a <= 0 or side_b <= 0:
            continue
        long_m = max(side_a, side_b) * mean_scale
        short_m = min(side_a, side_b) * mean_scale
        area_m2 = area_px * scale_x * scale_y
        fill_ratio = area_px / (side_a * side_b)
        aspect_ratio = long_m / max(short_m, 0.001)
        if not (
            60.0 <= area_m2 <= 5000.0 and
            5.0 <= short_m <= 45.0 and
            15.0 <= long_m <= 180.0 and
            aspect_ratio >= 1.5 and
            fill_ratio >= 0.36
        ):
            continue
        pixel_box = cv2.boxPoints(rect)
        local_box = ordered_box([
            pixel_to_local(point[0], point[1], width, height, v21["aerial"]["bounds_wgs84"], origin)
            for point in pixel_box
        ])
        footprint = Polygon(local_box).buffer(0)
        if footprint.is_empty or footprint.area < 40.0:
            continue
        river_overlap = footprint.intersection(river).area / footprint.area
        road_overlap = footprint.intersection(roads).area / footprint.area if not roads.is_empty else 0.0
        if river_overlap > 0.08 or road_overlap > 0.45:
            continue

        contour_mask = np.zeros((height, width), dtype=np.uint8)
        cv2.drawContours(contour_mask, [contour], -1, 255, -1)
        mean_h, mean_s, mean_v, _ = cv2.mean(hsv, mask=contour_mask)
        greenhouse_score = (
            0.44 * min(1.0, (aspect_ratio - 1.2) / 3.0) +
            0.32 * min(1.0, fill_ratio) +
            0.24 * (1.0 if (mean_s < 95 and mean_v > 125) else 0.45)
        )
        if aspect_ratio >= 2.15 and short_m <= 30.0 and greenhouse_score >= 0.50:
            kind = "greenhouse_visual_proxy"
            height_m = 4.2
        elif area_m2 >= 900.0:
            kind = "large_roof_visual_proxy"
            height_m = 7.2
        else:
            kind = "roof_visual_proxy"
            height_m = 5.8
        confidence = max(0.45, min(0.92, 0.42 + fill_ratio * 0.28 + min(aspect_ratio, 5.0) * 0.035))
        candidates.append({
            "candidate_id": "",
            "kind": kind,
            "source_role": "image-derived visual proxy",
            "surveyed": False,
            "cadastral": False,
            "confidence": round(confidence, 3),
            "area_m2": round(float(footprint.area), 1),
            "long_m": round(long_m, 2),
            "short_m": round(short_m, 2),
            "height_m": height_m,
            "mean_hsv": [round(mean_h, 1), round(mean_s, 1), round(mean_v, 1)],
            "polygon": [[round(x, 3), round(y, 3)] for x, y in local_box],
        })

    candidates.sort(key=lambda item: (item["kind"] != "greenhouse_visual_proxy", -item["confidence"], -item["area_m2"]))
    candidates = candidates[:120]
    for index, item in enumerate(candidates, start=1):
        item["candidate_id"] = f"V22-IMG-{index:03d}"

    debug = image.copy()
    for item in candidates:
        pixels = []
        west, south, east, north = map(float, v21["aerial"]["bounds_wgs84"])
        for x, y in item["polygon"]:
            lon, lat = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True).transform(origin[0] + x, origin[1] + y)
            u = round((lon - west) / (east - west) * width)
            v = round((north - lat) / (north - south) * height)
            pixels.append([u, v])
        colour = (0, 220, 255) if item["kind"] == "greenhouse_visual_proxy" else (0, 80, 255)
        cv2.polylines(debug, [np.array(pixels, dtype=np.int32)], True, colour, 3)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(DEBUG_PATH), debug, [cv2.IMWRITE_PNG_COMPRESSION, 4])
    return candidates, {"contour_count": len(contours), "debug_path": str(DEBUG_PATH)}


def main():
    v21 = load_json(V21_CONTEXT_PATH)
    shelter = load_json(SHELTER_CONTEXT_PATH)
    proxies, detection = image_proxy_candidates(v21)
    generated = datetime.now(timezone.utc).isoformat()
    actual_shelter_buildings = []
    for item in shelter["buildings"]:
        copied = dict(item)
        copied["source_role"] = "verified OSM footprint"
        copied["surveyed"] = False
        copied["cadastral"] = False
        actual_shelter_buildings.append(copied)

    payload = {
        "schema_version": "1.0",
        "dataset_id": "OSONG-VISUAL-V22",
        "generated_at_utc": generated,
        "source_v21_context": str(V21_CONTEXT_PATH),
        "crs": "EPSG:32652",
        "origin_utm52n": v21["origin_utm52n"],
        "field_core": {
            "size_m": [CORE_SIZE_M, CORE_SIZE_M],
            "verified_osm_buildings": v21["buildings"],
            "image_derived_visual_proxies": proxies,
            "proxy_detection": {
                "method": "HSV roof candidate segmentation plus oriented rectangles and GIS exclusions",
                "source_image": v21["aerial"]["path"],
                "source_zoom": v21["aerial"]["zoom"],
                **detection,
            },
        },
        "shelter_core": {
            "name": shelter["shelter"]["name"],
            "actual_osm_buildings": actual_shelter_buildings,
            "building_count": len(actual_shelter_buildings),
            "source_context": str(SHELTER_CONTEXT_PATH),
        },
        "render_policy": {
            "source_blend": str(ROOT / "blender" / "osong_visual_v21.blend"),
            "preserve_v20_camera": True,
            "preserve_v21_water_and_flood": True,
            "final_mp4": False,
        },
        "validation": {
            "field_verified_osm_building_count": len(v21["buildings"]),
            "field_image_proxy_count": len(proxies),
            "greenhouse_proxy_count": sum(item["kind"] == "greenhouse_visual_proxy" for item in proxies),
            "other_roof_proxy_count": sum(item["kind"] != "greenhouse_visual_proxy" for item in proxies),
            "shelter_actual_osm_building_count": len(actual_shelter_buildings),
            "all_proxies_explicitly_labelled": all(item["source_role"] == "image-derived visual proxy" for item in proxies),
            "video_rendered": False,
        },
        "limitations": [
            "Image-derived field structures are visual proxies and are not surveyed or cadastral buildings.",
            "OSM shelter footprints are mapped geometry but not an authoritative building register.",
            "Proxy heights are type-based visual defaults, not measured heights.",
            "The underlying z19 aerial remains a 2D orthographic texture.",
        ],
    }
    CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTEXT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "dataset_id": "OSONG-VISUAL-V22-MANIFEST",
        "generated_at_utc": generated,
        "status": "prepared_without_blender_or_video",
        "source_v21_unchanged": True,
        "files": [
            {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in (CONTEXT_PATH, V21_CONTEXT_PATH, SHELTER_CONTEXT_PATH, Path(v21["aerial"]["path"]))
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "status": "ok",
        "context": str(CONTEXT_PATH),
        "manifest": str(MANIFEST_PATH),
        **payload["validation"],
        "debug_image": str(DEBUG_PATH),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
