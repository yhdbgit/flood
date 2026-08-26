#!/usr/bin/env python3
"""Build all registered V23 field overlays and reusable camera profiles in one Scene Pack."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.geometry import tessellate_polygon


ROOT = Path(__file__).resolve().parents[1]
SOURCE_BLEND = ROOT / "blender" / "osong_common_v23.blend"
OUTPUT_BLEND = ROOT / "blender" / "osong_personalization_v23.blend"
PLAN_PATH = ROOT / "data" / "v23" / "field_assets" / "field_asset_plan_v23.json"
MANIFEST_PATH = ROOT / "data" / "v23" / "field_assets" / "field_assets_manifest_v23.json"
FONT_PATH = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")

FIELD_PARENT = "V23_FIELD_OVERLAYS"
CAMERA_PARENT = "V23_CAMERA_PROFILES"
FLOOD_PARENT = "V23_FIELD_FLOOD_OVERLAYS"
COMMON_PARENT = "V23_COMMON_BACKGROUND"
INFRA_PARENT = "V23_RENDER_INFRA"
TERRAIN_NAMES = ["Terrain_Osong_FieldRiver_HQ_1500m_V21", "Terrain_Osong_Regional_12km"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def get_or_create_collection(name: str) -> bpy.types.Collection:
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    return collection


def link_child_only(parent: bpy.types.Collection, child: bpy.types.Collection) -> None:
    for scene in bpy.data.scenes:
        if scene.collection.children.get(child.name) is not None:
            scene.collection.children.unlink(child)
    for collection in bpy.data.collections:
        if collection == parent:
            continue
        if collection.children.get(child.name) is not None:
            collection.children.unlink(child)
    if parent.children.get(child.name) is None:
        parent.children.link(child)


def clear_collection(collection: bpy.types.Collection) -> None:
    for child in list(collection.children):
        clear_collection(child)
        collection.children.unlink(child)
        bpy.data.collections.remove(child)
    for obj in list(collection.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def find_layer_collection(root: bpy.types.LayerCollection, name: str):
    if root.name == name:
        return root
    for child in root.children:
        found = find_layer_collection(child, name)
        if found is not None:
            return found
    return None


def configure_field_view_layer(scene, name: str, field_collection: str, composite: bool) -> None:
    old = scene.view_layers.get(name)
    if old is not None:
        scene.view_layers.remove(old)
    layer = scene.view_layers.new(name=name)
    allowed_top = {FIELD_PARENT, INFRA_PARENT}
    if composite:
        allowed_top.add(COMMON_PARENT)
    for child in scene.collection.children:
        node = find_layer_collection(layer.layer_collection, child.name)
        if node is not None:
            node.exclude = child.name not in allowed_top
    for child in bpy.data.collections[FIELD_PARENT].children:
        node = find_layer_collection(layer.layer_collection, child.name)
        if node is not None:
            node.exclude = child.name != field_collection
    layer.use = False
    layer.use_pass_z = True


def configure_field_flood_view_layer(scene, name: str, flood_collection: str) -> None:
    old = scene.view_layers.get(name)
    if old is not None:
        scene.view_layers.remove(old)
    layer = scene.view_layers.new(name=name)
    for child in scene.collection.children:
        node = find_layer_collection(layer.layer_collection, child.name)
        if node is not None:
            node.exclude = child.name not in {FLOOD_PARENT, INFRA_PARENT}
    for child in bpy.data.collections[FLOOD_PARENT].children:
        node = find_layer_collection(layer.layer_collection, child.name)
        if node is not None:
            node.exclude = child.name != flood_collection
    layer.use = False
    layer.use_pass_z = True


def terrain_height(x: float, y: float) -> tuple[float, str]:
    origin_world = Vector((x, y, 10000.0))
    direction_world = Vector((0.0, 0.0, -1.0))
    for name in TERRAIN_NAMES:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            continue
        inverse = obj.matrix_world.inverted()
        origin_local = inverse @ origin_world
        direction_local = (inverse.to_3x3() @ direction_world).normalized()
        hit, location, _normal, _face = obj.ray_cast(origin_local, direction_local)
        if hit:
            return float((obj.matrix_world @ location).z), name
    raise RuntimeError(f"No terrain surface below local coordinate ({x:.3f}, {y:.3f})")


def material(name: str, colour: tuple[float, float, float], alpha: float, emission: float):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    if shader is None:
        shader = next(node for node in mat.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    rgba = (*colour, alpha)
    shader.inputs["Base Color"].default_value = rgba
    shader.inputs["Roughness"].default_value = 0.48
    if shader.inputs.get("Alpha"):
        shader.inputs["Alpha"].default_value = alpha
    emission_input = shader.inputs.get("Emission Color") or shader.inputs.get("Emission")
    if emission_input:
        emission_input.default_value = (*colour, 1.0)
    if shader.inputs.get("Emission Strength"):
        shader.inputs["Emission Strength"].default_value = emission
    mat.diffuse_color = rgba
    try:
        mat.surface_render_method = "DITHERED"
    except (AttributeError, TypeError):
        try:
            mat.blend_method = "BLEND"
        except (AttributeError, TypeError):
            pass
    return mat


def apply_terrain_drape(obj, terrain, diagonal_m):
    subdivision = obj.modifiers.new(name="V23_Field_Simple_Subdivision", type="SUBSURF")
    subdivision.subdivision_type = "SIMPLE"
    subdivision.levels = 4 if diagonal_m > 500.0 else 3 if diagonal_m > 100.0 else 2
    subdivision.render_levels = subdivision.levels
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=subdivision.name)
    shrinkwrap = obj.modifiers.new(name="V23_Field_Terrain_Drape", type="SHRINKWRAP")
    shrinkwrap.target = terrain
    shrinkwrap.wrap_method = "PROJECT"
    shrinkwrap.wrap_mode = "ABOVE_SURFACE"
    shrinkwrap.use_project_z = True
    shrinkwrap.use_negative_direction = True
    shrinkwrap.use_positive_direction = True
    shrinkwrap.offset = 1.3
    bpy.ops.object.modifier_apply(modifier=shrinkwrap.name)
    obj.select_set(False)


def create_fill(item, collection, fill_material):
    points_2d = [Vector((float(point[0]), float(point[1]), 0.0)) for point in item["polygon_local_xy_m"]]
    triangles = tessellate_polygon([points_2d])
    vertices = []
    faces = []
    terrain_sources = set()
    for triangle in triangles:
        face = []
        for vertex_index in triangle:
            point = points_2d[vertex_index]
            z, source = terrain_height(float(point.x), float(point.y))
            terrain_sources.add(source)
            face.append(len(vertices))
            vertices.append((float(point.x), float(point.y), z + 1.3))
        faces.append(tuple(face))
    if not faces:
        raise RuntimeError(f"Cannot triangulate field {item['field_id']}")
    mesh = bpy.data.meshes.new(f"{item['overlay']['fill_object']}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(verbose=False)
    mesh.update()
    obj = bpy.data.objects.new(item["overlay"]["fill_object"], mesh)
    collection.objects.link(obj)
    obj.data.materials.append(fill_material)
    cx, cy = item["centre_local_xy_m"]
    _ground_z, terrain_name = terrain_height(float(cx), float(cy))
    apply_terrain_drape(obj, bpy.data.objects[terrain_name], float(item["diagonal_m"]))
    terrain_sources.add(terrain_name)
    return obj, sorted(terrain_sources)


def create_boundary(item, collection, boundary_material):
    curve = bpy.data.curves.new(f"{item['overlay']['boundary_object']}_Curve", "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 1
    curve.bevel_depth = float(item["overlay"]["border_width_m"])
    curve.bevel_resolution = 2
    spline = curve.splines.new("POLY")
    points = item["polygon_local_xy_m"]
    spline.points.add(len(points))
    terrain_sources = set()
    for index, (x, y) in enumerate(points + [points[0]]):
        z, source = terrain_height(float(x), float(y))
        terrain_sources.add(source)
        spline.points[index].co = (float(x), float(y), z + 2.0, 1.0)
    obj = bpy.data.objects.new(item["overlay"]["boundary_object"], curve)
    collection.objects.link(obj)
    obj.data.materials.append(boundary_material)
    return obj, sorted(terrain_sources)


def set_hidden_key(obj, frame, hidden):
    obj.hide_render = hidden
    obj.hide_viewport = hidden
    obj.keyframe_insert(data_path="hide_render", frame=frame)
    obj.keyframe_insert(data_path="hide_viewport", frame=frame)


def animate_flood_stages(objects):
    cycle_one = [48 + index * 19 for index in range(10)]
    cycle_two = [384 + index * 19 for index in range(10)]
    for index, obj in enumerate(objects):
        set_hidden_key(obj, 1, True)
        set_hidden_key(obj, cycle_one[index] - 1, True)
        set_hidden_key(obj, cycle_one[index], False)
        set_hidden_key(obj, cycle_one[index + 1] if index < 9 else 264, True)
        set_hidden_key(obj, cycle_two[index] - 1, True)
        set_hidden_key(obj, cycle_two[index], False)
        if index < 9:
            set_hidden_key(obj, cycle_two[index + 1], True)
        else:
            set_hidden_key(obj, 719, False)


def create_field_flood_stages(item, collection, flood_material):
    objects = []
    for stage in item["flood_overlay"]["stages"]:
        vertices = []
        faces = []
        for polygon in stage["polygons_local_xy_m"]:
            points = [Vector((float(x), float(y), 0.0)) for x, y in polygon[:-1]]
            if len(points) < 3:
                continue
            for triangle in tessellate_polygon([points]):
                face = []
                for index in triangle:
                    point = points[index]
                    z, _terrain = terrain_height(float(point.x), float(point.y))
                    face.append(len(vertices))
                    vertices.append((float(point.x), float(point.y), z + 1.55))
                faces.append(tuple(face))
        if not faces:
            continue
        name = f"FieldFlood_{item['field_id']}_Step_{stage['step']:02d}_V23"
        mesh = bpy.data.meshes.new(f"{name}_Mesh")
        mesh.from_pydata(vertices, [], faces)
        mesh.validate(verbose=False)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        obj.data.materials.append(flood_material)
        obj["v23_field_id"] = item["field_id"]
        obj["official_extent_constrained"] = True
        obj["hydraulic_time_series"] = False
        obj["progression_step"] = int(stage["step"])
        objects.append(obj)
    if len(objects) != 10:
        raise RuntimeError(f"Expected 10 flood stages for {item['field_id']}, got {len(objects)}")
    animate_flood_stages(objects)
    return objects


def clear_animation(data_block) -> None:
    if data_block.animation_data:
        data_block.animation_data_clear()


def duplicate_camera_profile(item, collection):
    base = bpy.data.objects.get("Camera_Osong_Shelter_V19")
    if base is None or base.type != "CAMERA":
        raise RuntimeError("V22 source camera is missing")
    base_constraint = next((constraint for constraint in base.constraints if constraint.type == "TRACK_TO"), None)
    if base_constraint is None or base_constraint.target is None:
        raise RuntimeError("V22 source camera target is missing")
    camera = base.copy()
    camera.data = base.data.copy()
    camera.name = item["camera_profile"]["camera_object"]
    camera.data.name = f"{camera.name}_Data"
    collection.objects.link(camera)
    clear_animation(camera)
    clear_animation(camera.data)

    target = base_constraint.target.copy()
    target.name = item["camera_profile"]["target_object"]
    collection.objects.link(target)
    clear_animation(target)
    constraint = next(value for value in camera.constraints if value.type == "TRACK_TO")
    constraint.target = target

    cx, cy = item["centre_local_xy_m"]
    ground_z, terrain_source = terrain_height(float(cx), float(cy))
    profile = item["camera_profile"]
    distance = float(profile["focus_distance_m"])
    height = float(profile["focus_height_m"])
    approach = float(profile["approach_distance_m"])
    lens = float(profile["lens_mm"])
    overview = max(approach * 1.32, distance * 2.25)
    overview_height = max(height * 2.15, overview * 0.88)
    overview_location = (cx - overview * 0.55, cy - overview * 0.72, ground_z + overview_height)
    shots = [
        (1, overview_location, lens - 10.0, "selected_field_overview_start"),
        (120, overview_location, lens - 8.0, "selected_field_first_flood_overview"),
        (240, (cx - overview * 0.48, cy - overview * 0.66, ground_z + overview_height * 0.92), lens - 6.0, "selected_field_first_flood_end"),
        (241, (cx - approach * 0.58, cy - approach * 0.72, ground_z + max(height * 1.45, approach * 0.82)), lens - 5.0, "selected_field_reset_approach"),
        (320, (cx - distance * 0.94, cy - distance * 1.08, ground_z + height * 1.35), lens, "field_focus_arrival"),
        (400, (cx - distance * 0.94, cy - distance * 1.08, ground_z + height * 1.35), lens, "field_focus_hold"),
        (600, (cx - distance * 0.78, cy - distance * 0.90, ground_z + height * 1.08), lens + 2.0, "field_close_hold"),
        (640, (cx - distance * 0.78, cy - distance * 0.90, ground_z + height * 1.08), lens + 2.0, "field_segment_end"),
        (719, overview_location, lens - 8.0, "selected_field_zoom_out_end"),
    ]
    target_z = ground_z + 8.0
    for frame, location, shot_lens, _shot in shots:
        camera.location = location
        camera.data.lens = shot_lens
        target.location = (cx, cy, target_z)
        camera.keyframe_insert(data_path="location", frame=frame)
        camera.data.keyframe_insert(data_path="lens", frame=frame)
        target.keyframe_insert(data_path="location", frame=frame)
    camera.data.clip_start = float(profile["clip_start_m"])
    camera.data.clip_end = float(profile["clip_end_m"])
    camera["v23_camera_profile_id"] = profile["camera_profile_id"]
    camera["v23_field_id"] = item["field_id"]
    target["v23_field_id"] = item["field_id"]
    return camera, target, ground_z, terrain_source, [
        {"frame": frame, "shot": shot, "location": [round(float(value), 3) for value in location], "lens_mm": shot_lens}
        for frame, location, shot_lens, shot in shots
    ]


def create_label(item, collection, label_material, camera, ground_z):
    curve = bpy.data.curves.new(f"{item['overlay']['label_object']}_Font", "FONT")
    curve.body = f"등록 농경지 {item['field_id'][-3:]}"
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.size = max(10.0, min(28.0, float(item["diagonal_m"]) * 0.075))
    curve.extrude = 0.35
    if FONT_PATH.is_file():
        curve.font = bpy.data.fonts.load(str(FONT_PATH), check_existing=True)
    label = bpy.data.objects.new(item["overlay"]["label_object"], curve)
    collection.objects.link(label)
    cx, cy = item["centre_local_xy_m"]
    label.location = (cx, cy, ground_z + max(14.0, curve.size * 1.4))
    label.data.materials.append(label_material)
    track = label.constraints.new(type="TRACK_TO")
    track.target = camera
    track.track_axis = "TRACK_Z"
    track.up_axis = "UP_Y"
    return label


def tag_objects(item, objects) -> None:
    for obj in objects:
        obj["v23_field_id"] = item["field_id"]
        obj["v23_owner_user_id"] = item["owner_user_id"]
        obj["v23_overlay_asset_id"] = item["overlay"]["asset_id"]
        obj["v23_geometry_accuracy"] = item["geometry_accuracy"]
        obj["v23_area_m2"] = float(item["area_m2"])
        obj["v23_risk_is_calculated"] = False
        if hasattr(obj, "visible_shadow"):
            obj.visible_shadow = False


def main() -> None:
    if Path(bpy.data.filepath).resolve() != SOURCE_BLEND.resolve():
        raise RuntimeError(f"Run this script with {SOURCE_BLEND}")
    source_hash_before = sha256(SOURCE_BLEND)
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    scene = bpy.context.scene

    field_parent = get_or_create_collection(FIELD_PARENT)
    if scene.collection.children.get(field_parent.name) is None:
        scene.collection.children.link(field_parent)
    clear_collection(field_parent)
    flood_parent = get_or_create_collection(FLOOD_PARENT)
    if scene.collection.children.get(flood_parent.name) is None:
        scene.collection.children.link(flood_parent)
    clear_collection(flood_parent)
    camera_parent = get_or_create_collection(CAMERA_PARENT)
    clear_collection(camera_parent)
    link_child_only(bpy.data.collections[INFRA_PARENT], camera_parent)

    fill_material = material("V23_Mat_FieldFill", (0.12, 0.95, 0.18), 0.34, 0.12)
    boundary_material = material("V23_Mat_FieldBoundary", (1.0, 0.82, 0.03), 1.0, 0.55)
    label_material = material("V23_Mat_FieldLabel", (1.0, 0.96, 0.72), 1.0, 0.4)
    flood_material = material("V23_Mat_FieldFlood", (0.02, 0.36, 0.78), 0.76, 0.12)
    assets = []
    for item in plan["fields"]:
        collection = bpy.data.collections.new(item["overlay"]["collection"])
        field_parent.children.link(collection)
        flood_collection = bpy.data.collections.new(item["flood_overlay"]["collection"])
        flood_parent.children.link(flood_collection)
        fill, fill_sources = create_fill(item, collection, fill_material)
        boundary, boundary_sources = create_boundary(item, collection, boundary_material)
        camera, target, ground_z, camera_terrain, camera_shots = duplicate_camera_profile(item, camera_parent)
        label = create_label(item, collection, label_material, camera, ground_z)
        flood_objects = create_field_flood_stages(item, flood_collection, flood_material)
        tag_objects(item, (fill, boundary, label))
        configure_field_view_layer(scene, item["overlay"]["rgba_view_layer"], collection.name, composite=False)
        configure_field_view_layer(scene, item["overlay"]["composite_view_layer"], collection.name, composite=True)
        configure_field_flood_view_layer(scene, item["flood_overlay"]["rgba_view_layer"], flood_collection.name)
        assets.append({
            "field_id": item["field_id"],
            "owner_user_id": item["owner_user_id"],
            "overlay_asset_id": item["overlay"]["asset_id"],
            "collection": collection.name,
            "objects": [fill.name, boundary.name, label.name],
            "polygon_vertex_count": len(item["polygon_local_xy_m"]),
            "terrain_sources": sorted(set(fill_sources + boundary_sources + [camera_terrain])),
            "ground_z_scene_m": round(ground_z, 3),
            "rgba_view_layer": item["overlay"]["rgba_view_layer"],
            "composite_view_layer": item["overlay"]["composite_view_layer"],
            "camera_profile_id": item["camera_profile"]["camera_profile_id"],
            "camera_object": camera.name,
            "camera_target_object": target.name,
            "camera_keyframes": camera_shots,
            "flood_collection": flood_collection.name,
            "flood_objects": [obj.name for obj in flood_objects],
            "flood_rgba_view_layer": item["flood_overlay"]["rgba_view_layer"],
            "official_field_intersection_percent": item["flood_overlay"]["official_field_intersection_percent"],
        })

    for layer in scene.view_layers:
        if not layer.name.startswith("V23_FIELD_") and not layer.name.startswith("V23_FLOOD_"):
            node = find_layer_collection(layer.layer_collection, FIELD_PARENT)
            if node is not None:
                node.exclude = True

    scene.name = "Osong_Personalization_V23"
    scene["v23_field_asset_count"] = len(assets)
    scene["v23_field_assets_prepared_at_registration"] = True
    scene["v23_trigger_time_full_render_allowed"] = False
    scene["v23_active_field_selection_required"] = True
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT_BLEND), check_existing=False)
    if sha256(SOURCE_BLEND) != source_hash_before:
        raise RuntimeError("V23 common source blend changed during field asset generation")
    manifest = {
        "schema_version": "1.0",
        "status": "built_preview_pending",
        "scene_pack_id": plan["scene_pack_id"],
        "source_blend": str(SOURCE_BLEND),
        "source_blend_sha256": source_hash_before,
        "source_blend_unchanged": True,
        "blend_path": str(OUTPUT_BLEND),
        "blend_bytes": OUTPUT_BLEND.stat().st_size,
        "blend_sha256": sha256(OUTPUT_BLEND),
        "field_asset_count": len(assets),
        "field_assets": assets,
        "selection_contract": {
            "one_scene_pack_contains_multiple_fields": True,
            "render_exactly_one_requested_field_overlay": True,
            "camera_profile_selected_by_field_id": True,
            "trigger_time_full_blender_render": False,
        },
        "previews": {"status": "pending"},
        "limitations": [
            "Demo geometries are OSM farmland polygons, not cadastral ownership parcels.",
            "Field overlays communicate registration and focus only; they do not calculate flood damage.",
            "Fields outside the 1.5 km HQ core use the lower-detail regional terrain until another HQ tile is prepared.",
        ],
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "blend_path": str(OUTPUT_BLEND),
        "blend_sha256": manifest["blend_sha256"],
        "field_asset_count": len(assets),
        "camera_profiles": [item["camera_profile_id"] for item in assets],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
