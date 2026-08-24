"""Validate V12 timeline and render representative QA frames."""

import json
from pathlib import Path

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
OUT = ROOT / "output" / "guidance_v12"
QA = OUT / "qa_frames"
REPORT = OUT / "story_setup_validation.json"
QA_FRAMES = [1, 217, 241, 336, 337, 553, 577, 793, 817, 912, 913, 1129, 1248]


def flood_objects():
    return [obj for obj in bpy.data.objects if obj.name.startswith("InundationV12_S")]


def visible_steps(scene, frame, objects):
    scene.frame_set(frame)
    return sorted({int(obj.get("progression_step")) for obj in objects if not obj.hide_render})


def expected_step(frame):
    if 241 <= frame <= 336 or 817 <= frame <= 912:
        return []
    start = 1 if frame <= 240 else 337 if frame <= 576 else 577 if frame <= 816 else 913
    return [min(10, (frame - start) // 24 + 1)]


def render_qa(scene):
    QA.mkdir(parents=True, exist_ok=True)
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    paths = []
    for frame in QA_FRAMES:
        scene.frame_set(frame)
        path = QA / f"frame_{frame:04d}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        if not path.is_file() or path.stat().st_size < 10_000:
            raise RuntimeError(f"QA render failed: {path}")
        paths.append(str(path))
    return paths


def main():
    scene = bpy.context.scene
    objects = flood_objects()
    camera = bpy.data.objects.get("Camera_Osong_Story_V12")
    timeline = {str(frame): visible_steps(scene, frame, objects) for frame in QA_FRAMES}
    checks = {
        "scene_name": scene.name == "Osong_Story_V12_Base",
        "timeline": (scene.frame_start, scene.frame_end, scene.render.fps) == (1, 1248, 24),
        "duration_52_seconds": scene.frame_end / scene.render.fps == 52.0,
        "story_camera": camera is not None and scene.camera == camera,
        "flood_objects_present": len(objects) >= 10,
        "ten_progression_steps": sorted({int(obj.get("progression_step")) for obj in objects}) == list(range(1, 11)),
        "four_flood_cycles": list(scene.get("flood_cycle_starts", [])) == [1, 337, 577, 913] if scene.get("flood_cycle_starts") else scene.get("story_timeline") is not None,
        "representative_frames": all(timeline[str(frame)] == expected_step(frame) for frame in QA_FRAMES),
        "final_hold_serious": timeline["1129"] == [10] and timeline["1248"] == [10],
        "candidate_c19": scene.get("selected_candidate") == "C19",
        "old_results_not_reused": scene.get("old_gangnae_results_reused") is False,
    }
    if not all(checks.values()):
        report = {"status": "failed", "checks": checks, "timeline": timeline}
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError(json.dumps(report, ensure_ascii=False))
    qa_paths = render_qa(scene)
    report = {
        "status": "ok",
        "checks": checks,
        "timeline": timeline,
        "counts": {"flood_objects": len(objects), "qa_frames": len(qa_paths)},
        "qa_frames": qa_paths,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
