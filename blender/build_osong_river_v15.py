"""Replace the V14 draped water with a continuous V15 sloped surface and terrain mask."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.geometry import tessellate_polygon


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
DATA_PATH = ROOT / "data" / "processed" / "osong_river_surface_v15.json"
BLEND_PATH = ROOT / "blender" / "osong_story_v15_water.blend"
OUT = ROOT / "output" / "river_v15"
REPORT_PATH = OUT / "scene_report.json"
PREVIEW_FRAMES = {"overview_dry": 481, "close_dry": 576}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def remove_old_water():
    removed = []
    collection = bpy.data.collections.get("V14_WATER")
    if collection:
        for obj in list(collection.objects):
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(collection)
    return removed


def apply_adjustments(obj_name: str, changes):
    obj = bpy.data.objects.get(obj_name)
    if obj is None or obj.type != "MESH":
        raise RuntimeError(f"Terrain object is missing: {obj_name}")
    for index, target_local_z in changes:
        vertex = obj.data.vertices[int(index)]
        vertex.co.z = float(target_local_z)
    obj.data.update(calc_edges=True)
    return obj


def water_material(base):
    material = base.new_material(
        "V15_Mat_ContinuousRiver",
        (0.008, 0.12, 0.20),
        roughness=0.20,
        metallic=0.03,
        alpha=1.0,
    )
    # The satellite terrain below the channel is intentionally masked. A
    # translucent surface makes that hidden terrain read as disconnected dry
    # patches, even when the water mesh itself is continuous.
    material.diffuse_color = (0.01, 0.22, 0.34, 1.0)
    shader = material.node_tree.nodes.get("Principled BSDF") if material.node_tree else None
    if shader:
        if shader.inputs.get("Coat Weight"):
            shader.inputs["Coat Weight"].default_value = 0.28
        if shader.inputs.get("Coat Roughness"):
            shader.inputs["Coat Roughness"].default_value = 0.10
    return material


def create_surface(data: dict, base):
    old = bpy.data.collections.get("V15_WATER_SURFACE")
    if old:
        for obj in list(old.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(old)
    collection = bpy.data.collections.new("V15_WATER_SURFACE")
    bpy.context.scene.collection.children.link(collection)
    vertices = [tuple(map(float, item)) for item in data["water_surface"]["vertices_xyz"]]
    vectors = [Vector((x, y)) for x, y, _z in vertices]
    index_map = {(round(v.x, 6), round(v.y, 6)): i for i, v in enumerate(vectors)}
    faces = []
    for triangle in tessellate_polygon([vectors]):
        if triangle and isinstance(triangle[0], int):
            face = list(triangle)
        else:
            face = [index_map[(round(v.x, 6), round(v.y, 6))] for v in triangle]
        if len(set(face)) == 3:
            faces.append(face)
    if not faces:
        raise RuntimeError("Continuous river triangulation produced no faces")
    mesh = bpy.data.meshes.new("V15_ContinuousRiver_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(verbose=True)
    mesh.update(calc_edges=True)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    obj = bpy.data.objects.new("RiverSurface_Osong_V15_Continuous", mesh)
    collection.objects.link(obj)
    obj.data.materials.append(water_material(base))
    obj["dataset_id"] = data["dataset_id"]
    obj["source_provider"] = data["source_geometry"]["provider"]
    obj["surface_method"] = data["surface_model"]["method"]
    obj["realtime_applied"] = False
    obj["hydraulic_model"] = False
    return obj, len(faces)


def render_previews(scene):
    outputs = []
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    for name, frame in PREVIEW_FRAMES.items():
        scene.frame_set(frame)
        path = OUT / f"{name}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        if not path.is_file() or path.stat().st_size < 10_000:
            raise RuntimeError(f"Preview render failed: {path}")
        outputs.append({
            "name": name,
            "frame": frame,
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    return outputs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = load_json(DATA_PATH)
    base = load_module("build_v15_material_base", ROOT / "blender" / "build_gangnae_hq_v10.py")
    scene = bpy.context.scene
    removed = remove_old_water()
    outer = apply_adjustments(
        data["terrain_mask"]["outer_object"],
        data["terrain_mask"]["outer_adjustments"],
    )
    core = apply_adjustments(
        data["terrain_mask"]["core_object"],
        data["terrain_mask"]["core_adjustments"],
    )
    water, face_count = create_surface(data, base)
    scene["water_quality_version"] = "V15"
    scene["water_surface_dataset"] = data["dataset_id"]
    scene["water_surface_continuous"] = True
    scene["terrain_mask_applied"] = True
    scene["water_realtime_applied"] = False
    scene["water_video_rendered"] = False
    scene["v14_base_story_preserved"] = True
    scene["v15_created_at_utc"] = datetime.now(timezone.utc).isoformat()
    scene.frame_set(481)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    previews = render_previews(scene)
    report = {
        "status": "rendered_pending_visual_review",
        "scene": scene.name,
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "blend_sha256": sha256(BLEND_PATH),
        "source_blend": str(ROOT / "blender" / "osong_story_v14_base.blend"),
        "old_water_objects_removed": removed,
        "continuous_water_object": water.name,
        "continuous_water_faces": face_count,
        "outer_terrain_vertices_adjusted": len(data["terrain_mask"]["outer_adjustments"]),
        "core_terrain_vertices_adjusted": len(data["terrain_mask"]["core_adjustments"]),
        "terrain_objects": [outer.name, core.name],
        "previews": previews,
        "video_rendered": False,
        "visual_review": "pending",
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
