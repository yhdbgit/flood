#!/usr/bin/env python3
"""Derive a non-destructive V23 layered Scene Pack from the approved V22 source."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
SOURCE_BLEND = ROOT / "blender" / "osong_visual_v22.blend"
OUTPUT_BLEND = ROOT / "blender" / "osong_common_v23.blend"
OUTPUT_ROOT = ROOT / "output" / "scene_packs" / "osong_miho_v23"
REPORT_PATH = ROOT / "data" / "v23" / "scene_packs" / "osong_miho_v23_layer_manifest.json"

PARENT_GROUPS = {
    "V23_COMMON_BACKGROUND": [
        "V19_TERRAIN",
        "V19_SHELTER_HQ",
        "V21_BANK_VEGETATION",
        "V21_CONTINUOUS_RIVER",
        "V21_FIELD_RIVER_HQ",
        "V21_FIELD_ROADS",
        "V21_RIVER_BANK",
        "V22_FIELD_IMAGE_PROXY_STRUCTURES",
    ],
    "V23_FLOOD_LAYER": ["V21_FLOOD_STAGES"],
    "V23_FIELD_OVERLAY_TEMPLATES": ["V21_REGISTERED_FIELD"],
    "V23_SHELTER_OVERLAY": ["V19_SHELTER_MARKER"],
    "V23_RENDER_INFRA": ["V19_LIGHTING_CAMERA"],
    "V23_LEGACY_UNUSED": [
        "V19_FIELD_BUILDINGS",
        "V19_FIELD_ROADS",
        "V19_REFERENCE_UNUSED",
        "V19_REGISTERED_FIELD",
        "V19_WATER_UNUSED",
        "V20_CONTINUOUS_RIVER",
        "V20_FLOOD_STAGES",
    ],
}

VIEW_LAYER_ALLOWED = {
    "V23_COMMON_BACKGROUND": {"V23_COMMON_BACKGROUND", "V23_RENDER_INFRA"},
    "V23_FLOOD_RGBA": {"V23_FLOOD_LAYER", "V23_RENDER_INFRA"},
    "V23_FIELD_TEMPLATE_RGBA": {"V23_FIELD_OVERLAY_TEMPLATES", "V23_RENDER_INFRA"},
    "V23_SHELTER_RGBA": {"V23_SHELTER_OVERLAY", "V23_RENDER_INFRA"},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def get_or_create_collection(name: str) -> bpy.types.Collection:
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    return collection


def unlink_collection_everywhere(child: bpy.types.Collection, keep_parent: bpy.types.Collection) -> None:
    for scene in bpy.data.scenes:
        if scene.collection.children.get(child.name) is not None:
            scene.collection.children.unlink(child)
    for parent in bpy.data.collections:
        if parent == keep_parent:
            continue
        if parent.children.get(child.name) is not None:
            parent.children.unlink(child)


def reparent_collection(child_name: str, parent: bpy.types.Collection) -> None:
    child = bpy.data.collections.get(child_name)
    if child is None:
        raise RuntimeError(f"Required V22 collection is missing: {child_name}")
    unlink_collection_everywhere(child, parent)
    if parent.children.get(child.name) is None:
        parent.children.link(child)


def configure_collection_tree(scene: bpy.types.Scene) -> None:
    parents = {name: get_or_create_collection(name) for name in PARENT_GROUPS}
    for parent in parents.values():
        if scene.collection.children.get(parent.name) is None:
            scene.collection.children.link(parent)
    for parent_name, children in PARENT_GROUPS.items():
        parent = parents[parent_name]
        for child_name in children:
            reparent_collection(child_name, parent)


def find_layer_collection(root: bpy.types.LayerCollection, name: str):
    if root.name == name:
        return root
    for child in root.children:
        found = find_layer_collection(child, name)
        if found is not None:
            return found
    return None


def configure_view_layers(scene: bpy.types.Scene) -> None:
    while len(scene.view_layers) > 1:
        scene.view_layers.remove(scene.view_layers[-1])
    base = scene.view_layers[0]
    base.name = "V23_COMMON_BACKGROUND"
    for name in VIEW_LAYER_ALLOWED:
        if name != base.name:
            scene.view_layers.new(name=name)

    for layer_name, allowed in VIEW_LAYER_ALLOWED.items():
        layer = scene.view_layers[layer_name]
        layer.use = layer_name == "V23_COMMON_BACKGROUND"
        layer.use_pass_z = True
        for parent_name in PARENT_GROUPS:
            node = find_layer_collection(layer.layer_collection, parent_name)
            if node is None:
                raise RuntimeError(f"Layer collection missing in {layer_name}: {parent_name}")
            node.exclude = parent_name not in allowed


def recursive_object_count(collection: bpy.types.Collection) -> int:
    objects = {obj.name for obj in collection.objects}
    for child in collection.children:
        objects.update(obj.name for obj in child.all_objects)
    return len(objects)


def excluded_parents(layer: bpy.types.ViewLayer):
    result = []
    for parent_name in PARENT_GROUPS:
        node = find_layer_collection(layer.layer_collection, parent_name)
        if node is not None and node.exclude:
            result.append(parent_name)
    return sorted(result)


def main() -> None:
    if Path(bpy.data.filepath).resolve() != SOURCE_BLEND.resolve():
        raise RuntimeError(f"Run this script with the approved V22 source: {SOURCE_BLEND}")
    source_hash_before = sha256(SOURCE_BLEND)
    scene = bpy.context.scene
    if scene.camera is None or scene.camera.name != "Camera_Osong_Shelter_V19":
        raise RuntimeError("Approved V22 animated camera is missing")
    if not bpy.data.objects.get("RegisteredFieldBoundary_V21") or not bpy.data.objects.get("RegisteredFieldFill_V21"):
        raise RuntimeError("Expected V22 fixed field overlay is missing")
    if len([obj for obj in bpy.data.objects if obj.name.startswith("FloodWaterV21_Step_")]) != 10:
        raise RuntimeError("Expected ten V22 flood stages")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    configure_collection_tree(scene)
    configure_view_layers(scene)

    scene.name = "Osong_Common_V23"
    scene.frame_start = 1
    scene.frame_end = 960
    scene.render.fps = 16
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene["v23_scene_pack_id"] = "OSONG-MIHO-SCENE-PACK-V23"
    scene["v23_scene_version"] = "23.1.0-layered-scene"
    scene["v23_source_blend_sha256"] = source_hash_before
    scene["v23_fixed_field_excluded_from_common"] = True
    scene["v23_flood_excluded_from_common"] = True
    scene["v23_shelter_marker_excluded_from_common"] = True
    scene["v23_trigger_time_full_render_allowed"] = False

    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT_BLEND), check_existing=False)
    source_hash_after = sha256(SOURCE_BLEND)
    if source_hash_after != source_hash_before:
        raise RuntimeError("V22 source blend changed during V23 derivation")

    report = {
        "status": "layered_scene_built_preview_pending",
        "scene_pack_id": "OSONG-MIHO-SCENE-PACK-V23",
        "scene_version": "23.1.0-layered-scene",
        "source_blend": str(SOURCE_BLEND),
        "source_blend_unchanged": True,
        "source_blend_sha256": source_hash_before,
        "blend_path": str(OUTPUT_BLEND),
        "blend_bytes": OUTPUT_BLEND.stat().st_size,
        "blend_sha256": sha256(OUTPUT_BLEND),
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "fps": scene.render.fps,
        "camera": scene.camera.name,
        "collection_groups": {
            name: {
                "children": children,
                "recursive_object_count": recursive_object_count(bpy.data.collections[name]),
            }
            for name, children in PARENT_GROUPS.items()
        },
        "view_layers": {
            layer.name: {
                "enabled_by_default": layer.use,
                "excluded_parent_groups": excluded_parents(layer),
            }
            for layer in scene.view_layers
        },
        "common_layer_contract": {
            "includes": ["terrain", "aerial context", "buildings", "roads", "continuous baseline river", "vegetation", "render infrastructure"],
            "excludes": ["fixed registered field", "flood stages", "shelter marker and label", "legacy unused objects"],
            "personalized_claims_baked_in": False,
        },
        "flood_layer_contract": {
            "object_prefix": "FloodWaterV21_Step_",
            "stage_count": 10,
            "render_target": "RGBA transparent pass",
            "hydraulic_event_forecast": False,
        },
        "render_outputs": {
            "common_background_clip": {"status": "render_pending"},
            "flood_rgba_layers": {"status": "render_pending"},
            "previews": {"status": "render_pending"},
        },
        "limitations": [
            "The existing V22 camera remains focused on demo field 001 and the shelter.",
            "The ten flood objects remain a visual progression, not hydraulic timestamps.",
            "Stage 4 separates render layers but does not yet create per-field overlays or camera profiles.",
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
