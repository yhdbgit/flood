"""Apply the fresh V17 HRFCO decision to the reusable V16 Blender scene."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
STATE_PATH = ROOT / "data" / "runtime" / "osong_realtime_state_v17.json"
SOURCE_BLEND_PATH = ROOT / "blender" / "osong_inundation_v16.blend"
BLEND_PATH = ROOT / "blender" / "osong_realtime_v17.blend"
OUT = ROOT / "output" / "realtime_v17"
PREVIEW_PATH = OUT / "current_state.png"
REPORT_PATH = OUT / "scene_report.json"
PREVIEW_FRAME = 481


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage_objects():
    return [
        obj
        for obj in bpy.data.objects
        if obj.name.startswith("InundationV16_") or obj.name.startswith("FieldImpactV16_")
    ]


def apply_stage(selected_stage):
    objects = stage_objects()
    visible = []
    for obj in objects:
        code = obj.get("stage_code")
        hidden = code != selected_stage
        obj.hide_viewport = hidden
        obj.hide_render = hidden
        if not hidden:
            visible.append(obj.name)
    return objects, visible


def configure_render(scene):
    scene.frame_set(PREVIEW_FRAME)
    camera = bpy.data.objects.get("Camera_Osong_Story_V14")
    if camera is None:
        raise RuntimeError("V14 story camera is missing from the V16 scene")
    camera.data.clip_start = 0.1
    camera.data.clip_end = 100_000.0
    scene.camera = camera
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.filepath = str(PREVIEW_PATH)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    state = load_json(STATE_PATH)
    if state.get("status") != "ok" or not state.get("selected_visual_stage"):
        raise RuntimeError("V17 state is unavailable; refusing to render it as a normal flood stage")
    selected = state["selected_visual_stage"]
    scene = bpy.context.scene
    objects, visible = apply_stage(selected)
    configure_render(scene)
    decision = state["decision_station"]
    scene["story_version"] = "V17"
    scene["realtime_state_dataset"] = state["dataset_id"]
    scene["realtime_selected_stage"] = selected
    scene["realtime_risk_code"] = state["risk"]["code"]
    scene["realtime_risk_label"] = state["risk"]["label"]
    scene["realtime_station_code"] = decision["code"]
    scene["realtime_station_name"] = decision["name"]
    scene["realtime_observed_at"] = decision["observed_at"]
    scene["realtime_water_level_m"] = float(decision["water_level_m"])
    scene["realtime_field_affected_percent"] = float(state["selected_stage"]["field_affected_percent"])
    scene["realtime_observation_applied"] = True
    scene["hydraulic_inundation_forecast"] = False
    scene["video_rendered"] = False
    scene["v17_created_at_utc"] = datetime.now(timezone.utc).isoformat()
    bpy.ops.render.render(write_still=True)
    if not PREVIEW_PATH.is_file() or PREVIEW_PATH.stat().st_size < 10_000:
        raise RuntimeError("V17 current-state preview render failed")
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    report = {
        "status": "rendered_pending_visual_review",
        "source_blend": str(SOURCE_BLEND_PATH),
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "blend_sha256": sha256(BLEND_PATH),
        "state_path": str(STATE_PATH),
        "state_sha256": sha256(STATE_PATH),
        "selected_stage": selected,
        "risk": state["risk"],
        "decision_station": {
            "code": decision["code"],
            "name": decision["name"],
            "observed_at": decision["observed_at"],
            "age_minutes": decision["age_minutes"],
            "water_level_m": decision["water_level_m"],
        },
        "field_affected_percent": state["selected_stage"]["field_affected_percent"],
        "stage_object_count": len(objects),
        "visible_stage_objects": visible,
        "preview": {
            "path": str(PREVIEW_PATH),
            "bytes": PREVIEW_PATH.stat().st_size,
            "sha256": sha256(PREVIEW_PATH),
        },
        "realtime_observation_applied": True,
        "hydraulic_inundation_forecast": False,
        "video_rendered": False,
        "visual_review": "pending",
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
