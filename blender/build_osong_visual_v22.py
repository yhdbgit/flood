"""Build V22 selective 3D structures on the reviewed V21 baseline."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import bpy

ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
V22_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_visual_v22_context.json"
V21_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_visual_v21_context.json"
MANIFEST_PATH = ROOT / "data" / "processed" / "osong_visual_v22_manifest.json"
SOURCE_BLEND_PATH = ROOT / "blender" / "osong_visual_v21.blend"
BLEND_PATH = ROOT / "blender" / "osong_visual_v22.blend"
BASE_SCRIPT = ROOT / "blender" / "build_gangnae_hq_v10.py"
OUTPUT_DIR = ROOT / "output" / "visual_v22"
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


def ensure_collection(scene, name):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        scene.collection.children.link(collection)
    return collection


def clear_collection(name):
    collection = bpy.data.collections.get(name)
    if collection:
        for obj in list(collection.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)


def material(base, name, colour, roughness, metallic=0.0, alpha=1.0, transmission=0.0):
    mat = base.new_material(name, colour, roughness=roughness, metallic=metallic, alpha=alpha)
    shader = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if shader:
        if shader.inputs.get("Transmission Weight"):
            shader.inputs["Transmission Weight"].default_value = transmission
        if shader.inputs.get("Coat Weight"):
            shader.inputs["Coat Weight"].default_value = 0.22
        if shader.inputs.get("Coat Roughness"):
            shader.inputs["Coat Roughness"].default_value = 0.14
    return mat


def distance(a, b):
    return math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))


def midpoint(a, b):
    return ((float(a[0]) + float(b[0])) / 2.0, (float(a[1]) + float(b[1])) / 2.0)


def create_proxy_structure(item, sampler, z_align, collection, materials):
    points = [tuple(map(float, point)) for point in item["polygon"]]
    if len(points) != 4:
        return None
    kind = item["kind"]
    is_greenhouse = kind == "greenhouse_visual_proxy"
    total_height = float(item["height_m"])
    wall_height = total_height * (0.64 if is_greenhouse else 0.78)
    roof_rise = total_height - wall_height
    ground = [sampler.z(x, y) + z_align + 0.06 for x, y in points]
    bottom = [(x, y, z) for (x, y), z in zip(points, ground)]
    top = [(x, y, z + wall_height) for (x, y), z in zip(points, ground)]
    vertices = bottom + top
    faces = [
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
        (3, 2, 1, 0),
    ]
    material_indices = [0, 0, 0, 0, 0]
    if distance(points[0], points[1]) >= distance(points[1], points[2]):
        ridge_a = midpoint(points[0], points[3])
        ridge_b = midpoint(points[1], points[2])
        ridge_a_z = (top[0][2] + top[3][2]) / 2.0 + roof_rise
        ridge_b_z = (top[1][2] + top[2][2]) / 2.0 + roof_rise
        vertices.extend([(ridge_a[0], ridge_a[1], ridge_a_z), (ridge_b[0], ridge_b[1], ridge_b_z)])
        faces.extend([(4, 5, 9, 8), (7, 8, 9, 6), (4, 8, 7), (5, 6, 9)])
    else:
        ridge_a = midpoint(points[0], points[1])
        ridge_b = midpoint(points[3], points[2])
        ridge_a_z = (top[0][2] + top[1][2]) / 2.0 + roof_rise
        ridge_b_z = (top[3][2] + top[2][2]) / 2.0 + roof_rise
        vertices.extend([(ridge_a[0], ridge_a[1], ridge_a_z), (ridge_b[0], ridge_b[1], ridge_b_z)])
        faces.extend([(4, 8, 9, 7), (5, 6, 9, 8), (4, 5, 8), (7, 9, 6)])
    material_indices.extend([1, 1, 1, 1])
    mesh = bpy.data.meshes.new(f"{item['candidate_id']}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(verbose=True)
    mesh.update(calc_edges=True)
    mesh.materials.append(materials["greenhouse_wall"] if is_greenhouse else materials["proxy_wall"])
    if is_greenhouse:
        roof_material = materials["greenhouse_roof"]
    else:
        palette_index = int(item["candidate_id"].rsplit("-", 1)[-1]) % len(materials["proxy_roofs"])
        roof_material = materials["proxy_roofs"][palette_index]
    mesh.materials.append(roof_material)
    for polygon, index in zip(mesh.polygons, material_indices):
        polygon.material_index = index
    obj = bpy.data.objects.new(f"ProxyStructure_{item['candidate_id']}", mesh)
    collection.objects.link(obj)
    for key in ("candidate_id", "kind", "source_role", "surveyed", "cadastral", "confidence", "area_m2", "height_m"):
        obj[key] = item[key]
    obj["submission_disclosure"] = "image-derived visual proxy; not authoritative building data"
    bevel = obj.modifiers.new("V22 edge softening", "BEVEL")
    bevel.width = 0.18 if is_greenhouse else 0.28
    bevel.segments = 2
    return obj


def tune_shelter_marker():
    """Keep the destination legible without hiding the mapped building cluster."""
    names = (
        "ShelterMarker_Pillar",
        "ShelterMarker_Arrow",
        "ShelterMarker_Ring",
        "ShelterLabel_OsongWelfareCenter",
    )
    scales = {
        719: 0.001,
        744: 1.20,
        768: 0.82,
        888: 0.42,
        960: 0.30,
    }
    tuned = []
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise RuntimeError(f"V22 shelter marker is missing: {name}")
        obj.animation_data_clear()
        for frame, value in scales.items():
            obj.scale = (value, value, value)
            obj.keyframe_insert(data_path="scale", frame=frame)
        obj["v22_marker_reduced_to_reveal_buildings"] = True
        tuned.append(obj)
    return tuned


def restyle_shelter_buildings(base):
    collection = bpy.data.collections.get("V19_SHELTER_HQ")
    if collection is None:
        raise RuntimeError("V19 shelter HQ collection is missing")
    palettes = [
        (
            material(base, "V22_Mat_ShelterWall_Warm", (0.55, 0.50, 0.43), 0.72),
            material(base, "V22_Mat_ShelterRoof_Red", (0.32, 0.075, 0.045), 0.62),
        ),
        (
            material(base, "V22_Mat_ShelterWall_Light", (0.68, 0.66, 0.59), 0.74),
            material(base, "V22_Mat_ShelterRoof_Blue", (0.065, 0.19, 0.30), 0.58, metallic=0.08),
        ),
        (
            material(base, "V22_Mat_ShelterWall_Concrete", (0.40, 0.42, 0.40), 0.80),
            material(base, "V22_Mat_ShelterRoof_Dark", (0.08, 0.09, 0.10), 0.64),
        ),
    ]
    buildings = []
    for obj in collection.all_objects:
        if not obj.name.startswith("Building_") or obj.type != "MESH":
            continue
        source_id = int(obj.get("osm_id", len(buildings)))
        wall, roof = palettes[source_id % len(palettes)]
        obj.data.materials.clear()
        obj.data.materials.append(wall)
        obj.data.materials.append(roof)
        obj["source_role"] = "verified OSM footprint"
        obj["authoritative_building_register"] = False
        buildings.append(obj)
    return buildings


def soften_field_overlay():
    obj = bpy.data.objects.get("RegisteredFieldFill_V21")
    if obj is None or not obj.data.materials:
        return False
    mat = obj.data.materials[0]
    alpha = 0.08
    mat.diffuse_color = (*mat.diffuse_color[:3], alpha)
    if mat.node_tree:
        shader = mat.node_tree.nodes.get("Principled BSDF")
        if shader and shader.inputs.get("Alpha"):
            shader.inputs["Alpha"].default_value = alpha
    try:
        mat.surface_render_method = "DITHERED"
    except (AttributeError, TypeError):
        pass
    obj["v22_overlay_alpha"] = alpha
    return True


def improve_lighting(scene):
    if scene.world and scene.world.node_tree:
        background = scene.world.node_tree.nodes.get("Background")
        if background:
            background.inputs["Color"].default_value = (0.115, 0.17, 0.245, 1.0)
            background.inputs["Strength"].default_value = 0.52
    sun = bpy.data.objects.get("V10_Sun")
    if sun and getattr(sun, "data", None):
        sun.data.energy = 3.0
        sun.data.angle = math.radians(3.0)
    area = bpy.data.objects.get("V10_Softbox")
    if area and getattr(area, "data", None):
        area.data.energy = 820.0
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except (AttributeError, TypeError):
        pass


def render_previews(scene):
    specs = [
        (1, "01_regional_overview"),
        (240, "02_first_flood_max"),
        (360, "03_field_structures_dry"),
        (600, "04_field_structures_flooded"),
        (888, "05_shelter_approach"),
        (960, "06_shelter_close"),
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
            raise RuntimeError(f"V22 preview render failed: {path}")
        results.append({"frame": frame, "path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)})
    return results


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    v22 = load_json(V22_CONTEXT_PATH)
    v21 = load_json(V21_CONTEXT_PATH)
    manifest = load_json(MANIFEST_PATH)
    base = load_module("build_osong_visual_v22_base", BASE_SCRIPT)
    scene = bpy.context.scene
    if scene.name != "Osong_Visual_V21":
        raise RuntimeError(f"V22 must start from V21, got {scene.name}")
    if scene.camera is None or scene.camera.name != "Camera_Osong_Shelter_V19":
        raise RuntimeError("Approved V20/V21 camera is missing")

    clear_collection("V22_FIELD_IMAGE_PROXY_STRUCTURES")
    proxy_collection = ensure_collection(scene, "V22_FIELD_IMAGE_PROXY_STRUCTURES")
    sampler = base.TerrainSampler(v21["terrain"])
    terrain = bpy.data.objects.get("Terrain_Osong_FieldRiver_HQ_1500m_V21")
    if terrain is None:
        raise RuntimeError("V21 field terrain is missing")
    z_align = float(terrain.location.z)
    materials = {
        "greenhouse_wall": material(base, "V22_Mat_GreenhouseWall", (0.56, 0.72, 0.73), 0.34, alpha=0.74, transmission=0.18),
        "greenhouse_roof": material(base, "V22_Mat_GreenhouseRoof", (0.82, 0.90, 0.88), 0.27, metallic=0.02, alpha=0.94, transmission=0.08),
        "proxy_wall": material(base, "V22_Mat_ProxyWall", (0.48, 0.46, 0.42), 0.76),
        "proxy_roofs": [
            material(base, "V22_Mat_ProxyRoof_Slate", (0.12, 0.20, 0.25), 0.58, metallic=0.08),
            material(base, "V22_Mat_ProxyRoof_Red", (0.35, 0.10, 0.055), 0.62, metallic=0.03),
            material(base, "V22_Mat_ProxyRoof_Light", (0.46, 0.49, 0.48), 0.66, metallic=0.06),
        ],
    }
    proxies = []
    for item in v22["field_core"]["image_derived_visual_proxies"]:
        obj = create_proxy_structure(item, sampler, z_align, proxy_collection, materials)
        if obj:
            proxies.append(obj)
    shelter_buildings = restyle_shelter_buildings(base)
    shelter_marker = tune_shelter_marker()
    overlay_softened = soften_field_overlay()
    improve_lighting(scene)

    camera_samples = {}
    for frame in (1, 48, 240, 264, 360, 384, 600, 720, 768, 888, 960):
        scene.frame_set(frame)
        camera_samples[str(frame)] = [round(float(value), 4) for value in scene.camera.location]
    scene.name = "Osong_Visual_V22"
    scene["story_version"] = "V22"
    scene["v22_source_v21_preserved"] = True
    scene["v22_image_proxy_count"] = len(proxies)
    scene["v22_greenhouse_proxy_count"] = sum(obj["kind"] == "greenhouse_visual_proxy" for obj in proxies)
    scene["v22_shelter_actual_osm_building_count"] = len(shelter_buildings)
    scene["v22_shelter_marker_reduced"] = bool(shelter_marker)
    scene["v22_camera_preserved"] = True
    scene["v22_video_rendered"] = False
    scene["v22_created_at_utc"] = datetime.now(timezone.utc).isoformat()

    previews = render_previews(scene)
    scene.frame_set(1)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    report = {
        "status": "rendered_pending_visual_review",
        "source_blend": str(SOURCE_BLEND_PATH),
        "source_v21_unchanged": True,
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "blend_sha256": sha256(BLEND_PATH),
        "image_proxy_objects": len(proxies),
        "greenhouse_proxy_objects": sum(obj["kind"] == "greenhouse_visual_proxy" for obj in proxies),
        "other_proxy_objects": sum(obj["kind"] != "greenhouse_visual_proxy" for obj in proxies),
        "shelter_actual_osm_buildings_restyled": len(shelter_buildings),
        "shelter_marker_reduced": bool(shelter_marker),
        "field_overlay_softened": overlay_softened,
        "camera_keyframe_samples": camera_samples,
        "camera_keyframes_preserved": True,
        "previews": previews,
        "video_rendered": False,
        "visual_review": "pending",
        "limitations": v22["limitations"],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["status"] = "blender_scene_built_pending_visual_review"
    manifest["blender_scene"] = {
        "path": str(BLEND_PATH),
        "bytes": BLEND_PATH.stat().st_size,
        "sha256": report["blend_sha256"],
        "source_v21_unchanged": True,
        "camera_keyframes_preserved": True,
        "video_rendered": False,
    }
    manifest["scene_report"] = str(REPORT_PATH)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
