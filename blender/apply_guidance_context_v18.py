"""Apply a ready V18 guidance context to the reusable V16 Blender scene."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
CONTEXT_PATH = ROOT / "data" / "runtime" / "guidance_context_v18.json"
SOURCE_BLEND_PATH = ROOT / "blender" / "osong_inundation_v16.blend"
BLEND_PATH = ROOT / "blender" / "osong_guidance_v18.blend"
OUT = ROOT / "output" / "guidance_v18_preview"
REPORT_PATH = OUT / "scene_report.json"
ANNOTATION_COLLECTION = "V18_GUIDANCE_ANNOTATIONS"
FONT_PATH = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_policy():
    path = ROOT / "scripts" / "v18_scene_policy.py"
    spec = importlib.util.spec_from_file_location("v18_scene_policy", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import scene policy: {path}")
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
    if collection is None:
        return
    for obj in list(collection.all_objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(collection)


def stage_objects():
    return [
        obj for obj in bpy.data.objects
        if obj.name.startswith("InundationV16_") or obj.name.startswith("FieldImpactV16_")
    ]


def apply_stage(selected_stage: str):
    visible = []
    objects = stage_objects()
    for obj in objects:
        hidden = obj.get("stage_code") != selected_stage
        obj.hide_viewport = hidden
        obj.hide_render = hidden
        if not hidden:
            visible.append(obj.name)
    return objects, visible


def annotation_material():
    name = "V18_Mat_Annotation_Dark"
    existing = bpy.data.materials.get(name)
    if existing:
        return existing
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.diffuse_color = (0.008, 0.018, 0.045, 1.0)
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader:
        if shader.inputs.get("Base Color"):
            shader.inputs["Base Color"].default_value = (0.008, 0.018, 0.045, 1.0)
        if shader.inputs.get("Roughness"):
            shader.inputs["Roughness"].default_value = 0.35
        if shader.inputs.get("Emission Color"):
            shader.inputs["Emission Color"].default_value = (0.008, 0.018, 0.045, 1.0)
        if shader.inputs.get("Emission Strength"):
            shader.inputs["Emission Strength"].default_value = 0.0
    return material


def load_korean_font():
    if not FONT_PATH.is_file():
        return None
    existing = bpy.data.fonts.get(FONT_PATH.name)
    return existing or bpy.data.fonts.load(str(FONT_PATH))


def create_annotation_objects(camera):
    remove_collection(ANNOTATION_COLLECTION)
    collection = bpy.data.collections.new(ANNOTATION_COLLECTION)
    bpy.context.scene.collection.children.link(collection)
    font = load_korean_font()
    material = annotation_material()
    layout = [
        ("V18_Title", (-0.30, 0.19, -1.25), 0.050),
        ("V18_Forecast", (-0.30, 0.11, -1.25), 0.028),
        ("V18_Reference", (-0.30, 0.03, -1.25), 0.028),
        ("V18_Impact", (-0.30, -0.05, -1.25), 0.028),
    ]
    result = {}
    for name, location, size in layout:
        curve = bpy.data.curves.new(f"{name}_Curve", type="FONT")
        curve.body = name
        curve.align_x = "LEFT"
        curve.align_y = "CENTER"
        curve.size = size
        curve.extrude = 0.001
        curve.bevel_depth = 0.0003
        if font:
            curve.font = font
        curve.materials.append(material)
        obj = bpy.data.objects.new(name, curve)
        collection.objects.link(obj)
        obj.parent = camera
        obj.location = location
        obj.rotation_euler = (0.0, 0.0, 0.0)
        obj["visual_role"] = "camera_space_guidance_annotation"
        result[name] = obj
    return collection, result


def reparent_annotations(objects, camera):
    for obj in objects.values():
        obj.parent = camera
        # Object coordinates intentionally remain camera-local.


def set_annotation_text(objects, spec):
    objects["V18_Title"].data.body = spec["title"]
    objects["V18_Forecast"].data.body = spec["forecast_line"]
    objects["V18_Reference"].data.body = spec["reference_line"]
    objects["V18_Impact"].data.body = spec["impact_line"]


def configure_render(scene):
    scene.frame_set(481)
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False


def render_previews(scene, specs, annotations):
    outputs = []
    all_stage_objects = stage_objects()
    for spec in specs:
        camera = bpy.data.objects.get(spec["camera"])
        if camera is None or camera.type != "CAMERA":
            raise RuntimeError(f"V18 camera is missing: {spec['camera']}")
        camera.data.clip_start = 0.1
        camera.data.clip_end = 100_000.0
        if camera.name == "Camera_Osong_Context_V14_Field":
            camera.data.lens = 42.0
        scene.camera = camera
        reparent_annotations(annotations, camera)
        set_annotation_text(annotations, spec)
        for annotation in annotations.values():
            annotation.hide_render = True
        _, visible = apply_stage(spec["stage"])
        path = OUT / f"{spec['code']}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        if not path.is_file() or path.stat().st_size < 10_000:
            raise RuntimeError(f"V18 preview render failed: {path}")
        outputs.append({
            "code": spec["code"],
            "stage": spec["stage"],
            "camera": camera.name,
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "visible_stage_objects": visible,
        })
    return all_stage_objects, outputs


def main():
    if not CONTEXT_PATH.is_file():
        raise RuntimeError(f"V18 guidance context is missing: {CONTEXT_PATH}")
    OUT.mkdir(parents=True, exist_ok=True)
    context = load_json(CONTEXT_PATH)
    policy = load_policy()
    specs = policy.build_preview_specs(context)
    summary = policy.scene_summary(context)
    scene = bpy.context.scene
    configure_render(scene)
    initial_camera = bpy.data.objects.get(specs[0]["camera"])
    if initial_camera is None:
        raise RuntimeError("V18 overview camera is missing")
    collection, annotations = create_annotation_objects(initial_camera)
    objects, previews = render_previews(scene, specs, annotations)

    final_spec = specs[-1]
    final_camera = bpy.data.objects.get(final_spec["camera"])
    scene.camera = final_camera
    reparent_annotations(annotations, final_camera)
    set_annotation_text(annotations, final_spec)
    for annotation in annotations.values():
        annotation.hide_render = True
    apply_stage(final_spec["stage"])
    scene["story_version"] = "V18"
    scene["guidance_context_id"] = context["context_id"]
    scene["guidance_context_source_mode"] = context["forecast"]["source"].get("mode", "unknown")
    scene["guidance_target_date"] = context["trigger"].get("target_date", "")
    scene["guidance_rain_24h_mm"] = float(context["trigger"]["rain_condition"]["value_mm"])
    scene["guidance_field_affected_percent"] = float(context["inundation"]["field_affected_percent"])
    scene["visual_reference_claim"] = summary["visual_reference_claim"]
    scene["hydraulic_event_forecast"] = False
    scene["guidance_text_composited_downstream"] = True
    scene["video_rendered"] = False
    scene["v18_created_at_utc"] = datetime.now(timezone.utc).isoformat()
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    report = {
        "status": "rendered_pending_automated_visual_review",
        "source_blend": str(SOURCE_BLEND_PATH),
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "blend_sha256": sha256(BLEND_PATH),
        "context_path": str(CONTEXT_PATH),
        "context_sha256": sha256(CONTEXT_PATH),
        **summary,
        "stage_object_count": len(objects),
        "annotation_collection": collection.name,
        "annotation_objects": sorted(annotations),
        "rendered_previews": previews,
        "video_rendered": False,
        "visual_review": "pending",
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
