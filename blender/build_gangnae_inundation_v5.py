"""Build V5 heuristic inundation playback on top of farmland V4.

This is explicitly an MVP visual model. It uses DEM elevation and distance from
the Miho centreline; it is not a hydraulic simulation or an official flood map.
"""

import json
import math
from pathlib import Path
import sys

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
sys.path.insert(0, str(ROOT / "blender"))
import build_gangnae_hydro_v3 as hydro_v3
import build_gangnae_farmland_v4 as farmland_v4


SCENARIO_PATH = ROOT / "config" / "mvp_inundation_scenarios.json"
FIELD_PATH = ROOT / "config" / "mvp_farmland.json"
GEOMETRY_PATH = ROOT / "data" / "processed" / "gangnae_hydro_geometry.json"
SNAPSHOT_PATH = ROOT / "data" / "runtime" / "hydro_snapshot.json"
BLEND_PATH = ROOT / "blender" / "gangnae_inundation_v5.blend"
REPORT_PATH = ROOT / "output" / "inundation_v5_validation_report.json"
RESULT_PATH = ROOT / "output" / "inundation_v5_field_result.json"
RENDER_PATHS = {
    "normal": ROOT / "output" / "gangnae_inundation_v5_normal.png",
    "attention": ROOT / "output" / "gangnae_inundation_v5_attention.png",
    "warning": ROOT / "output" / "gangnae_inundation_v5_warning.png",
    "serious": ROOT / "output" / "gangnae_inundation_v5_serious.png",
}

COLLECTION_NAME = "DT_INUNDATION_V5"
FIELD_ID = "GANGNAE-DEMO-001"
ACCURACY = "heuristic_demo_not_hydraulic_model"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def prepare_collection(scene):
    old = bpy.data.collections.get(COLLECTION_NAME)
    if old is not None:
        for obj in list(old.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for parent in list(bpy.data.collections):
            if old.name in parent.children:
                parent.children.unlink(old)
        if old.name in scene.collection.children:
            scene.collection.children.unlink(old)
        bpy.data.collections.remove(old)
    collection = bpy.data.collections.new(COLLECTION_NAME)
    scene.collection.children.link(collection)
    return collection


def segment_distance(point, start, end):
    px, py = point
    ax, ay = start
    bx, by = end
    dx = bx - ax
    dy = by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0.0:
        return math.hypot(px - ax, py - ay)
    amount = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.hypot(px - (ax + amount * dx), py - (ay + amount * dy))


def distance_to_polyline(x, y, line):
    return min(segment_distance((x, y), start, end) for start, end in zip(line, line[1:]))


def terrain_elevation(hgt_values, x, y, geometry):
    longitude, latitude = hydro_v3.local_to_lonlat(x, y, geometry)
    return float(hydro_v3.sample_elevation(hgt_values, longitude, latitude))


def qualifies(x, y, scenario, miho_line, hgt_values, geometry):
    return (
        distance_to_polyline(x, y, miho_line) <= scenario["max_distance_to_miho_m"]
        and terrain_elevation(hgt_values, x, y, geometry) <= scenario["max_dem_elevation_m"]
    )


def create_inundation_mesh(scenario, geometry, miho_line, hgt_values, collection, material, cell_size):
    terrain_width, terrain_depth, _ = geometry["terrain"]["dimensions_m"]
    min_x = -terrain_width / 2.0
    min_y = -terrain_depth / 2.0
    columns = math.ceil(terrain_width / cell_size)
    rows = math.ceil(terrain_depth / cell_size)
    cell_width = terrain_width / columns
    cell_depth = terrain_depth / rows
    vertices = []
    faces = []
    selected_cells = 0
    for column in range(columns):
        x0 = min_x + column * cell_width
        x1 = x0 + cell_width
        centre_x = (x0 + x1) / 2.0
        for row in range(rows):
            y0 = min_y + row * cell_depth
            y1 = y0 + cell_depth
            centre_y = (y0 + y1) / 2.0
            if not qualifies(centre_x, centre_y, scenario, miho_line, hgt_values, geometry):
                continue
            start = len(vertices)
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                z = hydro_v3.terrain_z(hgt_values, x, y, geometry, extra=3.2)
                vertices.append((x, y, z))
            faces.append((start, start + 1, start + 2, start + 3))
            selected_cells += 1
    mesh = bpy.data.meshes.new(f"Inundation_{scenario['code']}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(f"Inundation_{scenario['code']}", mesh)
    collection.objects.link(obj)
    obj.data.materials.append(material)
    obj["scenario_code"] = scenario["code"]
    obj["scenario_label"] = scenario["label"]
    obj["accuracy"] = ACCURACY
    obj["grid_cell_count"] = selected_cells
    obj["grid_cell_area_m2"] = round(cell_width * cell_depth, 2)
    obj["display_area_m2"] = round(selected_cells * cell_width * cell_depth, 2)
    obj["display_max_depth_m"] = scenario["display_max_depth_m"]
    return obj


def set_exclusive_visibility(objects, frames):
    ordered_codes = list(objects)
    for code, obj in objects.items():
        for frame_code in ("normal", *ordered_codes, "focus"):
            frame = frames[frame_code]
            visible = code == frame_code or (frame_code == "focus" and code == "serious")
            obj.hide_render = not visible
            obj.hide_viewport = not visible
            obj.keyframe_insert("hide_render", frame=frame)
            obj.keyframe_insert("hide_viewport", frame=frame)


def point_in_polygon(x, y, polygon):
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = current
        x2, y2 = previous
        if (y1 > y) != (y2 > y):
            crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing:
                inside = not inside
        previous = current
    return inside


def calculate_field_results(field, geometry, scenarios, miho_line, hgt_values, sample_grid):
    polygon = [farmland_v4.to_local(point, geometry) for point in field["geometry"]["coordinates"][0]]
    if polygon[0] == polygon[-1]:
        polygon.pop()
    min_x = min(point[0] for point in polygon)
    max_x = max(point[0] for point in polygon)
    min_y = min(point[1] for point in polygon)
    max_y = max(point[1] for point in polygon)
    samples = []
    for column in range(sample_grid):
        for row in range(sample_grid):
            x = min_x + (column + 0.5) * (max_x - min_x) / sample_grid
            y = min_y + (row + 0.5) * (max_y - min_y) / sample_grid
            if point_in_polygon(x, y, polygon):
                samples.append((x, y))
    results = {}
    for scenario in scenarios:
        wet = [point for point in samples if qualifies(*point, scenario, miho_line, hgt_values, geometry)]
        ratio = len(wet) / len(samples) if samples else 0.0
        if ratio == 0.0:
            risk_code, risk_label = "normal", "정상"
        elif ratio < 0.75:
            risk_code, risk_label = "warning", "경계"
        else:
            risk_code, risk_label = "serious", "심각"
        results[scenario["code"]] = {
            "scenario_label": scenario["label"],
            "sample_count": len(samples),
            "wet_sample_count": len(wet),
            "inundated_ratio": round(ratio, 4),
            "inundated_percent": round(ratio * 100.0, 1),
            "display_max_depth_m": scenario["display_max_depth_m"] if wet else 0.0,
            "risk_code": risk_code,
            "risk_label": risk_label,
        }
    return results


def reset_field_animation(field_results, frames):
    fill = bpy.data.materials.get("Material_V4_FieldFill")
    border = bpy.data.materials.get("Material_V4_FieldBorder")
    if fill is None or border is None:
        raise RuntimeError("V4 field materials are missing")
    for material in (fill, border):
        material.animation_data_clear()
        if material.node_tree:
            material.node_tree.animation_data_clear()
    colour_by_risk = {
        "normal": (0.20, 0.68, 0.08),
        "warning": (1.0, 0.48, 0.01),
        "serious": (0.95, 0.01, 0.005),
    }
    keyframes = [(frames["normal"], colour_by_risk["normal"], 0.04, 0.60)]
    border_keyframes = [(frames["normal"], (0.72, 1.0, 0.12), 0.18, 1.0)]
    for code in ("attention", "warning", "serious"):
        risk = field_results[code]["risk_code"]
        colour = colour_by_risk[risk]
        keyframes.append((frames[code], colour, 0.45 if risk == "serious" else 0.16, 0.84 if risk == "serious" else 0.70))
        border_keyframes.append((frames[code], colour, 0.70 if risk == "serious" else 0.30, 1.0))
    serious_risk = field_results["serious"]["risk_code"]
    serious_colour = colour_by_risk[serious_risk]
    keyframes.append((frames["focus"], serious_colour, 0.48, 0.86))
    border_keyframes.append((frames["focus"], serious_colour, 0.72, 1.0))
    farmland_v4.animate_material(fill, keyframes)
    farmland_v4.animate_material(border, border_keyframes)


def animate_camera(scene, frames, geometry, field):
    camera = bpy.data.objects.get("Camera_Gangnae_Hydro_V3")
    focus = bpy.data.objects.get("Camera_Farmland_Focus_V4")
    if camera is None or focus is None:
        raise RuntimeError("V4 cameras are missing")
    scene.frame_set(frames["normal"])
    overview_location = tuple(camera.location)
    overview_rotation = tuple(camera.rotation_euler)
    camera.animation_data_clear()
    camera.location = overview_location
    camera.rotation_euler = overview_rotation
    for frame_code in ("normal", "attention"):
        camera.keyframe_insert("location", frame=frames[frame_code])
        camera.keyframe_insert("rotation_euler", frame=frames[frame_code])
    centre = field["derived_metrics"]["centre_local_m"]
    field_z = hydro_v3.terrain_z(hydro_v3.read_hgt(), centre[0], centre[1], geometry, extra=7.0)
    midpoint = (
        (overview_location[0] + focus.location.x) / 2.0,
        (overview_location[1] + focus.location.y) / 2.0,
        focus.location.z + 1250.0,
    )
    farmland_v4.keyframe_camera(camera, frames["warning"], midpoint, (centre[0], centre[1], field_z))
    farmland_v4.keyframe_camera(camera, frames["serious"], tuple(focus.location), (centre[0] + 120.0, centre[1] - 45.0, field_z))
    close_location = (focus.location.x + 120.0, focus.location.y + 135.0, focus.location.z - 90.0)
    farmland_v4.keyframe_camera(camera, frames["focus"], close_location, (centre[0] + 80.0, centre[1] - 30.0, field_z))
    scene.camera = camera
    return camera


def render_at(scene, camera, frame, path):
    scene.camera = camera
    scene.frame_set(frame)
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Render failed: {path}")


def main():
    scene = bpy.context.scene
    scene.name = "Gangnae_Inundation_V5"
    scenario_config = load_json(SCENARIO_PATH)
    field = load_json(FIELD_PATH)
    geometry = load_json(GEOMETRY_PATH)
    snapshot = load_json(SNAPSHOT_PATH)
    frames = scenario_config["frames"]
    scenarios = scenario_config["scenarios"]
    scene.frame_start = frames["normal"]
    scene.frame_end = frames["focus"]
    scene.render.fps = 24
    collection = prepare_collection(scene)
    hgt_values = hydro_v3.read_hgt()
    miho = next(item for item in geometry["centerlines"] if item["name"] == "미호강")
    miho_line = max(miho["parts"], key=len)

    inundation_objects = {}
    for scenario in scenarios:
        material = hydro_v3.material(
            f"Material_V5_Inundation_{scenario['code']}",
            tuple(scenario["colour"]),
            roughness=0.24,
            metallic=0.06,
            alpha=scenario["alpha"],
            emission=0.18,
        )
        obj = create_inundation_mesh(
            scenario,
            geometry,
            miho_line,
            hgt_values,
            collection,
            material,
            scenario_config["grid_cell_m"],
        )
        inundation_objects[scenario["code"]] = obj
    set_exclusive_visibility(inundation_objects, frames)

    field_results = calculate_field_results(
        field,
        geometry,
        scenarios,
        miho_line,
        hgt_values,
        scenario_config["field_sample_grid"],
    )
    reset_field_animation(field_results, frames)
    field_obj = bpy.data.objects.get(f"Field_{FIELD_ID}")
    if field_obj is None:
        raise RuntimeError("Registered field is missing")
    field_obj["risk_is_calculated"] = True
    field_obj["risk_method"] = ACCURACY
    field_obj["scenario_results_json"] = json.dumps(field_results, ensure_ascii=False)
    camera = animate_camera(scene, frames, geometry, field)

    render_at(scene, camera, frames["normal"], RENDER_PATHS["normal"])
    render_at(scene, camera, frames["attention"], RENDER_PATHS["attention"])
    render_at(scene, camera, frames["warning"], RENDER_PATHS["warning"])
    render_at(scene, camera, frames["serious"], RENDER_PATHS["serious"])

    scene.frame_set(frames["serious"])
    scene.camera = camera
    scene["inundation_accuracy"] = ACCURACY
    scene["live_snapshot_risk"] = snapshot["scene_state"]["risk"]["code"]
    scene["scenario_mode"] = scenario_config["mode"]
    bpy.ops.object.select_all(action="DESELECT")
    field_obj.select_set(True)
    bpy.context.view_layer.objects.active = field_obj
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    result = {
        "status": "ok",
        "field_id": FIELD_ID,
        "accuracy": ACCURACY,
        "live_snapshot_context": snapshot["scene_state"],
        "scenario_results": field_results,
        "disclaimer": "MVP heuristic visualization; not an official forecast or hydraulic simulation.",
    }
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "status": "ok",
        "scene": scene.name,
        "collection": collection.name,
        "flood_meshes": {
            code: {
                "cells": obj["grid_cell_count"],
                "display_area_m2": obj["display_area_m2"],
            }
            for code, obj in inundation_objects.items()
        },
        "field_results": field_results,
        "camera_frames": list(frames.values()),
        "renders": {key: {"path": str(path), "bytes": path.stat().st_size} for key, path in RENDER_PATHS.items()},
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "limitations": scenario_config["limitations"],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[inundation-v5] build complete")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
