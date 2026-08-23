"""Compose the LangGraph guidance manifest with Blender 5.2 VSE."""

import json
from pathlib import Path

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
MANIFEST_PATH = ROOT / "output" / "guidance_v8" / "guidance_manifest.json"
BLEND_PATH = ROOT / "blender" / "gangnae_guidance_v8.blend"
REPORT_PATH = ROOT / "output" / "guidance_v8" / "composition_report.json"


def add_image(editor, name, path, channel, start, duration):
    strip = editor.strips.new_image(name, str(path), channel, start, fit_method="FIT")
    strip.frame_final_duration = duration
    return strip


def add_repeated_movie(editor, name, path, channel, start, duration):
    strips = []
    current = start
    remaining = duration
    index = 1
    while remaining > 0:
        strip = editor.strips.new_movie(f"{name}_{index}", str(path), channel, current, fit_method="FIT")
        use_duration = min(strip.frame_final_duration, remaining)
        strip.frame_final_duration = use_duration
        strips.append(strip)
        current += use_duration
        remaining -= use_duration
        index += 1
    return strips


def main():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "Gangnae_Guidance_V8"
    width, height = manifest["resolution"]
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    editor = scene.sequence_editor_create()
    visual_strips = []
    audio_strips = []
    overlay_strips = []
    for segment in manifest["segments"]:
        start = segment["start_frame"]
        duration = segment["duration_frames"]
        if segment["visual"] == "slide":
            visual_strips.append(add_image(editor, f"Slide_{segment['id']}", Path(segment["visual_path"]), 1, start, duration))
        else:
            visual_strips.extend(add_repeated_movie(editor, "DigitalTwin", Path(segment["visual_path"]), 1, start, duration))
            overlay_strips.append(add_image(editor, "DigitalTwinOverlay", Path(segment["overlay_path"]), 2, start, duration))
        audio_strips.append(editor.strips.new_sound(f"TTS_{segment['id']}", segment["audio_path"], 4, start))

    scene.render.fps = manifest["fps"]
    scene.frame_start = manifest["frame_start"]
    scene.frame_end = manifest["frame_end"]
    scene.render.use_sequencer = True
    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.audio_codec = "AAC"
    scene.render.ffmpeg.audio_bitrate = 192
    scene.render.filepath = manifest["output_video"]
    scene.render.use_file_extension = True
    try:
        scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
        scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    except (AttributeError, TypeError):
        pass
    scene["guidance_run_id"] = manifest["run_id"]
    scene["guidance_mode"] = manifest["mode"]
    scene["guidance_disclaimer"] = manifest["disclaimer"]
    scene["guidance_manifest"] = str(MANIFEST_PATH)
    scene["ai_voice_disclosure"] = manifest.get("ai_voice_disclosure", "")
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    bpy.ops.render.render(animation=True)

    video = Path(manifest["output_video"])
    if not video.is_file() or video.stat().st_size < 100_000 or b"ftyp" not in video.read_bytes()[:32]:
        raise RuntimeError("V8 MP4 render failed")
    report = {
        "status": "ok",
        "scene": scene.name,
        "visual_strip_count": len(visual_strips),
        "overlay_strip_count": len(overlay_strips),
        "audio_strip_count": len(audio_strips),
        "frames": [scene.frame_start, scene.frame_end],
        "fps": scene.render.fps,
        "duration_seconds": manifest["duration_seconds"],
        "video_path": str(video),
        "video_bytes": video.stat().st_size,
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[guidance-v8] composition complete")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
