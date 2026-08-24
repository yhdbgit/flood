"""Build the reusable Osong V14 3 km Blender context without rendering images or video."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import bpy

ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
OUTER_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_context_v14_3km.json"
CORE_CONTEXT_PATH = ROOT / "data" / "processed" / "osong_hq_v11_context.json"
MANIFEST_PATH = ROOT / "data" / "processed" / "osong_context_v14_3km_manifest.json"
BLEND_PATH = ROOT / "blender" / "osong_context_v14_3km.blend"
REPORT_PATH = ROOT / "output" / "context_v14_3km" / "scene_report.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    if not OUTER_CONTEXT_PATH.is_file():
        raise FileNotFoundError(f"Run scripts/prepare_osong_context_v14_3km.py first: {OUTER_CONTEXT_PATH}")
    outer_context = load_json(OUTER_CONTEXT_PATH)
    core_context = load_json(CORE_CONTEXT_PATH)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    base = load_module("build_osong_context_v14_base", ROOT / "blender" / "build_gangnae_hq_v10.py")
    base.SCENE_NAME = "Osong_Context_V14_3km"
    base.COLLECTIONS = {
        "terrain": "V14_TERRAIN",
        "water": "V14_WATER",
        "roads": "V14_ROADS",
        "buildings": "V14_BUILDINGS",
        "field": "V14_CORE_FIELD",
        "reference": "V14_OFFICIAL_REFERENCE",
        "lighting": "V14_LIGHTING",
    }

    scene, collections = base.reset_scene()
    base.configure_georeference(scene, outer_context)
    blendergis_enabled = False

    outer_terrain, sampler = base.create_terrain(outer_context, collections["terrain"])
    outer_terrain.name = "Terrain_Osong_Background_3km"
    outer_terrain["detail_role"] = "outer_low_detail_background"
    outer_terrain["aoi_size_m"] = [3000.0, 3000.0]

    core_terrain, _ = base.create_terrain(core_context, collections["terrain"])
    core_terrain.name = "Terrain_Osong_Core_1km"
    elevation_alignment = (
        float(core_context["terrain"]["elevation_min_m"])
        - float(outer_context["terrain"]["elevation_min_m"])
    ) * float(outer_context["terrain"]["vertical_exaggeration"])
    core_terrain.location.z = elevation_alignment + 0.08
    core_terrain["detail_role"] = "central_high_detail_overlay"
    core_terrain["aoi_size_m"] = [1000.0, 1000.0]
    core_terrain["alignment_z_m"] = round(core_terrain.location.z, 3)

    water_count = base.create_water(outer_context, sampler, collections["water"])
    road_count, bridge_count = base.create_roads(outer_context, sampler, collections["roads"])
    building_count = base.create_buildings(outer_context, sampler, collections["buildings"])
    field, field_outline = base.create_field(outer_context, sampler, collections["field"])
    if field:
        field.name = "AgriculturalLanduse_V14_Core"
        field["scope"] = "unchanged V11 representative field"
    if field_outline:
        field_outline.name = "AgriculturalLanduseBoundary_V14_Core"
    official_count = base.create_official_reference(outer_context, sampler, collections["reference"])
    base.create_lighting(scene, collections["lighting"])

    overview = base.create_camera(
        "Camera_Osong_Context_V14_Overview",
        (2050.0, -2750.0, 1850.0),
        (0.0, 0.0, 25.0),
        55.0,
        collections["lighting"],
    )
    top = base.create_camera(
        "Camera_Osong_Context_V14_Top",
        (0.0, 0.0, 3600.0),
        (0.0, 0.0, 0.0),
        50.0,
        collections["lighting"],
        orthographic=True,
    )
    top.data.ortho_scale = 3300.0
    field_camera = base.create_camera(
        "Camera_Osong_Context_V14_Field",
        (330.0, -430.0, 310.0),
        (0.0, 0.0, sampler.z(0.0, 0.0) + 4.0),
        58.0,
        collections["lighting"],
    )
    scene.camera = overview
    engine = base.configure_render(scene)

    for key in [key for key in scene.keys() if str(key).startswith("v10_")]:
        del scene[key]
    scene["v14_dataset_id"] = "OSONG-CONTEXT-V14-3KM"
    scene["v14_aoi_size_m"] = [3000.0, 3000.0]
    scene["v14_core_size_m"] = [1000.0, 1000.0]
    scene["v14_outer_terrain_grid"] = [129, 129]
    scene["v14_outer_aerial_zoom"] = 16
    scene["v14_core_aerial_zoom"] = 18
    scene["v14_core_data_unchanged"] = True
    scene["v14_hydraulic_domain_expanded"] = False
    scene["v14_video_rendered"] = False
    scene["v14_context_manifest"] = str(MANIFEST_PATH)
    scene["v14_blendergis_required"] = False
    scene["v14_geodata_import_policy"] = "preprojected EPSG:32652 context; no runtime addon dependency"
    scene["v14_created_at_utc"] = datetime.now(timezone.utc).isoformat()

    for camera in (obj for obj in bpy.data.objects if obj.type == "CAMERA"):
        camera.data.clip_start = 0.1
        camera.data.clip_end = 100_000.0
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            space.clip_start = 0.1
            space.clip_end = 100_000.0
            space.shading.type = "MATERIAL"
            if space.region_3d:
                space.region_3d.view_distance = 2100.0

    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    report = {
        "status": "ok",
        "scene": scene.name,
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "blender_version": bpy.app.version_string,
        "render_engine_configured": engine,
        "blendergis_enabled": blendergis_enabled,
        "blendergis_required": False,
        "aoi_size_m": [3000.0, 3000.0],
        "core_size_m": [1000.0, 1000.0],
        "terrain_objects": [outer_terrain.name, core_terrain.name],
        "core_alignment_z_m": round(core_terrain.location.z, 3),
        "objects": {
            "water": water_count,
            "roads": road_count,
            "bridges": bridge_count,
            "buildings": building_count,
            "field": int(field is not None),
            "field_outline": int(field_outline is not None),
            "official_reference_boundaries": official_count,
            "cameras": [overview.name, top.name, field_camera.name],
        },
        "packed_images": sum(1 for image in bpy.data.images if image.packed_file),
        "still_images_rendered": False,
        "video_rendered": False,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = load_json(MANIFEST_PATH)
    manifest["blender_scene"] = {
        "path": str(BLEND_PATH),
        "bytes": BLEND_PATH.stat().st_size,
        "sha256": sha256(BLEND_PATH),
        "packed_images": report["packed_images"],
        "video_rendered": False,
    }
    manifest["scene_report"] = str(REPORT_PATH)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
