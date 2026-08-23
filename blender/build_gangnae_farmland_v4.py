"""Add an MVP registered farmland parcel and focus animation to hydro-v3."""

import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
sys.path.insert(0, str(ROOT / "blender"))
import build_gangnae_hydro_v3 as hydro_v3


FIELD_CONFIG_PATH = ROOT / "config" / "mvp_farmland.json"
GEOMETRY_PATH = ROOT / "data" / "processed" / "gangnae_hydro_geometry.json"
HGT_PATH = ROOT / "data" / "terrain" / "N36E127.hgt"
BLEND_PATH = ROOT / "blender" / "gangnae_farmland_v4.blend"
REPORT_PATH = ROOT / "output" / "farmland_v4_validation_report.json"
OVERVIEW_PATH = ROOT / "output" / "gangnae_farmland_v4_overview.png"
FOCUS_NORMAL_PATH = ROOT / "output" / "gangnae_farmland_v4_focus_normal.png"
FOCUS_RISK_PATH = ROOT / "output" / "gangnae_farmland_v4_focus_risk.png"

COLLECTION_NAME = "DT_FARMLAND_V4"
FOCUS_CAMERA_NAME = "Camera_Farmland_Focus_V4"
NORMAL_FRAME = 1
ATTENTION_FRAME = 48
RISK_FRAME = 96


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


def to_local(coordinate, geometry):
    longitude, latitude = coordinate
    origin_lon, origin_lat = geometry["origin_wgs84"]
    scale = geometry["metres_per_degree"]
    return (
        (longitude - origin_lon) * scale["longitude"],
        (latitude - origin_lat) * scale["latitude"],
    )


def create_field_mesh(field, geometry, hgt_values, collection, material):
    boundary = [to_local(point, geometry) for point in field["geometry"]["coordinates"][0]]
    if boundary[0] == boundary[-1]:
        boundary.pop()
    centre_x = sum(point[0] for point in boundary) / len(boundary)
    centre_y = sum(point[1] for point in boundary) / len(boundary)
    vertices = [
        (
            centre_x,
            centre_y,
            hydro_v3.terrain_z(hgt_values, centre_x, centre_y, geometry, 4.2),
        )
    ]
    for x, y in boundary:
        vertices.append((x, y, hydro_v3.terrain_z(hgt_values, x, y, geometry, 4.2)))
    faces = []
    for index in range(len(boundary)):
        faces.append((0, index + 1, ((index + 1) % len(boundary)) + 1))
    mesh = bpy.data.meshes.new(f"Field_{field['field_id']}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(f"Field_{field['field_id']}", mesh)
    collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj, boundary, (centre_x, centre_y)


def animate_material(material, keyframes):
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader is None:
        shader = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    base_colour = shader.inputs["Base Color"]
    emission_colour = shader.inputs.get("Emission Color") or shader.inputs.get("Emission")
    emission_strength = shader.inputs.get("Emission Strength")
    alpha = shader.inputs.get("Alpha")
    for frame, colour, strength, opacity in keyframes:
        rgba = (*colour, opacity)
        base_colour.default_value = rgba
        base_colour.keyframe_insert("default_value", frame=frame)
        if emission_colour is not None:
            emission_colour.default_value = rgba
            emission_colour.keyframe_insert("default_value", frame=frame)
        if emission_strength is not None:
            emission_strength.default_value = strength
            emission_strength.keyframe_insert("default_value", frame=frame)
        if alpha is not None:
            alpha.default_value = opacity
            alpha.keyframe_insert("default_value", frame=frame)
        material.diffuse_color = rgba
        material.keyframe_insert("diffuse_color", frame=frame)


def create_focus_camera(scene, collection, field_centre, field_z):
    data = bpy.data.cameras.new(f"{FOCUS_CAMERA_NAME}_Data")
    camera = bpy.data.objects.new(FOCUS_CAMERA_NAME, data)
    collection.objects.link(camera)
    camera.location = (field_centre[0] - 540.0, field_centre[1] - 680.0, field_z + 610.0)
    hydro_v3.point_at(camera, (field_centre[0] + 120.0, field_centre[1] - 45.0, field_z))
    data.lens = 58.0
    data.sensor_width = 36.0
    data.clip_start = 1.0
    data.clip_end = 100_000.0
    return camera


def keyframe_camera(camera, frame, location, target):
    camera.location = location
    hydro_v3.point_at(camera, target)
    camera.keyframe_insert("location", frame=frame)
    camera.keyframe_insert("rotation_euler", frame=frame)


def set_linear_camera_motion(camera):
    # Blender 5.2 layered Actions no longer expose Action.fcurves directly.
    # The default Bezier interpolation is sufficient for this MVP camera move.
    return


def render_at(scene, camera, frame, path):
    scene.camera = camera
    scene.frame_set(frame)
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Render failed: {path}")


def main():
    scene = bpy.context.scene
    scene.name = "Gangnae_Farmland_V4"
    scene.frame_start = NORMAL_FRAME
    scene.frame_end = RISK_FRAME
    scene.render.fps = 24
    collection = prepare_collection(scene)
    field = load_json(FIELD_CONFIG_PATH)
    geometry = load_json(GEOMETRY_PATH)
    hgt_values = hydro_v3.read_hgt()

    fill_material = hydro_v3.material(
        "Material_V4_FieldFill", (0.28, 0.72, 0.12, 1.0), roughness=0.62, alpha=0.62, emission=0.05
    )
    border_material = hydro_v3.material(
        "Material_V4_FieldBorder", (0.82, 1.0, 0.18, 1.0), roughness=0.48, emission=0.22
    )
    text_material = hydro_v3.material(
        "Material_V4_FieldText", (1.0, 1.0, 0.88, 1.0), roughness=0.55, emission=0.28
    )

    animate_material(
        fill_material,
        [
            (NORMAL_FRAME, (0.20, 0.68, 0.08), 0.04, 0.58),
            (ATTENTION_FRAME, (1.0, 0.55, 0.02), 0.12, 0.68),
            (RISK_FRAME, (0.95, 0.015, 0.01), 0.42, 0.82),
        ],
    )
    animate_material(
        border_material,
        [
            (NORMAL_FRAME, (0.72, 1.0, 0.12), 0.15, 1.0),
            (ATTENTION_FRAME, (1.0, 0.65, 0.01), 0.30, 1.0),
            (RISK_FRAME, (1.0, 0.015, 0.005), 0.65, 1.0),
        ],
    )

    field_obj, boundary, centre = create_field_mesh(
        field, geometry, hgt_values, collection, fill_material
    )
    closed_boundary = boundary + [boundary[0]]
    border_obj = hydro_v3.create_flat_strips(
        f"FieldBoundary_{field['field_id']}",
        [closed_boundary],
        collection,
        border_material,
        hgt_values,
        geometry,
        width=5.5,
        z_offset=5.0,
        closed=True,
    )
    field_z = hydro_v3.terrain_z(hgt_values, centre[0], centre[1], geometry, 7.0)
    label = hydro_v3.create_map_text(
        f"FieldLabel_{field['field_id']}",
        "등록 농경지",
        (centre[0], centre[1], field_z),
        24.0,
        collection,
        text_material,
        None,
    )

    for obj in (field_obj, border_obj, label):
        obj["field_id"] = field["field_id"]
        obj["display_name"] = field["display_name"]
        obj["owner_display_name"] = field["owner_display_name"]
        obj["registration_status"] = field["registration_status"]
        obj["geometry_accuracy"] = field["geometry_accuracy"]
        obj["area_m2"] = field["derived_metrics"]["area_m2"]
        obj["distance_to_miho_centerline_m"] = field["derived_metrics"]["distance_to_miho_centerline_m"]
        obj["risk_is_calculated"] = False

    focus_camera = create_focus_camera(scene, collection, centre, field_z)
    main_camera = bpy.data.objects.get("Camera_Gangnae_Hydro_V3")
    if main_camera is None:
        raise RuntimeError("Camera_Gangnae_Hydro_V3 is missing")
    overview_location = tuple(main_camera.location)
    overview_rotation = tuple(main_camera.rotation_euler)
    width, depth, _ = geometry["terrain"]["dimensions_m"]
    main_camera.animation_data_clear()
    main_camera.location = overview_location
    main_camera.rotation_euler = overview_rotation
    main_camera.keyframe_insert("location", frame=NORMAL_FRAME)
    main_camera.keyframe_insert("rotation_euler", frame=NORMAL_FRAME)
    midpoint = (
        (overview_location[0] + focus_camera.location.x) / 2.0,
        (overview_location[1] + focus_camera.location.y) / 2.0,
        max(focus_camera.location.z + 520.0, width * 0.72),
    )
    keyframe_camera(main_camera, ATTENTION_FRAME, midpoint, (centre[0] + 90.0, centre[1] - 30.0, field_z))
    keyframe_camera(main_camera, RISK_FRAME, tuple(focus_camera.location), (centre[0] + 120.0, centre[1] - 45.0, field_z))
    set_linear_camera_motion(main_camera)

    render_at(scene, main_camera, NORMAL_FRAME, OVERVIEW_PATH)
    render_at(scene, focus_camera, NORMAL_FRAME, FOCUS_NORMAL_PATH)
    render_at(scene, focus_camera, RISK_FRAME, FOCUS_RISK_PATH)

    scene.camera = main_camera
    scene.frame_set(NORMAL_FRAME)
    bpy.ops.object.select_all(action="DESELECT")
    field_obj.select_set(True)
    bpy.context.view_layer.objects.active = field_obj
    scene["mvp_field_id"] = field["field_id"]
    scene["mvp_field_geometry_accuracy"] = field["geometry_accuracy"]
    scene["mvp_risk_is_calculated"] = False
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    report = {
        "status": "ok",
        "scene": scene.name,
        "collection": collection.name,
        "field_id": field["field_id"],
        "field_area_m2": field["derived_metrics"]["area_m2"],
        "geometry_accuracy": field["geometry_accuracy"],
        "distance_to_miho_centerline_m": field["derived_metrics"]["distance_to_miho_centerline_m"],
        "risk_is_calculated": False,
        "timeline": {
            "normal": NORMAL_FRAME,
            "attention": ATTENTION_FRAME,
            "risk": RISK_FRAME,
            "fps": scene.render.fps,
        },
        "camera_keyframes": [NORMAL_FRAME, ATTENTION_FRAME, RISK_FRAME],
        "renders": {
            "overview": {"path": str(OVERVIEW_PATH), "bytes": OVERVIEW_PATH.stat().st_size},
            "focus_normal": {"path": str(FOCUS_NORMAL_PATH), "bytes": FOCUS_NORMAL_PATH.stat().st_size},
            "focus_risk": {"path": str(FOCUS_RISK_PATH), "bytes": FOCUS_RISK_PATH.stat().st_size},
        },
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "limitations": [
            "The MVP field is derived inside an OSM farmland area and is not a cadastral parcel.",
            "The red risk state is a presentation keyframe and is not yet driven by an inundation calculation.",
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[farmland-v4] build complete")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
