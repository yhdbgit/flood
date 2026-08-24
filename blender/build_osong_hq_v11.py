"""Build the selected Osong/Miho HQ V11 Blender scene from prepared data."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
CONTEXT_PATH = ROOT / "data" / "processed" / "osong_hq_v11_context.json"
BLEND_PATH = ROOT / "blender" / "osong_hq_v11.blend"
OUTPUT_DIR = ROOT / "output" / "hq_v11"
REPORT_PATH = OUTPUT_DIR / "scene_report.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rename_v11():
    for blocks in (
        bpy.data.objects,
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.collections,
        bpy.data.worlds,
    ):
        for block in blocks:
            block.name = block.name.replace("Gangnae", "Osong").replace("V10", "V11")

    field = bpy.data.objects.get("RegisteredField_V11")
    if field:
        field.name = "AgriculturalLanduse_V11"
        field["geometry_role"] = "OSM landuse=farmland reference, not cadastral parcel"
        field["production_replacement_required"] = True
    outline = bpy.data.objects.get("RegisteredFieldBoundary_V11")
    if outline:
        outline.name = "AgriculturalLanduseBoundary_V11"
        outline["geometry_role"] = "OSM land-cover boundary"


def main():
    if not CONTEXT_PATH.is_file():
        raise FileNotFoundError(f"Run scripts/prepare_osong_hq_v11.py first: {CONTEXT_PATH}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base = load_module("build_gangnae_hq_v10_base", ROOT / "blender" / "build_gangnae_hq_v10.py")
    base.CONTEXT_PATH = CONTEXT_PATH
    base.BLEND_PATH = BLEND_PATH
    base.OUTPUT_DIR = OUTPUT_DIR
    base.OVERVIEW_PATH = OUTPUT_DIR / "osong_hq_v11_overview.png"
    base.TOP_PATH = OUTPUT_DIR / "osong_hq_v11_top.png"
    base.FIELD_PATH = OUTPUT_DIR / "osong_hq_v11_farmland.png"
    base.REPORT_PATH = REPORT_PATH
    base.SCENE_NAME = "Osong_HQ_V11"
    base.COLLECTIONS = {
        "terrain": "V11_TERRAIN",
        "water": "V11_WATER",
        "roads": "V11_ROADS",
        "buildings": "V11_BUILDINGS",
        "field": "V11_AGRICULTURAL_LANDUSE",
        "reference": "V11_OFFICIAL_REFERENCE",
        "lighting": "V11_LIGHTING",
    }

    def create_water_v11(context, sampler, collection):
        water = base.new_material("V11_Mat_WaterOverlay", (0.015, 0.30, 0.52), 0.22, 0.08, 0.42)
        count = 0
        for index, item in enumerate(context["water_polygons"]):
            obj = base.polygon_mesh(
                f"WaterPolygon_{index:03d}",
                item["polygon"],
                sampler,
                collection,
                water,
                0.72,
            )
            if obj:
                obj["source"] = "OpenStreetMap"
                obj["osm_id"] = str(item["osm_id"])
                obj["water_type"] = item.get("water") or "water"
                obj["visual_role"] = "semi-transparent geospatial overlay"
                count += 1
        for index, item in enumerate(context["waterways"]):
            obj = base.strip_mesh(
                f"Waterway_{index:03d}",
                item["path"],
                float(item["width_m"]),
                sampler,
                collection,
                water,
                0.74,
            )
            if obj:
                obj["source"] = "OpenStreetMap"
                obj["osm_id"] = str(item["osm_id"])
                obj["waterway"] = item["waterway"]
                obj["visual_role"] = "semi-transparent geospatial overlay"
                count += 1
        return count

    base.create_water = create_water_v11
    base.main()

    rename_v11()
    scene = bpy.context.scene
    for key in list(scene.keys()):
        if str(key).startswith("v10_"):
            del scene[key]
    scene["v11_stage"] = "C19 terrain, imagery, river, roads and OSM farmland integrated"
    scene["v11_pilot_id"] = "OSONG-MIHO-AGRI-V11"
    scene["v11_selected_candidate"] = "C19"
    scene["v11_visible_water_source"] = "OpenStreetMap"
    scene["v11_official_reference_source"] = "VWorld UJ201"
    scene["v11_farmland_source"] = "OpenStreetMap way 378002205"
    scene["v11_farmland_is_cadastral"] = False
    scene["v11_v9_v10_files_modified"] = False

    for camera in (obj for obj in bpy.data.objects if obj.type == "CAMERA"):
        camera.data.clip_start = 0.1
        camera.data.clip_end = 100_000.0
    scene.camera = next((obj for obj in bpy.data.objects if "Overview" in obj.name), scene.camera)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            space.clip_start = 0.1
            space.clip_end = 100_000.0
            space.shading.type = "MATERIAL"
            if space.region_3d:
                space.region_3d.view_distance = 900.0
    scene["v11_freeview_clip_end_m"] = 100_000.0
    scene["v11_default_viewport_shading"] = "MATERIAL"
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    context = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    report.update({
        "status": "ok",
        "scene": scene.name,
        "blend_path": str(BLEND_PATH),
        "selected_candidate": "C19",
        "field_object": "AgriculturalLanduse_V11",
        "field_geometry_role": "OSM land-cover reference, not cadastral parcel",
        "origin_wgs84": context["georeference"]["origin_wgs84"],
        "renders": [
            str(OUTPUT_DIR / "osong_hq_v11_overview.png"),
            str(OUTPUT_DIR / "osong_hq_v11_top.png"),
            str(OUTPUT_DIR / "osong_hq_v11_farmland.png"),
        ],
        "v9_v10_files_modified": False,
    })
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
