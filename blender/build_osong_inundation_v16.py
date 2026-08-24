"""Build the refined terrain-conforming V16 inundation scene and previews."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
DATA_PATH = ROOT / "data" / "processed" / "osong_inundation_mesh_v16.json"
SOURCE_BLEND_PATH = ROOT / "blender" / "osong_story_v15_water.blend"
BLEND_PATH = ROOT / "blender" / "osong_inundation_v16.blend"
OUT = ROOT / "output" / "inundation_v16"
REPORT_PATH = OUT / "scene_report.json"
PREVIEW_FRAME = 481


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def remove_collection(name: str):
    collection = bpy.data.collections.get(name)
    removed = []
    if collection:
        for obj in list(collection.all_objects):
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(collection)
    return removed


def material(base, name, colour, alpha, roughness=0.22):
    result = base.new_material(name, colour, roughness=roughness, metallic=0.03, alpha=alpha)
    result.diffuse_color = (*colour, alpha)
    shader = result.node_tree.nodes.get("Principled BSDF") if result.node_tree else None
    if shader and shader.inputs.get("Coat Weight"):
        shader.inputs["Coat Weight"].default_value = 0.16
    return result


def mesh_object(name, mesh_data, collection, mat, properties):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(mesh_data["vertices"], [], mesh_data["faces"])
    mesh.validate(verbose=True)
    mesh.update(calc_edges=True)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.data.materials.append(mat)
    for key, value in properties.items():
        obj[key] = value
    return obj


def create_stage_objects(base, dataset):
    removed = remove_collection("V14_OFFICIAL_INUNDATION")
    remove_collection("V16_INUNDATION_STAGES")
    collection = bpy.data.collections.new("V16_INUNDATION_STAGES")
    bpy.context.scene.collection.children.link(collection)
    flood_materials = {
        "intermediate": material(base, "V16_Mat_Flood_Intermediate", (0.02, 0.32, 0.68), 0.44),
        "maximum": material(base, "V16_Mat_Flood_Maximum", (0.008, 0.16, 0.54), 0.58),
    }
    impact_materials = {
        "intermediate": material(base, "V16_Mat_FieldImpact_Intermediate", (1.0, 0.30, 0.01), 0.80, 0.30),
        "maximum": material(base, "V16_Mat_FieldImpact_Maximum", (0.92, 0.015, 0.005), 0.88, 0.30),
    }
    groups = {"normal": []}
    counts = {}
    for stage in dataset["stages"]:
        code = stage["code"]
        if code == "normal":
            counts[code] = {"flood_faces": 0, "impact_faces": 0}
            continue
        props = {
            "stage_code": code,
            "stage_label": stage["label"],
            "official_extent_fraction": float(stage["official_extent_fraction"]),
            "field_affected_percent": float(stage["field_affected_percent"]),
            "hydraulic_time_series": False,
            "realtime_applied": False,
        }
        flood = mesh_object(
            f"InundationV16_{code}_TerrainConforming",
            stage["flood_mesh"],
            collection,
            flood_materials[code],
            {**props, "visual_role": "official_flood_extent"},
        )
        impact = mesh_object(
            f"FieldImpactV16_{code}",
            stage["field_impact_mesh"],
            collection,
            impact_materials[code],
            {**props, "visual_role": "field_intersection_only"},
        )
        groups[code] = [flood, impact]
        counts[code] = {
            "flood_faces": len(flood.data.polygons),
            "impact_faces": len(impact.data.polygons),
        }
    return collection, groups, counts, removed


def set_stage(groups, visible_code):
    for code, objects in groups.items():
        hidden = code != visible_code
        for obj in objects:
            obj.hide_render = hidden
            obj.hide_viewport = hidden


def normalise_field_materials():
    colours = {
        "V10_Mat_FieldFill": (0.20, 0.68, 0.08, 0.20),
        "V10_Mat_FieldBorder": (0.95, 0.98, 0.12, 1.0),
    }
    for name, colour in colours.items():
        mat = bpy.data.materials.get(name)
        if mat is None:
            raise RuntimeError(f"Farmland material is missing: {name}")
        if mat.node_tree:
            mat.node_tree.animation_data_clear()
        mat.diffuse_color = colour
        shader = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
        if shader and shader.inputs.get("Base Color"):
            shader.inputs["Base Color"].default_value = colour
        if shader and shader.inputs.get("Alpha"):
            shader.inputs["Alpha"].default_value = colour[3]


def configure_render(scene):
    scene.frame_set(PREVIEW_FRAME)
    camera = bpy.data.objects.get("Camera_Osong_Story_V14")
    if camera is None:
        raise RuntimeError("V14 story camera is missing")
    camera.data.clip_start = 0.1
    camera.data.clip_end = 100_000.0
    scene.camera = camera
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"


def render_previews(scene, groups, dataset):
    outputs = []
    for stage in dataset["stages"]:
        code = stage["code"]
        set_stage(groups, code)
        path = OUT / f"{code}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        if not path.is_file() or path.stat().st_size < 10_000:
            raise RuntimeError(f"Preview render failed: {path}")
        outputs.append({
            "stage": code,
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "field_affected_percent": float(stage["field_affected_percent"]),
        })
    return outputs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dataset = load_json(DATA_PATH)
    base = load_module("build_v16_refined_base", ROOT / "blender" / "build_gangnae_hq_v10.py")
    scene = bpy.context.scene
    collection, groups, counts, removed = create_stage_objects(base, dataset)
    normalise_field_materials()
    configure_render(scene)
    previews = render_previews(scene, groups, dataset)
    set_stage(groups, "normal")
    scene["story_version"] = "V16"
    scene["inundation_dataset"] = dataset["dataset_id"]
    scene["inundation_surface_method"] = dataset["terrain_surface_method"]
    scene["inundation_stage_codes"] = [stage["code"] for stage in dataset["stages"]]
    scene["official_final_extent"] = True
    scene["hydraulic_time_series"] = False
    scene["realtime_stage_applied"] = False
    scene["field_maximum_affected_percent"] = float(dataset["stages"][-1]["field_affected_percent"])
    scene["video_rendered"] = False
    scene["v16_created_at_utc"] = datetime.now(timezone.utc).isoformat()
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    report = {
        "status": "rendered_pending_visual_review",
        "source_blend": str(SOURCE_BLEND_PATH),
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "blend_sha256": sha256(BLEND_PATH),
        "removed_v14_inundation_objects": len(removed),
        "collection": collection.name,
        "mesh_counts": counts,
        "previews": previews,
        "field_highlight": "intersection only",
        "realtime_applied": False,
        "video_rendered": False,
        "visual_review": "pending",
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
