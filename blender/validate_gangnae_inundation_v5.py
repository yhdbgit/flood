"""Validate saved V5 blend in a fresh Blender process."""

import json
from pathlib import Path

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
REPORT_PATH = ROOT / "output" / "inundation_v5_saved_blend_check.json"
FIELD_ID = "GANGNAE-DEMO-001"
FRAMES = {"normal": 1, "attention": 30, "warning": 65, "serious": 100, "focus": 120}

failures = []
collection = bpy.data.collections.get("DT_INUNDATION_V5")
objects = list(collection.objects) if collection else []
if collection is None:
    failures.append("DT_INUNDATION_V5 collection is missing")

flood_objects = {code: bpy.data.objects.get(f"Inundation_{code}") for code in ("attention", "warning", "serious")}
for code, obj in flood_objects.items():
    if obj is None:
        failures.append(f"{code} inundation mesh is missing")
    elif obj.get("accuracy") != "heuristic_demo_not_hydraulic_model":
        failures.append(f"{code} accuracy label is invalid")
    elif obj.get("grid_cell_count", 0) <= 0:
        failures.append(f"{code} inundation mesh is empty")

field = bpy.data.objects.get(f"Field_{FIELD_ID}")
if field is None:
    failures.append("registered field is missing")
    field_results = {}
else:
    if field.get("risk_is_calculated") is not True:
        failures.append("field heuristic risk flag is missing")
    if field.get("risk_method") != "heuristic_demo_not_hydraulic_model":
        failures.append("field risk method is invalid")
    field_results = json.loads(field.get("scenario_results_json", "{}"))
    if field_results.get("attention", {}).get("inundated_percent") != 0.0:
        failures.append("attention scenario should not reach the MVP field")
    warning_percent = field_results.get("warning", {}).get("inundated_percent", 0.0)
    serious_percent = field_results.get("serious", {}).get("inundated_percent", 0.0)
    if not 0.0 < warning_percent < 100.0:
        failures.append(f"warning field overlap must be partial: {warning_percent}")
    if serious_percent != 100.0:
        failures.append(f"serious field overlap must be complete: {serious_percent}")

visibility = {}
for code, frame in (("attention", 30), ("warning", 65), ("serious", 100)):
    bpy.context.scene.frame_set(frame)
    visibility[code] = {name: not obj.hide_render for name, obj in flood_objects.items() if obj}
    if visibility[code].get(code) is not True or sum(visibility[code].values()) != 1:
        failures.append(f"exclusive visibility invalid at {frame}: {visibility[code]}")

camera = bpy.data.objects.get("Camera_Gangnae_Hydro_V3")
camera_positions = {}
if camera and camera.animation_data and camera.animation_data.action:
    for code, frame in FRAMES.items():
        bpy.context.scene.frame_set(frame)
        camera_positions[code] = [round(value, 3) for value in camera.matrix_world.translation]
    if len({tuple(value) for value in camera_positions.values()}) < 3:
        failures.append(f"camera movement is insufficient: {camera_positions}")
else:
    failures.append("animated main camera is missing")

tube_curves = [obj.name for obj in objects if obj.type == "CURVE" and getattr(obj.data, "bevel_depth", 0.0) > 0.0]
if tube_curves:
    failures.append(f"tube curves found: {tube_curves}")

text_dump = "\n".join(str(value) for obj in objects for value in [obj.name, *[obj.get(key) for key in obj.keys()]])
api_key_markers = [marker for marker in ("1FB4A0FE", "HRFCO_API_KEY") if marker in text_dump]
if api_key_markers:
    failures.append(f"API key marker found: {api_key_markers}")

report = {
    "status": "failed" if failures else "ok",
    "scene": bpy.context.scene.name,
    "flood_mesh_count": sum(obj is not None for obj in flood_objects.values()),
    "flood_cells": {code: obj.get("grid_cell_count") for code, obj in flood_objects.items() if obj},
    "field_results": field_results,
    "visibility": visibility,
    "camera_positions": camera_positions,
    "tube_curve_count": len(tube_curves),
    "api_key_markers": api_key_markers,
    "failures": failures,
}
REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if failures:
    raise RuntimeError("; ".join(failures))
