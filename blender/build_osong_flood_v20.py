"""Add continuous river, two flood cycles, and the shelter ending to V19."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import bpy

ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
DATA_PATH = ROOT / "data" / "processed" / "osong_flood_v20.json"
MANIFEST_PATH = ROOT / "data" / "processed" / "osong_flood_v20_manifest.json"
FIELD_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_hq_v11_context.json"
SHELTER_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_shelter_v19_hq.json"
SOURCE_BLEND_PATH = ROOT / "blender" / "osong_shelter_v19.blend"
BLEND_PATH = ROOT / "blender" / "osong_flood_v20.blend"
OUTPUT_DIR = ROOT / "output" / "flood_v20"
PREVIEW_DIR = OUTPUT_DIR / "previews"
REPORT_PATH = OUTPUT_DIR / "scene_report.json"
BASE_SCRIPT = ROOT / "blender" / "build_gangnae_hq_v10.py"
FPS = 24
FRAME_END = 960
CYCLE_ONE_START = 48
CYCLE_ONE_RESET = 264
CYCLE_TWO_START = 384


def load_json(path):
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


def remove_collection(name):
    collection = bpy.data.collections.get(name)
    if collection:
        for obj in list(collection.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(collection)


def mesh_object(name, mesh_data, collection, material, properties):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(mesh_data["vertices"], [], mesh_data["faces"])
    mesh.validate(verbose=True)
    mesh.update(calc_edges=True)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.data.materials.append(material)
    for key, value in properties.items():
        obj[key] = value
    return obj


def water_material(base, name, colour, alpha, roughness=0.18):
    material = base.new_material(name, colour, roughness=roughness, metallic=0.04, alpha=alpha)
    material.diffuse_color = (*colour, alpha)
    shader = material.node_tree.nodes.get("Principled BSDF") if material.node_tree else None
    if shader:
        if shader.inputs.get("Coat Weight"):
            shader.inputs["Coat Weight"].default_value = 0.22
        if shader.inputs.get("Coat Roughness"):
            shader.inputs["Coat Roughness"].default_value = 0.10
    return material


def set_hidden_key(obj, frame, hidden):
    obj.hide_render = hidden
    obj.hide_viewport = hidden
    obj.keyframe_insert(data_path="hide_render", frame=frame)
    obj.keyframe_insert(data_path="hide_viewport", frame=frame)


def animate_stages(objects):
    step_spacing = 19
    cycle_one_frames = [CYCLE_ONE_START + i * step_spacing for i in range(10)]
    cycle_two_frames = [CYCLE_TWO_START + i * step_spacing for i in range(10)]
    for index, obj in enumerate(objects):
        set_hidden_key(obj, 1, True)
        first = cycle_one_frames[index]
        set_hidden_key(obj, first - 1, True)
        set_hidden_key(obj, first, False)
        first_end = cycle_one_frames[index + 1] if index < 9 else CYCLE_ONE_RESET
        set_hidden_key(obj, first_end, True)

        second = cycle_two_frames[index]
        set_hidden_key(obj, second - 1, True)
        set_hidden_key(obj, second, False)
        if index < 9:
            set_hidden_key(obj, cycle_two_frames[index + 1], True)
        else:
            set_hidden_key(obj, FRAME_END, False)
    return cycle_one_frames, cycle_two_frames


def clear_animation(obj):
    if obj:
        obj.animation_data_clear()


def animate_camera(field_target, shelter_target, midpoint):
    camera = bpy.data.objects.get("Camera_Osong_Shelter_V19")
    target = bpy.data.objects.get("CameraTarget_Osong_Shelter_V19")
    if camera is None or target is None:
        raise RuntimeError("V19 camera or target is missing")
    clear_animation(camera)
    clear_animation(camera.data)
    clear_animation(target)
    keys = [
        (1, (1800, -2200, 1600), field_target, 52, "river_field_overview_dry"),
        (48, (1650, -2000, 1480), field_target, 54, "first_flood_start"),
        (240, (1450, -1750, 1320), field_target, 57, "first_flood_maximum"),
        (264, (1450, -1750, 1320), field_target, 57, "instant_reset"),
        (360, (620, -920, 620), field_target, 58, "field_zoom_in_dry"),
        (384, (560, -830, 570), field_target, 60, "second_flood_start"),
        (600, (470, -700, 500), field_target, 62, "second_flood_maximum_hold"),
        (720, (850, -2200, 3300), midpoint, 50, "flooded_field_zoom_out"),
        (768, (1150, -350, 2400), shelter_target, 54, "shelter_reveal"),
        (888, (2150, 1920, 680), shelter_target, 62, "shelter_zoom_in"),
        (960, (2050, 2050, 590), shelter_target, 66, "shelter_hold"),
    ]
    for frame, location, aim, lens, _shot in keys:
        camera.location = location
        camera.data.lens = lens
        target.location = aim
        camera.keyframe_insert(data_path="location", frame=frame)
        camera.data.keyframe_insert(data_path="lens", frame=frame)
        target.keyframe_insert(data_path="location", frame=frame)
    return camera, keys


def animate_marker():
    names = [
        "ShelterMarker_Pillar",
        "ShelterMarker_Arrow",
        "ShelterMarker_Ring",
        "ShelterLabel_OsongWelfareCenter",
    ]
    objects = []
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise RuntimeError(f"V19 shelter marker is missing: {name}")
        clear_animation(obj)
        obj.scale = (0.001,) * 3
        obj.keyframe_insert(data_path="scale", frame=719)
        obj.scale = (2.8,) * 3
        obj.keyframe_insert(data_path="scale", frame=744)
        obj.scale = (2.2,) * 3
        obj.keyframe_insert(data_path="scale", frame=768)
        obj.scale = (1.0,) * 3
        obj.keyframe_insert(data_path="scale", frame=888)
        obj.keyframe_insert(data_path="scale", frame=960)
        objects.append(obj)
    return objects


def field_centre(context):
    points = context["field"]["polygon"]
    return (
        sum(float(point[0]) for point in points) / len(points),
        sum(float(point[1]) for point in points) / len(points),
    )


def targets(base, field, shelter, flood):
    outer_min = float(load_json(ROOT / "data" / "processed" / "osong_shelter_v19_outer.json")["terrain"]["elevation_min_m"])
    exaggeration = float(field["terrain"]["vertical_exaggeration"])
    field_align = (float(field["terrain"]["elevation_min_m"]) - outer_min) * exaggeration + 0.18
    shelter_align = (float(shelter["terrain"]["elevation_min_m"]) - outer_min) * exaggeration + 0.2
    field_sampler = base.TerrainSampler(field["terrain"])
    shelter_sampler = base.TerrainSampler(shelter["terrain"])
    fx, fy = field_centre(field)
    sx, sy = map(float, shelter["shelter"]["local_from_field_origin_m"])
    fz = field_sampler.z(fx, fy) + field_align + 10
    sz = shelter_sampler.z(0, 0) + shelter_align + 14
    field_target = (fx, fy, fz)
    shelter_target = (sx, sy, sz)
    midpoint = ((fx + sx) / 2, (fy + sy) / 2, max(fz, sz) + 15)
    return field_target, shelter_target, midpoint


def render_previews(scene, camera):
    specs = [
        (1, "01_dry_overview"),
        (144, "02_first_flood_mid"),
        (240, "03_first_flood_max"),
        (264, "04_reset_dry"),
        (384, "05_field_dry"),
        (480, "06_field_flood_mid"),
        (600, "07_field_flood_max"),
        (768, "08_shelter_reveal"),
        (960, "09_shelter_close"),
    ]
    outputs = []
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    for frame, name in specs:
        scene.frame_set(frame)
        path = PREVIEW_DIR / f"{name}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        if not path.is_file() or path.stat().st_size < 10_000:
            raise RuntimeError(f"Preview render failed: {path}")
        outputs.append({"frame": frame, "path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)})
    return outputs


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    data = load_json(DATA_PATH)
    field = load_json(FIELD_CONTEXT_PATH)
    shelter = load_json(SHELTER_CONTEXT_PATH)
    manifest = load_json(MANIFEST_PATH)
    base = load_module("build_osong_flood_v20_base", BASE_SCRIPT)
    scene = bpy.context.scene
    if scene.name != "Osong_Shelter_V19":
        raise RuntimeError(f"V20 must start from the V19 scene, got {scene.name}")

    remove_collection("V20_CONTINUOUS_RIVER")
    remove_collection("V20_FLOOD_STAGES")
    river_collection = bpy.data.collections.new("V20_CONTINUOUS_RIVER")
    flood_collection = bpy.data.collections.new("V20_FLOOD_STAGES")
    scene.collection.children.link(river_collection)
    scene.collection.children.link(flood_collection)

    river_mat = water_material(base, "V20_Mat_ContinuousRiver", (0.005, 0.16, 0.28), 0.94)
    river = mesh_object(
        "RiverSurface_Osong_V20_Continuous",
        data["river"]["mesh"],
        river_collection,
        river_mat,
        {
            "dataset_id": data["dataset_id"],
            "source_provider": data["river"]["source_provider"],
            "visual_role": "continuous baseline river",
            "hydraulic_model": False,
        },
    )

    stage_objects = []
    for stage in data["flood"]["stages"]:
        ratio = (int(stage["step"]) - 1) / 9.0
        colour = (0.015, 0.31 - 0.08 * ratio, 0.66 - 0.10 * ratio)
        material = water_material(base, f"V20_Mat_Flood_{stage['step']:02d}", colour, 0.62 + 0.10 * ratio)
        obj = mesh_object(
            f"FloodWaterV20_Step_{stage['step']:02d}",
            stage["water_mesh"],
            flood_collection,
            material,
            {
                "step": int(stage["step"]),
                "official_extent_fraction": float(stage["official_extent_fraction"]),
                "visual_depth_cap_m": float(stage["visual_depth_cap_m"]),
                "field_affected_percent": float(stage["field_affected_percent"]),
                "visual_role": "official-bound blue flood water",
                "hydraulic_time_series": False,
                "hazard_map_class_colour": False,
            },
        )
        stage_objects.append(obj)
    cycle_one_frames, cycle_two_frames = animate_stages(stage_objects)

    field_target, shelter_target, midpoint = targets(base, field, shelter, data)
    camera, camera_keys = animate_camera(field_target, shelter_target, midpoint)
    marker_objects = animate_marker()
    scene.camera = camera
    scene.name = "Osong_Flood_V20"
    scene.frame_start = 1
    scene.frame_end = FRAME_END
    scene.render.fps = FPS
    scene["story_version"] = "V20"
    scene["v20_dataset"] = data["dataset_id"]
    scene["v20_source_v19_preserved"] = True
    scene["v20_continuous_river"] = True
    scene["v20_flood_cycle_count"] = 2
    scene["v20_flood_stage_count"] = 10
    scene["v20_flood_animation_seconds_per_cycle"] = (cycle_one_frames[-1] - cycle_one_frames[0]) / FPS
    scene["v20_hazard_map_overlay_visible"] = False
    scene["v20_hydraulic_time_series"] = False
    scene["v20_shelter_ending"] = True
    scene["v20_video_rendered"] = False
    scene["v20_created_at_utc"] = datetime.now(timezone.utc).isoformat()

    previews = render_previews(scene, camera)
    scene.frame_set(1)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    hazard_named = [obj.name for obj in bpy.data.objects if "hazard" in obj.name.lower()]
    report = {
        "status": "rendered_pending_visual_review",
        "source_blend": str(SOURCE_BLEND_PATH),
        "source_v19_unchanged": True,
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "blend_sha256": sha256(BLEND_PATH),
        "river_object": river.name,
        "river_faces": len(river.data.polygons),
        "flood_stage_objects": len(stage_objects),
        "flood_stage_faces": [len(obj.data.polygons) for obj in stage_objects],
        "flood_cycles": 2,
        "flood_seconds_per_cycle": round((cycle_one_frames[-1] - cycle_one_frames[0]) / FPS, 3),
        "maximum_field_affected_percent": data["field"]["maximum_affected_percent"],
        "hazard_map_overlay_visible": False,
        "hazard_named_objects": hazard_named,
        "hydraulic_time_series": False,
        "camera_keyframes": [{"frame": frame, "shot": shot} for frame, _loc, _aim, _lens, shot in camera_keys],
        "marker_objects": [obj.name for obj in marker_objects],
        "previews": previews,
        "video_duration_seconds": FRAME_END / FPS,
        "video_rendered": False,
        "visual_review": "pending",
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["status"] = "blender_scene_built_pending_visual_review"
    manifest["blender_scene"] = {
        "path": str(BLEND_PATH),
        "bytes": BLEND_PATH.stat().st_size,
        "sha256": report["blend_sha256"],
        "source_v19_unchanged": True,
        "video_rendered": False,
    }
    manifest["scene_report"] = str(REPORT_PATH)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
