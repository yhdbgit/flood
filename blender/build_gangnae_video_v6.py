"""Add camera HUD and Blender-native MP4 settings to V5, then save V6."""

import json
from pathlib import Path
import sys

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
sys.path.insert(0, str(ROOT / "blender"))
import build_gangnae_hydro_v3 as hydro_v3


CONFIG_PATH = ROOT / "config" / "video_v6.json"
FIELD_RESULT_PATH = ROOT / "output" / "inundation_v5_field_result.json"
BLEND_PATH = ROOT / "blender" / "gangnae_video_v6.blend"
POSTER_PATH = ROOT / "output" / "gangnae_flood_mvp_v6_poster.png"
VIDEO_PATH = ROOT / "output" / "gangnae_flood_mvp_v6.mp4"
REPORT_PATH = ROOT / "output" / "video_v6_setup_report.json"
COLLECTION_NAME = "DT_VIDEO_V6"
FONT_PATH = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def prepare_collection(scene):
    old = bpy.data.collections.get(COLLECTION_NAME)
    if old is not None:
        for obj in list(old.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for parent in list(bpy.data.collections):
            if old.name in parent.children:
                parent.children.unlink(old)
        if old.name in scene.collection.children:
            scene.collection.children.unlink(old)
        bpy.data.collections.remove(old)
    collection = bpy.data.collections.new(COLLECTION_NAME)
    scene.collection.children.link(collection)
    return collection


def load_font():
    if not FONT_PATH.is_file():
        return None
    for font in bpy.data.fonts:
        if Path(font.filepath).name == FONT_PATH.name:
            return font
    return bpy.data.fonts.load(str(FONT_PATH))


def create_hud_material(name, colour, alpha=1.0, emission=0.4):
    return hydro_v3.material(name, colour, roughness=0.6, alpha=alpha, emission=emission)


def create_panel(name, camera, collection, width, height, y, material):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    half_width = width / 2.0
    half_height = height / 2.0
    mesh.from_pydata(
        [
            (-half_width, -half_height, 0.0),
            (half_width, -half_height, 0.0),
            (half_width, half_height, 0.0),
            (-half_width, half_height, 0.0),
        ],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.parent = camera
    obj.location = (0.0, y, -10.15)
    obj.data.materials.append(material)
    obj["video_overlay"] = True
    return obj


def create_hud_text(name, body, camera, collection, location, size, material, font, align="LEFT"):
    curve = bpy.data.curves.new(f"{name}_Curve", type="FONT")
    curve.body = body
    curve.align_x = align
    curve.align_y = "CENTER"
    curve.size = size
    curve.extrude = 0.003
    curve.bevel_depth = 0.001
    if font is not None:
        curve.font = font
    obj = bpy.data.objects.new(name, curve)
    collection.objects.link(obj)
    obj.parent = camera
    obj.location = location
    obj.data.materials.append(material)
    obj["video_overlay"] = True
    return obj


def animate_exclusive_visibility(obj, start, end, frame_start, frame_end):
    points = [(frame_start, start != frame_start)]
    if start > frame_start:
        points.append((start - 1, True))
    points.append((start, False))
    points.append((end, False))
    if end < frame_end:
        points.append((end + 1, True))
        points.append((frame_end, True))
    for frame, hidden in points:
        obj.hide_render = hidden
        obj.hide_viewport = hidden
        obj.keyframe_insert("hide_render", frame=frame)
        obj.keyframe_insert("hide_viewport", frame=frame)


def status_texts(field_results):
    warning = field_results["scenario_results"]["warning"]
    serious = field_results["scenario_results"]["serious"]
    return {
        "normal": "정상 · 등록 농경지 침수 없음",
        "attention": "관심 · 하천 주변 저지대 침수 시작",
        "warning": f"경계 · 등록 농경지 {warning['inundated_percent']:.1f}% 영향",
        "serious": f"심각 · 등록 농경지 {serious['inundated_percent']:.1f}% 영향",
    }


def configure_render(scene, config):
    width, height = config["resolution"]
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.fps = config["fps"]
    scene.frame_start = config["frame_start"]
    scene.frame_end = config["frame_end"]
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.filepath = str(VIDEO_PATH)
    scene.render.use_file_extension = True
    scene.render.film_transparent = False
    try:
        scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
        scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    except (AttributeError, TypeError):
        pass
    if scene.render.engine == "BLENDER_EEVEE_NEXT":
        scene.render.image_settings.color_depth = "8"


def render_poster(scene, frame):
    previous_media_type = scene.render.image_settings.media_type
    previous_format = scene.render.image_settings.file_format
    previous_path = scene.render.filepath
    scene.frame_set(frame)
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(POSTER_PATH)
    bpy.ops.render.render(write_still=True)
    scene.render.image_settings.media_type = previous_media_type
    scene.render.image_settings.file_format = previous_format
    scene.render.image_settings.color_mode = "RGB"
    scene.render.filepath = previous_path
    if not POSTER_PATH.is_file() or POSTER_PATH.stat().st_size == 0:
        raise RuntimeError("V6 poster render failed")


def main():
    scene = bpy.context.scene
    scene.name = "Gangnae_Video_V6"
    config = load_json(CONFIG_PATH)
    field_results = load_json(FIELD_RESULT_PATH)
    collection = prepare_collection(scene)
    camera = bpy.data.objects.get("Camera_Gangnae_Hydro_V3")
    if camera is None:
        raise RuntimeError("V5 main camera is missing")
    scene.camera = camera
    font = load_font()

    panel_material = create_hud_material("Material_V6_HUD_Panel", (0.008, 0.012, 0.02), alpha=0.62, emission=0.02)
    white_material = create_hud_material("Material_V6_HUD_White", (1.0, 1.0, 1.0), emission=0.65)
    muted_material = create_hud_material("Material_V6_HUD_Muted", (0.78, 0.84, 0.90), emission=0.45)
    create_panel("HUD_TitlePanel_V6", camera, collection, 6.05, 0.52, 1.55, panel_material)
    create_panel("HUD_StatusPanel_V6", camera, collection, 6.05, 0.66, -1.48, panel_material)
    create_hud_text(
        "HUD_Title_V6",
        config["title"],
        camera,
        collection,
        (-2.82, 1.55, -10.0),
        0.25,
        white_material,
        font,
    )
    create_hud_text(
        "HUD_Disclaimer_V6",
        config["disclaimer"],
        camera,
        collection,
        (-2.82, -1.68, -10.0),
        0.135,
        muted_material,
        font,
    )

    labels = status_texts(field_results)
    status_objects = {}
    for segment in config["status_segments"]:
        code = segment["code"]
        material = create_hud_material(
            f"Material_V6_Status_{code}", tuple(segment["colour"]), emission=0.72
        )
        obj = create_hud_text(
            f"HUD_Status_{code}_V6",
            labels[code],
            camera,
            collection,
            (-2.82, -1.37, -10.0),
            0.23,
            material,
            font,
        )
        animate_exclusive_visibility(
            obj,
            segment["start"],
            segment["end"],
            config["frame_start"],
            config["frame_end"],
        )
        status_objects[code] = obj

    configure_render(scene, config)
    scene["video_id"] = config["video_id"]
    scene["video_accuracy"] = config["accuracy"]
    scene["video_disclaimer"] = config["disclaimer"]
    scene["video_output_path"] = str(VIDEO_PATH)
    render_poster(scene, 100)
    scene.frame_set(config["frame_start"])
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    report = {
        "status": "ok",
        "scene": scene.name,
        "video_id": config["video_id"],
        "resolution": config["resolution"],
        "fps": config["fps"],
        "frames": [config["frame_start"], config["frame_end"]],
        "duration_seconds": round((config["frame_end"] - config["frame_start"] + 1) / config["fps"], 3),
        "status_overlays": list(status_objects),
        "poster": {"path": str(POSTER_PATH), "bytes": POSTER_PATH.stat().st_size},
        "video_path": str(VIDEO_PATH),
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "accuracy": config["accuracy"],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[video-v6] setup complete")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
