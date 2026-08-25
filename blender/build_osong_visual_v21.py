"""Build the selective high-detail V21 field/river scene on preserved V20."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
CONTEXT_PATH = ROOT / "data" / "processed" / "osong_visual_v21_context.json"
MANIFEST_PATH = ROOT / "data" / "processed" / "osong_visual_v21_manifest.json"
OUTER_PATH = ROOT / "data" / "processed" / "osong_shelter_v19_outer.json"
SOURCE_BLEND_PATH = ROOT / "blender" / "osong_flood_v20.blend"
BLEND_PATH = ROOT / "blender" / "osong_visual_v21.blend"
BASE_SCRIPT = ROOT / "blender" / "build_gangnae_hq_v10.py"
V19_SCRIPT = ROOT / "blender" / "build_osong_shelter_v19.py"
V20_SCRIPT = ROOT / "blender" / "build_osong_flood_v20.py"
OUTPUT_DIR = ROOT / "output" / "visual_v21"
PREVIEW_DIR = OUTPUT_DIR / "previews"
REPORT_PATH = OUTPUT_DIR / "scene_report.json"


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


def remove_object(name):
    obj = bpy.data.objects.get(name)
    if obj:
        bpy.data.objects.remove(obj, do_unlink=True)


def clear_collection(name):
    collection = bpy.data.collections.get(name)
    if collection:
        for obj in list(collection.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)


def ensure_collection(scene, name):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        scene.collection.children.link(collection)
    return collection


def relink_active(obj, collection):
    for source in list(obj.users_collection):
        source.objects.unlink(obj)
    collection.objects.link(obj)


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


def water_material():
    material = bpy.data.materials.new("V21_Mat_MihoRiver_PBR")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    texcoord = nodes.new("ShaderNodeTexCoord")
    noise_large = nodes.new("ShaderNodeTexNoise")
    noise_small = nodes.new("ShaderNodeTexNoise")
    mix = nodes.new("ShaderNodeMixRGB")
    bump = nodes.new("ShaderNodeBump")
    noise_large.inputs["Scale"].default_value = 1.8
    noise_large.inputs["Detail"].default_value = 5.0
    noise_large.inputs["Roughness"].default_value = 0.58
    noise_small.inputs["Scale"].default_value = 14.0
    noise_small.inputs["Detail"].default_value = 3.0
    mix.blend_type = "MULTIPLY"
    mix.inputs[0].default_value = 0.42
    bump.inputs["Strength"].default_value = 0.22
    bump.inputs["Distance"].default_value = 0.16
    water_alpha = 0.68
    material.diffuse_color = (0.006, 0.065, 0.095, water_alpha)
    shader.inputs["Base Color"].default_value = (0.006, 0.065, 0.095, 1.0)
    shader.inputs["Roughness"].default_value = 0.24
    shader.inputs["Metallic"].default_value = 0.02
    if shader.inputs.get("Alpha"):
        shader.inputs["Alpha"].default_value = water_alpha
    if shader.inputs.get("Transmission Weight"):
        shader.inputs["Transmission Weight"].default_value = 0.12
    try:
        material.surface_render_method = "DITHERED"
    except (AttributeError, TypeError):
        try:
            material.blend_method = "BLEND"
        except (AttributeError, TypeError):
            pass
    if shader.inputs.get("Coat Weight"):
        shader.inputs["Coat Weight"].default_value = 0.34
        shader.inputs["Coat Roughness"].default_value = 0.08
    links.new(texcoord.outputs["Generated"], noise_large.inputs["Vector"])
    links.new(texcoord.outputs["Generated"], noise_small.inputs["Vector"])
    links.new(noise_large.outputs["Fac"], mix.inputs[1])
    links.new(noise_small.outputs["Fac"], mix.inputs[2])
    links.new(mix.outputs["Color"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], shader.inputs["Normal"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return material


def create_bank_lines(base, context, sampler, collection, field_align):
    material = base.new_material("V21_Mat_WetBank", (0.055, 0.065, 0.045), 0.94)
    objects = []
    for index, points in enumerate(context["river"]["boundary_lines"]):
        obj = base.strip_mesh(
            f"RiverBankWetEdge_V21_{index:02d}", points, 3.6, sampler, collection, material, 0.12
        )
        if obj:
            obj.location.z += field_align
            obj["visual_role"] = "wet river bank edge"
            obj["surveyed_bankline"] = False
            objects.append(obj)
    return objects


def create_tree_assets(base, context, collection):
    trunk_material = base.new_material("V21_Mat_TreeTrunk", (0.13, 0.065, 0.025), 0.92)
    crown_material = base.new_material("V21_Mat_TreeCrown", (0.035, 0.16, 0.045), 0.82)
    trunk_mesh = None
    crown_mesh = None
    objects = []
    for index, item in enumerate(context["vegetation"]):
        height = float(item["height_m"])
        crown = float(item["crown_m"])
        z = float(item["z"])
        if trunk_mesh is None:
            bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=0.34, depth=1.0)
            template = bpy.context.object
            trunk_mesh = template.data
            bpy.data.objects.remove(template, do_unlink=True)
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1.0)
            template = bpy.context.object
            crown_mesh = template.data
            bpy.data.objects.remove(template, do_unlink=True)
        trunk = bpy.data.objects.new(f"TreeTrunk_V21_{index:03d}", trunk_mesh)
        collection.objects.link(trunk)
        trunk.location = (float(item["x"]), float(item["y"]), z + height * 0.21)
        trunk.scale = (0.7 + crown * 0.04, 0.7 + crown * 0.04, height * 0.42)
        trunk.data.materials.clear()
        trunk.data.materials.append(trunk_material)
        canopy = bpy.data.objects.new(f"TreeCrown_V21_{index:03d}", crown_mesh)
        collection.objects.link(canopy)
        canopy.location = (float(item["x"]), float(item["y"]), z + height * 0.66)
        canopy.scale = (crown, crown * 0.86, height * 0.48)
        canopy.data.materials.clear()
        canopy.data.materials.append(crown_material)
        for obj in (trunk, canopy):
            obj["placement_accuracy"] = item["placement_accuracy"]
        objects.extend([trunk, canopy])
    return objects


def render_previews(scene):
    specs = [
        (1, "01_overview_dry"),
        (96, "02_river_approach"),
        (240, "03_first_flood_max"),
        (384, "04_field_dry_close"),
        (480, "05_field_flood_mid"),
        (600, "06_field_flood_max"),
        (720, "07_zoom_out_flooded"),
        (960, "08_shelter_close"),
    ]
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    results = []
    for frame, name in specs:
        scene.frame_set(frame)
        path = PREVIEW_DIR / f"{name}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        if not path.is_file() or path.stat().st_size < 10_000:
            raise RuntimeError(f"V21 preview render failed: {path}")
        results.append({"frame": frame, "path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)})
    return results


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    context = load_json(CONTEXT_PATH)
    outer = load_json(OUTER_PATH)
    manifest = load_json(MANIFEST_PATH)
    base = load_module("build_osong_visual_v21_base", BASE_SCRIPT)
    v19 = load_module("build_osong_visual_v21_v19", V19_SCRIPT)
    v20 = load_module("build_osong_visual_v21_v20", V20_SCRIPT)
    scene = bpy.context.scene
    if scene.name != "Osong_Flood_V20":
        raise RuntimeError(f"V21 must start from V20, got {scene.name}")
    if scene.camera is None or scene.camera.name != "Camera_Osong_Shelter_V19":
        raise RuntimeError("The approved V20 camera is missing")

    # Replace only the field/river high-detail visual layers; preserve camera,
    # regional background, flood stages and shelter assets.
    remove_object("Terrain_Osong_Field_HQ_1km")
    for name in (
        "V19_FIELD_ROADS",
        "V19_FIELD_BUILDINGS",
        "V19_REGISTERED_FIELD",
        "V20_CONTINUOUS_RIVER",
        "V20_FLOOD_STAGES",
        "V21_FLOOD_STAGES",
    ):
        clear_collection(name)
    terrain_collection = ensure_collection(scene, "V21_FIELD_RIVER_HQ")
    road_collection = ensure_collection(scene, "V21_FIELD_ROADS")
    building_collection = ensure_collection(scene, "V21_FIELD_BUILDINGS")
    field_collection = ensure_collection(scene, "V21_REGISTERED_FIELD")
    river_collection = ensure_collection(scene, "V21_CONTINUOUS_RIVER")
    bank_collection = ensure_collection(scene, "V21_RIVER_BANK")
    vegetation_collection = ensure_collection(scene, "V21_BANK_VEGETATION")
    flood_collection = ensure_collection(scene, "V21_FLOOD_STAGES")

    before = set(bpy.data.objects)
    terrain, sampler = base.create_terrain(context, terrain_collection)
    terrain.name = "Terrain_Osong_FieldRiver_HQ_1500m_V21"
    v19.replace_material(
        terrain,
        v19.feathered_aerial(Path(context["aerial"]["path"]), "V21_Mat_FieldRiverHQ_Feathered"),
    )
    outer_min = float(outer["terrain"]["elevation_min_m"])
    exaggeration = float(context["terrain"]["vertical_exaggeration"])
    field_align = (float(context["terrain"]["elevation_min_m"]) - outer_min) * exaggeration + 0.18
    terrain.location.z += field_align
    terrain["detail_level"] = "selective HQ z19 visual core"
    terrain["source_dem_accuracy"] = context["terrain"]["source_resolution"]
    terrain["channel_carved"] = True

    road_count, bridge_count = base.create_roads(context, sampler, road_collection)
    building_count = base.create_buildings(context, sampler, building_collection)
    field_obj, field_outline = base.create_field(context, sampler, field_collection)
    for obj in [obj for obj in bpy.data.objects if obj not in before and obj is not terrain]:
        obj.location.z += field_align
    if field_obj:
        field_obj.name = "RegisteredFieldFill_V21"
    if field_outline:
        field_outline.name = "RegisteredFieldBoundary_V21"

    river = mesh_object(
        "RiverSurface_Miho_V21_Continuous",
        context["river"]["mesh"],
        river_collection,
        water_material(),
        {
            "source": context["river"]["source"],
            "continuous": True,
            "hole_count": context["validation"]["river_hole_count"],
            "surveyed_bankline": False,
            "hydraulic_model": False,
            "z_spread_scene_m": round(
                context["river"]["new_v21_z_range_scene_m"][1]
                - context["river"]["new_v21_z_range_scene_m"][0], 4
            ),
        },
    )
    bank_objects = create_bank_lines(base, context, sampler, bank_collection, field_align)
    tree_objects = create_tree_assets(base, context, vegetation_collection)

    flood_material = v20.water_material(
        base,
        "V21_Mat_FloodWater_Coherent",
        (0.025, 0.24, 0.58),
        alpha=0.72,
        roughness=0.22,
    )
    flood_objects = []
    for stage in context["flood"]["stages"]:
        obj = mesh_object(
            f"FloodWaterV21_Step_{int(stage['step']):02d}",
            stage["mesh"],
            flood_collection,
            flood_material,
            {
                "visual_role": "official-bound coherent flood water",
                "official_extent_fraction": float(stage["official_extent_fraction"]),
                "visual_depth_cap_m": float(stage["visual_depth_cap_m"]),
                "field_affected_percent": float(stage["field_affected_percent"]),
                "hydraulic_time_series": False,
                "small_holes_cleaned": True,
            },
        )
        flood_objects.append(obj)
    if len(flood_objects) != 10:
        raise RuntimeError(f"V21 requires 10 flood stage objects, got {len(flood_objects)}")
    cycle_one_frames, cycle_two_frames = v20.animate_stages(flood_objects)

    # Preserve the approved V20 keyframes exactly.
    camera_keyframe_samples = {}
    for frame in (1, 48, 240, 264, 360, 384, 600, 720, 768, 888, 960):
        scene.frame_set(frame)
        camera_keyframe_samples[str(frame)] = [round(float(value), 4) for value in scene.camera.location]
    scene.name = "Osong_Visual_V21"
    scene["story_version"] = "V21"
    scene["v21_source_v20_preserved"] = True
    scene["v21_camera_keyframes_preserved"] = True
    scene["v21_hq_size_m"] = [1500.0, 1500.0]
    scene["v21_aerial_zoom"] = 19
    scene["v21_river_continuous"] = True
    scene["v21_river_hole_count"] = 0
    scene["v21_flood_stage_count"] = len(flood_objects)
    scene["v21_flood_surface_method"] = context["flood"]["surface_method"]
    scene["v21_video_rendered"] = False
    scene["v21_created_at_utc"] = datetime.now(timezone.utc).isoformat()
    scene.frame_start = 1
    scene.frame_end = 960
    scene.render.fps = 24
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.clip_start = 0.5
                area.spaces.active.clip_end = 50_000.0

    previews = render_previews(scene)
    scene.frame_set(1)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    report = {
        "status": "rendered_pending_visual_review",
        "source_blend": str(SOURCE_BLEND_PATH),
        "source_v20_unchanged": True,
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "blend_sha256": sha256(BLEND_PATH),
        "hq_size_m": [1500.0, 1500.0],
        "aerial_zoom": 19,
        "aerial_pixels": context["aerial"]["pixel_size"],
        "terrain_vertices": len(terrain.data.vertices),
        "terrain_faces": len(terrain.data.polygons),
        "channel_vertices_changed": context["terrain"]["channel_carve"]["changed_vertex_count"],
        "river_object": river.name,
        "river_vertices": len(river.data.vertices),
        "river_faces": len(river.data.polygons),
        "river_holes": context["validation"]["river_hole_count"],
        "old_river_z_spread_scene_m": context["river"]["old_v20_z_range_scene_m"][1] - context["river"]["old_v20_z_range_scene_m"][0],
        "new_river_z_spread_scene_m": context["river"]["new_v21_z_range_scene_m"][1] - context["river"]["new_v21_z_range_scene_m"][0],
        "roads": road_count,
        "bridges": bridge_count,
        "buildings": building_count,
        "bank_objects": len(bank_objects),
        "vegetation_objects": len(tree_objects),
        "camera_keyframe_samples": camera_keyframe_samples,
        "camera_keyframes_preserved": True,
        "old_v20_flood_stage_objects_remaining": len([obj for obj in bpy.data.objects if obj.name.startswith("FloodWaterV20_Step_")]),
        "flood_stage_objects": len(flood_objects),
        "flood_stage_faces": [len(obj.data.polygons) for obj in flood_objects],
        "flood_cycle_one_frames": cycle_one_frames,
        "flood_cycle_two_frames": cycle_two_frames,
        "previews": previews,
        "video_rendered": False,
        "visual_review": "pending",
        "limitations": context["limitations"],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["status"] = "blender_scene_built_pending_visual_review"
    manifest["blender_scene"] = {
        "path": str(BLEND_PATH),
        "bytes": BLEND_PATH.stat().st_size,
        "sha256": report["blend_sha256"],
        "source_v20_unchanged": True,
        "camera_keyframes_preserved": True,
        "video_rendered": False,
    }
    manifest["scene_report"] = str(REPORT_PATH)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
