"""Validate the saved Gangnae HQ V10 blend without modifying it."""

import json
from pathlib import Path

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
REPORT_PATH = ROOT / "output" / "hq_v10" / "saved_blend_validation.json"
EXPECTED_RENDERS = [
    ROOT / "output" / "hq_v10" / "gangnae_hq_v10_overview.png",
    ROOT / "output" / "hq_v10" / "gangnae_hq_v10_top.png",
    ROOT / "output" / "hq_v10" / "gangnae_hq_v10_field.png",
]


def objects_with_prefix(prefix):
    return [obj for obj in bpy.data.objects if obj.name.startswith(prefix)]


def main():
    scene = bpy.context.scene
    terrain = bpy.data.objects.get("Terrain_Gangnae_HQ_V10")
    field = bpy.data.objects.get("RegisteredField_V10")
    roads = objects_with_prefix("Road_")
    waterways = objects_with_prefix("Waterway_") + objects_with_prefix("WaterPolygon_")
    buildings = objects_with_prefix("Building_")
    bridges = [obj for obj in roads if bool(obj.get("bridge", False))]
    official = objects_with_prefix("OfficialBoundary_")
    cameras = [obj for obj in bpy.data.objects if obj.type == "CAMERA"]
    images = [image for image in bpy.data.images if image.source == "FILE"]

    checks = {
        "scene_name": scene.name == "Gangnae_HQ_V10",
        "terrain_present": terrain is not None and len(terrain.data.vertices) == 16641,
        "aerial_image_loaded": any("esri_world_imagery_z18" in image.filepath for image in images),
        "road_count": len(roads) == 41,
        "bridge_count": len(bridges) == 2,
        "water_count": len(waterways) == 3,
        "registered_field_present": field is not None,
        "official_reference_present": len(official) == 1,
        "camera_count": len(cameras) == 3,
        "crs": scene.get("SRID") == "EPSG:32652",
        "metric_scale": float(scene.get("scale", 0.0)) == 1.0,
        "aoi_size": list(scene.get("v10_aoi_size_m", [])) == [1000.0, 1000.0],
        "v9_not_modified_flag": scene.get("v10_v9_files_modified") is False,
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
            "bridges": len(bridges),
            "water": len(waterways),
            "buildings": len(buildings),
            "official_reference_boundaries": len(official),
            "cameras": len(cameras),
        },
        "note": (
            "Zero OSM building footprints were returned for this exact 1 km AOI; "
            "no synthetic buildings were invented."
        ),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
