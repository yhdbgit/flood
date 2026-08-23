"""Validate the saved hydro-v3 blend in a fresh Blender process."""

import json
from pathlib import Path

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
REPORT_PATH = ROOT / "output" / "hydro_v3_saved_blend_check.json"

collection = bpy.data.collections.get("DT_HYDRO_V3")
if collection is None:
    raise RuntimeError("DT_HYDRO_V3 collection is missing")

objects = list(collection.objects)
tube_curves = [
    obj.name
    for obj in objects
    if obj.type == "CURVE" and getattr(obj.data, "bevel_depth", 0.0) > 0.0
]
zone_fills = [obj for obj in objects if obj.name.startswith("ZoneFill_")]
zone_boundaries = [obj for obj in objects if obj.name.startswith("ZoneBoundary_")]
water_surfaces = [obj for obj in objects if obj.name.startswith("WaterSurface_")]
station_heads = [
    obj for obj in objects if obj.name.startswith("StationPin_") and not obj.name.endswith("_Pointer")
]
required_water = {"WaterSurface_미호강", "WaterSurface_태성천"}
missing_water = sorted(required_water - {obj.name for obj in water_surfaces})

text_dump = "\n".join(
    str(value)
    for obj in objects
    for value in [obj.name, *[obj.get(key) for key in obj.keys()]]
)
api_key_markers = [marker for marker in ("1FB4A0FE", "HRFCO_API_KEY") if marker in text_dump]

failures = []
if tube_curves:
    failures.append(f"tube curves remain: {tube_curves}")
if len(zone_fills) != 10:
    failures.append(f"expected 10 zone fills, got {len(zone_fills)}")
if len(zone_boundaries) != 10:
    failures.append(f"expected 10 zone boundaries, got {len(zone_boundaries)}")
if len(water_surfaces) != 2 or missing_water:
    failures.append(f"water surfaces invalid: count={len(water_surfaces)}, missing={missing_water}")
if len(station_heads) != 2:
    failures.append(f"expected 2 station pins, got {len(station_heads)}")
if api_key_markers:
    failures.append(f"API key marker found: {api_key_markers}")
if bpy.data.objects.get("Terrain_Gangnae") is None:
    failures.append("Terrain_Gangnae is missing")

report = {
    "status": "failed" if failures else "ok",
    "scene": bpy.context.scene.name,
    "active_camera": bpy.context.scene.camera.name if bpy.context.scene.camera else None,
    "terrain_present": bpy.data.objects.get("Terrain_Gangnae") is not None,
    "zone_fill_count": len(zone_fills),
    "zone_boundary_count": len(zone_boundaries),
    "water_surface_count": len(water_surfaces),
    "station_count": len(station_heads),
    "tube_curve_count": len(tube_curves),
    "tube_curve_names": tube_curves,
    "missing_required_water": missing_water,
    "api_key_markers": api_key_markers,
    "failures": failures,
}
REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if failures:
    raise RuntimeError("; ".join(failures))
