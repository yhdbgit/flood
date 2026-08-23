"""Build and render the 52-second V9 digital-twin story base from the V5 scene."""

import json
from pathlib import Path
import sys
import time

import bpy

ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
sys.path.insert(0, str(ROOT / "blender"))
import build_gangnae_farmland_v4 as farmland_v4

OUT = ROOT / "output" / "guidance_v9"
BASE_VIDEO = OUT / "gangnae_story_v9_base.mp4"
BLEND_PATH = ROOT / "blender" / "gangnae_story_v9_base.blend"
REPORT_PATH = OUT / "base_render_report.json"
FPS = 24
FRAME_END = 1248

CAMERA_KEYS = [
    (1, "overview"), (240, "overview"),
    (241, "overview"), (288, "mid"), (336, "close"),
    (337, "close"), (576, "close"),
    (577, "overview"), (816, "overview"),
    (817, "overview"), (864, "mid"), (912, "close"),
    (913, "close"), (1248, "close"),
]

# Original V6 flood progression is stretched from 5 seconds to 10 seconds.
STATE_EVENTS = [
    (1, "normal"), (59, "attention"), (129, "warning"), (199, "serious"), (240, "serious"),
    (241, "normal"), (336, "normal"),
    (337, "normal"), (395, "attention"), (465, "warning"), (535, "serious"), (576, "serious"),
    (577, "normal"), (635, "attention"), (705, "warning"), (775, "serious"), (816, "serious"),
    (817, "normal"), (912, "normal"),
    (913, "normal"), (971, "attention"), (1041, "warning"), (1111, "serious"), (1152, "serious"),
    (1153, "serious"), (1248, "serious"),
]


def camera_snapshot(scene, camera, frame):
    scene.frame_set(frame)
    return {
        "location": tuple(camera.location),
        "rotation": tuple(camera.rotation_euler),
    }


def apply_camera_state(camera, frame, state):
    camera.location = state["location"]
    camera.rotation_euler = state["rotation"]
    camera.keyframe_insert("location", frame=frame)
    camera.keyframe_insert("rotation_euler", frame=frame)


def rebuild_camera(scene):
    camera = bpy.data.objects.get("Camera_Gangnae_Hydro_V3")
    if camera is None:
        raise RuntimeError("main camera is missing")
    states = {
        "overview": camera_snapshot(scene, camera, 1),
        "mid": camera_snapshot(scene, camera, 65),
        "close": camera_snapshot(scene, camera, 120),
    }
    camera.animation_data_clear()
    for frame, code in CAMERA_KEYS:
        apply_camera_state(camera, frame, states[code])
    scene.camera = camera
    return camera, states


def rebuild_inundation_visibility():
    objects = {
        code: bpy.data.objects.get(f"Inundation_{code}")
        for code in ("attention", "warning", "serious")
    }
    if any(obj is None for obj in objects.values()):
        raise RuntimeError(f"inundation objects are missing: {objects}")
    for obj in objects.values():
        obj.animation_data_clear()
    for frame, state in STATE_EVENTS:
        for code, obj in objects.items():
            hidden = code != state
            obj.hide_render = hidden
            obj.hide_viewport = hidden
            obj.keyframe_insert("hide_render", frame=frame)
            obj.keyframe_insert("hide_viewport", frame=frame)
    return objects


def material_keyframes(border=False):
    colours = {
        "normal": ((0.72, 1.0, 0.12), 0.18, 1.0) if border else ((0.20, 0.68, 0.08), 0.04, 0.60),
        "attention": ((0.72, 1.0, 0.12), 0.18, 1.0) if border else ((0.20, 0.68, 0.08), 0.04, 0.60),
        "warning": ((1.0, 0.48, 0.01), 0.30, 1.0) if border else ((1.0, 0.48, 0.01), 0.16, 0.70),
        "serious": ((0.95, 0.01, 0.005), 0.72, 1.0) if border else ((0.95, 0.01, 0.005), 0.48, 0.86),
    }
    return [(frame, *colours[state]) for frame, state in STATE_EVENTS]


def rebuild_field_materials():
    fill = bpy.data.materials.get("Material_V4_FieldFill")
    border = bpy.data.materials.get("Material_V4_FieldBorder")
    if fill is None or border is None:
        raise RuntimeError("field materials are missing")
    for material in (fill, border):
        material.animation_data_clear()
        if material.node_tree:
            material.node_tree.animation_data_clear()
    farmland_v4.animate_material(fill, material_keyframes(False))
    farmland_v4.animate_material(border, material_keyframes(True))
    return fill, border


def configure_render(scene):
    scene.name = "Gangnae_Story_V9_Base"
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
    OUT.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    camera, camera_states = rebuild_camera(scene)
    flood_objects = rebuild_inundation_visibility()
    rebuild_field_materials()
    configure_render(scene)
    scene["story_version"] = "V9"
    scene["story_timeline"] = "wide-flood, reset-zoom, close-flood x2, freeze"
    scene["flood_speed_factor"] = 0.5
    scene["base_duration_seconds"] = 52.0
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    started = time.time()
    bpy.ops.render.render(animation=True)
    elapsed = round(time.time() - started, 3)
    if not BASE_VIDEO.is_file() or BASE_VIDEO.stat().st_size < 100_000 or b"ftyp" not in BASE_VIDEO.read_bytes()[:32]:
        raise RuntimeError("V9 base MP4 render failed")
    report = {
        "status": "ok",
        "scene": scene.name,
        "frames": [1, FRAME_END],
        "fps": FPS,
        "duration_seconds": FRAME_END / FPS,
        "flood_playback_speed": 0.5,
        "camera_keyframes": [frame for frame, _ in CAMERA_KEYS],
        "state_events": STATE_EVENTS,
        "flood_objects": list(flood_objects),
        "base_video": str(BASE_VIDEO),
        "base_video_bytes": BASE_VIDEO.stat().st_size,
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "render_elapsed_seconds": elapsed,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[story-v9] base render complete")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
