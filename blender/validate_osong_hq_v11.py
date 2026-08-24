"""Validate the saved Osong HQ V11 blend without modifying it."""

import json
from pathlib import Path

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
REPORT_PATH = ROOT / "output" / "hq_v11" / "saved_blend_validation.json"
EXPECTED_RENDERS = [
    ROOT / "output" / "hq_v11" / "osong_hq_v11_overview.png",
    ROOT / "output" / "hq_v11" / "osong_hq_v11_top.png",
    ROOT / "output" / "hq_v11" / "osong_hq_v11_farmland.png",
]


def prefixed(prefix):
    return [obj for obj in bpy.data.objects if obj.name.startswith(prefix)]


def main():
    scene = bpy.context.scene
    terrain = bpy.data.objects.get("Terrain_Osong_HQ_V11")
    field = bpy.data.objects.get("AgriculturalLanduse_V11")
    roads = prefixed("Road_")
    water = prefixed("Waterway_") + prefixed("WaterPolygon_")
    official = prefixed("OfficialBoundary_")
    cameras = [obj for obj in bpy.data.objects if obj.type == "CAMERA"]
    images = [image for image in bpy.data.images if image.source == "FILE"]
    lon = float(scene.get("longitude", 0.0))
    lat = float(scene.get("latitude", 0.0))

    checks = {
        "scene_name": scene.name == "Osong_HQ_V11",
        "terrain_present": terrain is not None and len(terrain.data.vertices) == 16641,
        "aerial_image_loaded": any("osong_hq_v11" in image.filepath for image in images),
        "water_present": len(water) >= 1,
        "roads_present": len(roads) >= 1,
        "farmland_present": field is not None,
        "farmland_not_cadastral": field is not None and field.get("production_replacement_required") is True,
        "official_reference_present": len(official) >= 1,
        "camera_count": len(cameras) == 3,
        "camera_clip_end": all(camera.data.clip_end >= 100_000 for camera in cameras),
        "freeview_clip_end": float(scene.get("v11_freeview_clip_end_m", 0.0)) >= 100_000,
        "crs": scene.get("SRID") == "EPSG:32652",
        "origin_matches_c19": abs(lon - 127.30572825724568) < 1e-7 and abs(lat - 36.58306048243385) < 1e-7,
        "candidate_c19": scene.get("v11_selected_candidate") == "C19",
        "older_files_not_modified_flag": scene.get("v11_v9_v10_files_modified") is False,
        "renders_exist": all(path.is_file() and path.stat().st_size > 0 for path in EXPECTED_RENDERS),
    }
    report = {
        "status": "ok" if all(checks.values()) else "failed",
        "blend_file": bpy.data.filepath,
        "checks": checks,
        "counts": {
            "objects": len(bpy.data.objects),
            "terrain_vertices": len(terrain.data.vertices) if terrain else 0,
            "roads": len(roads),
            "water": len(water),
            "official_reference_boundaries": len(official),
            "cameras": len(cameras),
        },
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
