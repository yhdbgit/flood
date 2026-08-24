"""Build and optionally render the 52-second Osong V12 story from V11."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
import time

import bpy
from mathutils import Vector


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
CONTEXT_PATH = ROOT / "data" / "processed" / "osong_hq_v11_context.json"
INUNDATION_PATH = ROOT / "data" / "processed" / "osong_inundation_v12.json"
OUT = ROOT / "output" / "guidance_v12"
BASE_VIDEO = OUT / "osong_story_v12_base.mp4"
BLEND_PATH = ROOT / "blender" / "osong_story_v12_base.blend"
REPORT_PATH = OUT / "base_render_report.json"

FPS = 24
FRAME_END = 1248
FLOOD_STARTS = [1, 337, 577, 913]
RESET_FRAMES = [241, 817]
STEP_FRAMES = 24
CAMERA_KEYS = [
    (1, "overview"), (240, "overview"),
    (241, "overview"), (288, "mid"), (336, "close"),
    (337, "close"), (576, "close"),
    (577, "overview"), (816, "overview"),
    (817, "overview"), (864, "mid"), (912, "close"),
    (913, "close"), (1248, "close"),
]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure_collection(name):
    old = bpy.data.collections.get(name)
    if old:
        for obj in list(old.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(old)
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    return collection


def make_flood_material(base, step):
    progress = step / 10.0
    colour = (
        0.01 + 0.02 * progress,
        0.28 - 0.08 * progress,
        0.62 + 0.16 * progress,
    )
    return base.new_material(
        f"V12_Mat_Inundation_{step:02d}",
        colour,
        roughness=0.20,
        metallic=0.05,
        alpha=0.42 + 0.18 * progress,
    )


def build_flood_objects(base, context, inundation):
    collection = ensure_collection("V12_INUNDATION")
    sampler = base.TerrainSampler(context["terrain"])
    groups = {}
    for item in inundation["progression"]:
        step = int(item["step"])
        material = make_flood_material(base, step)
        objects = []
        for index, polygon in enumerate(item["polygons"]):
            obj = base.polygon_mesh(
                f"InundationV12_S{step:02d}_P{index:02d}",
                polygon["exterior"],
                sampler,
                collection,
                material,
                z_offset=1.05 + step * 0.012,
            )
            if obj:
                obj["progression_step"] = step
                obj["field_affected_percent"] = float(item["field_affected_percent"])
                obj["source_method"] = inundation["method"]["name"]
                objects.append(obj)
        if not objects:
            raise RuntimeError(f"No Blender objects created for inundation step {step}")
        groups[step] = objects
    return collection, groups


def set_group_visibility(groups, frame, visible_step):
    for step, objects in groups.items():
        hidden = step != visible_step
        for obj in objects:
            obj.hide_render = hidden
            obj.hide_viewport = hidden
            obj.keyframe_insert("hide_render", frame=frame)
            obj.keyframe_insert("hide_viewport", frame=frame)


def animate_flood(groups):
    events = []
    for frame in RESET_FRAMES:
        events.append((frame, None))
    for start in FLOOD_STARTS:
        for index in range(10):
            events.append((start + index * STEP_FRAMES, index + 1))
    events.extend([(1153, 10), (1248, 10)])
    for frame, step in sorted(set(events)):
        set_group_visibility(groups, frame, step)
    for objects in groups.values():
        for obj in objects:
            if not obj.animation_data or not obj.animation_data.action:
                continue
            for curve in getattr(obj.animation_data.action, "fcurves", []):
                for point in curve.keyframe_points:
                    point.interpolation = "CONSTANT"
    return sorted(set(events))


def camera_state(camera):
    return {
        "location": Vector(camera.location),
        "rotation": camera.rotation_euler.copy(),
        "lens": float(camera.data.lens),
    }


def midpoint_state(a, b):
    q = a["rotation"].to_quaternion().slerp(b["rotation"].to_quaternion(), 0.5)
    return {
        "location": a["location"].lerp(b["location"], 0.5),
        "rotation": q.to_euler(),
        "lens": (a["lens"] + b["lens"]) / 2.0,
    }


def rebuild_story_camera(scene):
    overview = bpy.data.objects.get("Camera_Osong_HQ_V11_Overview")
    close = bpy.data.objects.get("Camera_Osong_HQ_V11_Field")
    if overview is None or close is None:
        raise RuntimeError("V11 overview/field cameras are missing")
    states = {"overview": camera_state(overview), "close": camera_state(close)}
    states["mid"] = midpoint_state(states["overview"], states["close"])
    data = overview.data.copy()
    data.name = "Camera_Osong_Story_V12_Data"
    data.clip_start = 0.1
    data.clip_end = 100_000.0
    camera = bpy.data.objects.new("Camera_Osong_Story_V12", data)
    bpy.data.collections["V11_LIGHTING"].objects.link(camera)
    for frame, code in CAMERA_KEYS:
        state = states[code]
        camera.location = state["location"]
        camera.rotation_euler = state["rotation"]
        camera.data.lens = state["lens"]
        camera.keyframe_insert("location", frame=frame)
        camera.keyframe_insert("rotation_euler", frame=frame)
        camera.data.keyframe_insert("lens", frame=frame)
    for action_owner in (camera, camera.data):
        if not action_owner.animation_data or not action_owner.animation_data.action:
            continue
        for curve in getattr(action_owner.animation_data.action, "fcurves", []):
            for point in curve.keyframe_points:
                point.interpolation = "BEZIER"
    overview.hide_render = True
    close.hide_render = True
    top = bpy.data.objects.get("Camera_Osong_HQ_V11_Top")
    if top:
        top.hide_render = True
    scene.camera = camera
    return camera, states


def colour_for_progress(progress):
    green = Vector((0.20, 0.68, 0.08))
    red = Vector((0.95, 0.03, 0.01))
    colour = green.lerp(red, progress)
    return (*colour, 0.18 + 0.42 * progress)


def keyframe_material(material, frame, colour):
    shader = material.node_tree.nodes.get("Principled BSDF") if material.node_tree else None
    if shader is None:
        return
    shader.inputs["Base Color"].default_value = colour
    shader.inputs["Base Color"].keyframe_insert("default_value", frame=frame)
    if shader.inputs.get("Alpha"):
        shader.inputs["Alpha"].default_value = colour[3]
        shader.inputs["Alpha"].keyframe_insert("default_value", frame=frame)


def animate_field():
    fill = bpy.data.materials.get("V11_Mat_FieldFill")
    border = bpy.data.materials.get("V11_Mat_FieldBorder")
    if fill is None or border is None:
        raise RuntimeError("V11 farmland materials are missing")
    for material in (fill, border):
        if material.node_tree:
            material.node_tree.animation_data_clear()
    normal_frames = [241, 817]
    for frame in normal_frames:
        keyframe_material(fill, frame, colour_for_progress(0.0))
        keyframe_material(border, frame, (0.95, 0.98, 0.12, 1.0))
    for start in FLOOD_STARTS:
        for index in range(10):
            frame = start + index * STEP_FRAMES
            progress = (index + 1) / 10.0
            keyframe_material(fill, frame, colour_for_progress(progress))
            border_colour = (0.95, 0.98 - 0.80 * progress, 0.12 - 0.10 * progress, 1.0)
            keyframe_material(border, frame, border_colour)
    keyframe_material(fill, 1248, colour_for_progress(1.0))
    keyframe_material(border, 1248, (0.95, 0.18, 0.02, 1.0))
    for material in (fill, border):
        if material.node_tree and material.node_tree.animation_data and material.node_tree.animation_data.action:
            for curve in getattr(material.node_tree.animation_data.action, "fcurves", []):
                for point in curve.keyframe_points:
                    point.interpolation = "LINEAR"


def configure_render(scene):
    scene.name = "Osong_Story_V12_Base"
    scene.frame_start = 1
    scene.frame_end = FRAME_END
    scene.render.fps = FPS
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.filepath = str(BASE_VIDEO)
    scene.render.use_file_extension = True
    try:
        scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
        scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    except (AttributeError, TypeError):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup-only", action="store_true")
    args, _unknown = parser.parse_known_args()
    args.setup_only = "--setup-only" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    context = load_json(CONTEXT_PATH)
    inundation = load_json(INUNDATION_PATH)
    base = load_module("build_v10_geometry_base", ROOT / "blender" / "build_gangnae_hq_v10.py")
    scene = bpy.context.scene
    collection, groups = build_flood_objects(base, context, inundation)
    flood_events = animate_flood(groups)
    camera, states = rebuild_story_camera(scene)
    animate_field()
    configure_render(scene)
    scene["story_version"] = "V12"
    scene["pilot_id"] = inundation["pilot_id"]
    scene["selected_candidate"] = "C19"
    scene["story_timeline"] = "wide flood, dry zoom, close flood, repeated once, final hold"
    scene["flood_progression_steps"] = 10
    scene["flood_playback_speed"] = 0.5
    scene["base_duration_seconds"] = 52.0
    scene["inundation_method"] = inundation["method"]["name"]
    scene["old_gangnae_results_reused"] = False
    scene["v11_source_blend"] = str(ROOT / "blender" / "osong_hq_v11.blend")
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    elapsed = 0.0
    if not args.setup_only:
        started = time.time()
        bpy.ops.render.render(animation=True)
        elapsed = round(time.time() - started, 3)
        if not BASE_VIDEO.is_file() or BASE_VIDEO.stat().st_size < 100_000:
            raise RuntimeError("V12 base MP4 render failed")
        if b"ftyp" not in BASE_VIDEO.read_bytes()[:32]:
            raise RuntimeError("V12 base MP4 container is invalid")

    report = {
        "status": "setup_ok" if args.setup_only else "ok",
        "scene": scene.name,
        "frames": [1, FRAME_END],
        "fps": FPS,
        "duration_seconds": FRAME_END / FPS,
        "camera": camera.name,
        "camera_keyframes": [frame for frame, _ in CAMERA_KEYS],
        "flood_cycle_starts": FLOOD_STARTS,
        "flood_cycle_count": len(FLOOD_STARTS),
        "progression_steps_per_cycle": 10,
        "flood_events": flood_events,
        "inundation_objects": sum(len(items) for items in groups.values()),
        "inundation_collection": collection.name,
        "base_video": str(BASE_VIDEO),
        "base_video_bytes": BASE_VIDEO.stat().st_size if BASE_VIDEO.is_file() else 0,
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "render_elapsed_seconds": elapsed,
        "old_gangnae_results_reused": False,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
