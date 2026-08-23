"""Validate the saved farmland-v4 blend in a fresh Blender process."""

import json
from pathlib import Path

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
REPORT_PATH = ROOT / "output" / "farmland_v4_saved_blend_check.json"
FIELD_ID = "GANGNAE-DEMO-001"

collection = bpy.data.collections.get("DT_FARMLAND_V4")
failures = []
if collection is None:
    failures.append("DT_FARMLAND_V4 collection is missing")
    objects = []
else:
    objects = list(collection.objects)

field = bpy.data.objects.get(f"Field_{FIELD_ID}")
border = bpy.data.objects.get(f"FieldBoundary_{FIELD_ID}")
label = bpy.data.objects.get(f"FieldLabel_{FIELD_ID}")
focus_camera = bpy.data.objects.get("Camera_Farmland_Focus_V4")
main_camera = bpy.data.objects.get("Camera_Gangnae_Hydro_V3")

for name, obj in (("field", field), ("border", border), ("label", label), ("focus camera", focus_camera), ("main camera", main_camera)):
    if obj is None:
        failures.append(f"{name} is missing")

tube_curves = [
    obj.name
    for obj in objects
    if obj.type == "CURVE" and getattr(obj.data, "bevel_depth", 0.0) > 0.0
]
if tube_curves:
    failures.append(f"tube curves remain: {tube_curves}")

camera_frames = [1, 48, 96]
camera_positions = {}
if main_camera and main_camera.animation_data and main_camera.animation_data.action:
    for frame in camera_frames:
        bpy.context.scene.frame_set(frame)
        camera_positions[str(frame)] = [round(value, 3) for value in main_camera.matrix_world.translation]
    if len({tuple(position) for position in camera_positions.values()}) != 3:
        failures.append(f"camera motion invalid: {camera_positions}")
else:
    camera_frames = []
    failures.append("main camera animation is missing")

animated_materials = []
for name in ("Material_V4_FieldFill", "Material_V4_FieldBorder"):
    material = bpy.data.materials.get(name)
    if material and (
        material.animation_data
        or (material.node_tree and any(node.id_data.animation_data for node in material.node_tree.nodes))
    ):
        animated_materials.append(name)
if len(animated_materials) != 2:
    failures.append(f"animated materials invalid: {animated_materials}")

if field is not None:
    if field.get("geometry_accuracy") != "demo_candidate_not_cadastral":
        failures.append("field geometry accuracy is not labelled as demo")
    if field.get("risk_is_calculated") is not False:
        failures.append("field risk must remain explicitly uncalculated")

text_dump = "\n".join(
    str(value)
    for obj in objects
    for value in [obj.name, *[obj.get(key) for key in obj.keys()]]
)
api_key_markers = [marker for marker in ("1FB4A0FE", "HRFCO_API_KEY") if marker in text_dump]
if api_key_markers:
    failures.append(f"API key marker found: {api_key_markers}")

report = {
    "status": "failed" if failures else "ok",
    "scene": bpy.context.scene.name,
    "field_present": field is not None,
    "border_present": border is not None,
    "label_present": label is not None,
    "focus_camera_present": focus_camera is not None,
    "active_camera": bpy.context.scene.camera.name if bpy.context.scene.camera else None,
    "camera_keyframes": camera_frames,
    "camera_positions": camera_positions,
    "animated_materials": animated_materials,
    "tube_curve_count": len(tube_curves),
    "api_key_markers": api_key_markers,
    "failures": failures,
}
REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if failures:
    raise RuntimeError("; ".join(failures))
