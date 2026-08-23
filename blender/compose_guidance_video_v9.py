"""Compose the V9 60-second story, overlays, final card, and TTS in Blender VSE."""

import json
from pathlib import Path
import bpy

ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
OUT = ROOT / "output" / "guidance_v9"
MANIFEST_PATH = OUT / "guidance_manifest.json"
BLEND_PATH = ROOT / "blender" / "gangnae_guidance_v9.blend"
REPORT_PATH = OUT / "composition_report.json"


def add_image(editor, name, path, channel, start, duration, alpha=False):
    strip = editor.strips.new_image(name, str(path), channel, start, fit_method="FIT")
    strip.frame_final_duration = duration
    if alpha:
        strip.blend_type = "ALPHA_OVER"
    return strip


def main():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "Gangnae_Guidance_V9"
    scene.render.resolution_x, scene.render.resolution_y = manifest["resolution"]
    scene.render.resolution_percentage = 100
    scene.render.fps = manifest["fps"]
    scene.frame_start = 1
    scene.frame_end = manifest["frame_end"]
    editor = scene.sequence_editor_create()
    base = editor.strips.new_movie("DigitalTwinStoryBase", manifest["base_video"], 1, 1, fit_method="FIT")
    base.frame_final_duration = manifest["base_frame_end"]
    image_strips = []
    sound_strips = []
    for segment in manifest["segments"]:
        duration = segment["end_frame"] - segment["start_frame"] + 1
        image_strips.append(add_image(
            editor,
            f"Visual_{segment['id']}",
            Path(segment["visual_path"]),
            2,
            segment["start_frame"],
            duration,
            alpha=segment["visual_type"] == "overlay",
        ))
        sound_strips.append(editor.strips.new_sound(
            f"TTS_{segment['id']}", segment["audio_path"], 4, segment["start_frame"]
        ))
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
    scene["story_version"] = "V9"
    scene["flood_playback_speed"] = 0.5
    scene["ai_voice_disclosure"] = manifest["ai_voice_disclosure"]
    scene["guidance_manifest"] = str(MANIFEST_PATH)
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    bpy.ops.render.render(animation=True)
    video = Path(manifest["output_video"])
    if not video.is_file() or video.stat().st_size < 100_000 or b"ftyp" not in video.read_bytes()[:32]:
        raise RuntimeError("V9 final MP4 render failed")
    report = {
        "status": "ok",
        "scene": scene.name,
        "movie_strips": 1,
        "image_strips": len(image_strips),
        "sound_strips": len(sound_strips),
        "frames": [scene.frame_start, scene.frame_end],
        "fps": scene.render.fps,
        "duration_seconds": scene.frame_end / scene.render.fps,
        "video_path": str(video),
        "video_bytes": video.stat().st_size,
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[guidance-v9] composition complete")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
