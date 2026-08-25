"""Build V19 field-to-shelter Blender scene and four validation stills.

No flood or inundation object is created in this stage.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
BASE_SCRIPT = ROOT / "blender" / "build_gangnae_hq_v10.py"
OUTER_PATH = ROOT / "data" / "processed" / "osong_shelter_v19_outer.json"
FIELD_PATH = ROOT / "data" / "processed" / "osong_hq_v11_context.json"
SHELTER_PATH = ROOT / "data" / "processed" / "osong_shelter_v19_hq.json"
MANIFEST_PATH = ROOT / "data" / "processed" / "osong_shelter_v19_manifest.json"
BLEND_PATH = ROOT / "blender" / "osong_shelter_v19.blend"
OUTPUT_DIR = ROOT / "output" / "shelter_v19"
PREVIEW_DIR = OUTPUT_DIR / "previews"
REPORT_PATH = OUTPUT_DIR / "scene_report.json"
FONT_PATH = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")
FPS = 24
FRAME_END = 528


def load_json(path):
    if not Path(path).is_file():
        raise FileNotFoundError(path)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def feathered_aerial(image_path, name):
    """Fade a 1 km HQ aerial at its edges into the 12 km background."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    texture = nodes.new("ShaderNodeTexImage")
    uv = nodes.new("ShaderNodeTexCoord")
    split = nodes.new("ShaderNodeSeparateXYZ")
    inv_u = nodes.new("ShaderNodeMath")
    inv_v = nodes.new("ShaderNodeMath")
    min_u = nodes.new("ShaderNodeMath")
    min_v = nodes.new("ShaderNodeMath")
    edge = nodes.new("ShaderNodeMath")
    gain = nodes.new("ShaderNodeMath")
    texture.image = bpy.data.images.load(str(image_path), check_existing=True)
    for node in (inv_u, inv_v):
        node.operation = "SUBTRACT"
        node.inputs[0].default_value = 1.0
    min_u.operation = min_v.operation = edge.operation = "MINIMUM"
    gain.operation = "MULTIPLY"
    gain.inputs[1].default_value = 8.0
    gain.use_clamp = True
    shader.inputs["Roughness"].default_value = 0.9
    links.new(uv.outputs["UV"], split.inputs["Vector"])
    links.new(split.outputs["X"], inv_u.inputs[1])
    links.new(split.outputs["Y"], inv_v.inputs[1])
    links.new(split.outputs["X"], min_u.inputs[0])
    links.new(inv_u.outputs[0], min_u.inputs[1])
    links.new(split.outputs["Y"], min_v.inputs[0])
    links.new(inv_v.outputs[0], min_v.inputs[1])
    links.new(min_u.outputs[0], edge.inputs[0])
    links.new(min_v.outputs[0], edge.inputs[1])
    links.new(edge.outputs[0], gain.inputs[0])
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    links.new(gain.outputs[0], shader.inputs["Alpha"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    try:
        material.surface_render_method = "DITHERED"
    except (AttributeError, TypeError):
        try:
            material.blend_method = "BLEND"
        except (AttributeError, TypeError):
            pass
    return material


def replace_material(obj, material):
    obj.data.materials.clear()
    obj.data.materials.append(material)


def add_collection(scene, name):
    collection = bpy.data.collections.new(name)
    scene.collection.children.link(collection)
    return collection


def move_created(before, dx=0.0, dy=0.0, dz=0.0):
    created = [obj for obj in bpy.data.objects if obj not in before]
    for obj in created:
        obj.location.x += dx
        obj.location.y += dy
        obj.location.z += dz
    return created


def centroid(points):
    return (
        sum(float(p[0]) for p in points) / len(points),
        sum(float(p[1]) for p in points) / len(points),
    )


def create_camera(base, collection, field_target, shelter_target, midpoint):
    camera = base.create_camera(
        "Camera_Osong_Shelter_V19", (850.0, -2450.0, 3550.0), midpoint, 52.0, collection
    )
    camera.data.clip_start = 1.0
    camera.data.clip_end = 50_000.0
    target = bpy.data.objects.new("CameraTarget_Osong_Shelter_V19", None)
    collection.objects.link(target)
    constraint = camera.constraints.new(type="TRACK_TO")
    constraint.target = target
    constraint.track_axis = "TRACK_NEGATIVE_Z"
    constraint.up_axis = "UP_Y"
    keys = [
        (1, (850, -2450, 3550), midpoint, 52, "regional_overview"),
        (96, (620, -920, 620), field_target, 58, "field_zoom_in"),
        (216, (470, -700, 500), field_target, 62, "field_hold_future_flood_slot"),
        (336, (850, -2200, 3300), midpoint, 50, "zoom_out_from_field"),
        (384, (1150, -350, 2400), shelter_target, 54, "shelter_reveal"),
        (480, (2150, 1920, 680), shelter_target, 62, "shelter_zoom_in"),
        (528, (2050, 2050, 590), shelter_target, 66, "shelter_hold"),
    ]
    for frame, location, aim, lens, _shot in keys:
        camera.location = location
        camera.data.lens = lens
        target.location = aim
        camera.keyframe_insert(data_path="location", frame=frame)
        camera.data.keyframe_insert(data_path="lens", frame=frame)
        target.keyframe_insert(data_path="location", frame=frame)
    return camera, keys


def relink_active(obj, collection):
    for old in list(obj.users_collection):
        old.objects.unlink(obj)
    collection.objects.link(obj)


def create_marker(base, collection, location, camera):
    red = base.new_material("V19_Mat_ShelterMarker", (1.0, 0.12, 0.03), 0.25)
    yellow = base.new_material("V19_Mat_ShelterLabel", (1.0, 0.82, 0.04), 0.3)
    objects = []
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=16, depth=55, location=(location[0], location[1], location[2] + 28))
    pillar = bpy.context.object
    pillar.name = "ShelterMarker_Pillar"
    relink_active(pillar, collection)
    pillar.data.materials.append(red)
    objects.append(pillar)
    bpy.ops.mesh.primitive_cone_add(vertices=48, radius1=34, radius2=0, depth=44, location=(location[0], location[1], location[2] + 77))
    arrow = bpy.context.object
    arrow.name = "ShelterMarker_Arrow"
    relink_active(arrow, collection)
    arrow.data.materials.append(red)
    objects.append(arrow)
    bpy.ops.mesh.primitive_torus_add(major_radius=52, minor_radius=4, location=(location[0], location[1], location[2] + 3))
    ring = bpy.context.object
    ring.name = "ShelterMarker_Ring"
    relink_active(ring, collection)
    ring.data.materials.append(yellow)
    objects.append(ring)
    curve = bpy.data.curves.new("ShelterLabel_Font", "FONT")
    curve.body = "오송읍복지회관"
    curve.align_x = curve.align_y = "CENTER"
    curve.size = 28
    curve.extrude = 0.7
    if FONT_PATH.is_file():
        curve.font = bpy.data.fonts.load(str(FONT_PATH), check_existing=True)
    label = bpy.data.objects.new("ShelterLabel_OsongWelfareCenter", curve)
    collection.objects.link(label)
    label.location = (location[0], location[1], location[2] + 130)
    label.data.materials.append(yellow)
    track = label.constraints.new(type="TRACK_TO")
    track.target = camera
    track.track_axis = "TRACK_Z"
    track.up_axis = "UP_Y"
    objects.append(label)
    for obj in objects:
        obj["shelter_name"] = "오송읍복지회관"
        obj["source_wgs84"] = [127.3241937, 36.60890936]
        obj.scale = (0.001,) * 3
        obj.keyframe_insert(data_path="scale", frame=320)
        obj.scale = (2.8,) * 3
        obj.keyframe_insert(data_path="scale", frame=342)
        obj.scale = (2.2,) * 3
        obj.keyframe_insert(data_path="scale", frame=384)
        obj.scale = (1.0,) * 3
        obj.keyframe_insert(data_path="scale", frame=480)
        obj.keyframe_insert(data_path="scale", frame=528)
    return objects


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    outer = load_json(OUTER_PATH)
    field = load_json(FIELD_PATH)
    shelter = load_json(SHELTER_PATH)
    manifest = load_json(MANIFEST_PATH)
    base = load_module("build_osong_shelter_v19_base", BASE_SCRIPT)
    base.SCENE_NAME = "Osong_Shelter_V19"
    base.COLLECTIONS = {
        "terrain": "V19_TERRAIN",
        "water": "V19_WATER_UNUSED",
        "roads": "V19_FIELD_ROADS",
        "buildings": "V19_FIELD_BUILDINGS",
        "field": "V19_REGISTERED_FIELD",
        "reference": "V19_REFERENCE_UNUSED",
        "lighting": "V19_LIGHTING_CAMERA",
    }
    scene, collections = base.reset_scene()
    shelter_collection = add_collection(scene, "V19_SHELTER_HQ")
    marker_collection = add_collection(scene, "V19_SHELTER_MARKER")

    field_origin = Vector(manifest["field_origin_utm52n"])
    outer_origin = Vector(manifest["outer_origin_utm52n"])
    outer_offset = outer_origin - field_origin
    shelter_offset = Vector(shelter["shelter"]["local_from_field_origin_m"])
    base.configure_georeference(scene, field)

    outer_terrain, outer_sampler = base.create_terrain(outer, collections["terrain"])
    outer_terrain.name = "Terrain_Osong_Regional_12km"
    outer_terrain.location.x = outer_offset.x
    outer_terrain.location.y = outer_offset.y
    outer_min = float(outer["terrain"]["elevation_min_m"])
    exaggeration = float(outer["terrain"]["vertical_exaggeration"])

    before = set(bpy.data.objects)
    field_terrain, field_sampler = base.create_terrain(field, collections["terrain"])
    field_terrain.name = "Terrain_Osong_Field_HQ_1km"
    replace_material(field_terrain, feathered_aerial(Path(field["aerial"]["path"]), "V19_Mat_FieldHQ_Feathered"))
    base.create_roads(field, field_sampler, collections["roads"])
    base.create_buildings(field, field_sampler, collections["buildings"])
    field_obj, field_outline = base.create_field(field, field_sampler, collections["field"])
    field_align = (float(field["terrain"]["elevation_min_m"]) - outer_min) * exaggeration + 0.18
    field_created = move_created(before, dz=field_align)

    before = set(bpy.data.objects)
    shelter_terrain, shelter_sampler = base.create_terrain(shelter, shelter_collection)
    shelter_terrain.name = "Terrain_Osong_Shelter_HQ_1km"
    replace_material(shelter_terrain, feathered_aerial(Path(shelter["aerial"]["path"]), "V19_Mat_ShelterHQ_Feathered"))
    road_count, bridge_count = base.create_roads(shelter, shelter_sampler, shelter_collection)
    building_count = base.create_buildings(shelter, shelter_sampler, shelter_collection)
    shelter_align = (float(shelter["terrain"]["elevation_min_m"]) - outer_min) * exaggeration + 0.2
    shelter_created = move_created(before, shelter_offset.x, shelter_offset.y, shelter_align)

    base.create_lighting(scene, collections["lighting"])
    fx, fy = centroid(field["field"]["polygon"])
    field_target = (fx, fy, field_sampler.z(fx, fy) + field_align + 10)
    shelter_z = shelter_sampler.z(0, 0) + shelter_align + 6
    shelter_target = (shelter_offset.x, shelter_offset.y, shelter_z + 8)
    midpoint = ((fx + shelter_offset.x) / 2, (fy + shelter_offset.y) / 2, max(field_target[2], shelter_z) + 15)
    camera, keys = create_camera(base, collections["lighting"], field_target, shelter_target, midpoint)
    marker_objects = create_marker(base, marker_collection, (shelter_offset.x, shelter_offset.y, shelter_z), camera)

    scene.camera = camera
    engine = base.configure_render(scene)
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.fps = FPS
    scene.frame_start = 1
    scene.frame_end = FRAME_END
    scene.render.image_settings.file_format = "PNG"
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.clip_start = 1.0
                area.spaces.active.clip_end = 50_000.0

    scene["v19_dataset_id"] = "OSONG-SHELTER-V19"
    scene["v19_shelter_name"] = shelter["shelter"]["name"]
    scene["v19_shelter_wgs84"] = [shelter["shelter"]["lon"], shelter["shelter"]["lat"]]
    scene["v19_regional_size_m"] = [12000.0, 12000.0]
    scene["v19_flood_animation_included"] = False
    scene["v19_camera_animation_included"] = True
    scene["v19_created_at_utc"] = datetime.now(timezone.utc).isoformat()

    previews = [
        (1, PREVIEW_DIR / "01_regional_overview.png"),
        (216, PREVIEW_DIR / "02_field_close.png"),
        (384, PREVIEW_DIR / "03_shelter_reveal.png"),
        (528, PREVIEW_DIR / "04_shelter_close.png"),
    ]
    for frame, path in previews:
        scene.frame_set(frame)
        base.render(scene, camera, path)
    scene.frame_set(1)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    flood_named = [obj.name for obj in bpy.data.objects if any(t in obj.name.lower() for t in ("flood", "inundation", "hazard"))]
    report = {
        "status": "ok",
        "scene": scene.name,
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "blend_sha256": sha256(BLEND_PATH),
        "render_engine": engine,
        "regional_size_m": [12000.0, 12000.0],
        "field_hq_size_m": [1000.0, 1000.0],
        "shelter_hq_size_m": [1000.0, 1000.0],
        "shelter": shelter["shelter"],
        "shelter_objects": {"roads": road_count, "bridges": bridge_count, "buildings": building_count},
        "camera": {"fps": FPS, "frame_end": FRAME_END, "duration_seconds": FRAME_END / FPS, "keyframes": [{"frame": f, "shot": shot} for f, _l, _a, _n, shot in keys]},
        "preview_renders": [str(path) for _frame, path in previews],
        "flood_animation_included": False,
        "flood_named_objects": flood_named,
        "marker_object_count": len(marker_objects),
        "packed_images": sum(1 for image in bpy.data.images if image.packed_file),
        "video_rendered": False,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["blender_scene"] = {"path": str(BLEND_PATH), "bytes": BLEND_PATH.stat().st_size, "sha256": report["blend_sha256"], "camera_animation": True, "flood_animation": False, "video_rendered": False}
    manifest["scene_report"] = str(REPORT_PATH)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
