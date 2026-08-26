#!/usr/bin/env python3
"""Render Stage 7 field backgrounds and transparent personalization overlays."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any, Dict, Iterable, List

import bpy


ROOT = Path(__file__).resolve().parents[1]
BLEND = ROOT / "blender" / "osong_personalization_v23.blend"
PLAN_PATH = ROOT / "data" / "v23" / "composition_assets" / "composition_asset_plan_v23.json"
MANIFEST_PATH = ROOT / "data" / "v23" / "composition_assets" / "composition_assets_manifest_v23.json"
PROOF_ROOT = ROOT / "output" / "composition_assets" / "v23" / "proofs"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Render V23 Stage 7 composition assets")
    parser.add_argument("--mode", choices=("proof", "render"), required=True)
    parser.add_argument("--asset", action="append", help="Asset ID; repeatable. Omit for all.")
    parser.add_argument("--asset-type", choices=("field_clean_background", "field_overlay", "shelter_overlay"))
    parser.add_argument("--proof-scale", type=int, default=50, choices=(25, 50, 100))
    return parser.parse_args(values)


def selected_assets(plan: Dict[str, Any], names: Iterable[str] | None, asset_type: str | None) -> List[Dict[str, Any]]:
    available = {item["asset_id"]: item for item in plan["assets"]}
    if names:
        unknown = sorted(set(names) - set(available))
        if unknown:
            raise ValueError(f"Unknown asset IDs: {', '.join(unknown)}")
        items = [available[name] for name in names]
    else:
        items = list(plan["assets"])
    if asset_type:
        items = [item for item in items if item["asset_type"] == asset_type]
    if not items:
        raise ValueError("No Stage 7 assets selected")
    return items


def configure_scene(scene, plan: Dict[str, Any], asset: Dict[str, Any], scale: int = 100) -> None:
    camera = bpy.data.objects.get(asset["camera_object"])
    if camera is None:
        raise RuntimeError(f"Missing camera: {asset['camera_object']}")
    if scene.view_layers.get(asset["view_layer"]) is None:
        raise RuntimeError(f"Missing view layer: {asset['view_layer']}")
    scene.camera = camera
    for layer in scene.view_layers:
        layer.use = layer.name == asset["view_layer"]
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.fps = int(plan["fps"])
    scene.render.resolution_x = int(plan["resolution"][0])
    scene.render.resolution_y = int(plan["resolution"][1])
    scene.render.resolution_percentage = scale
    scene.render.film_transparent = bool(asset["transparent_background"])
    scene.render.use_file_extension = True


def render_proofs(scene, plan: Dict[str, Any], assets: List[Dict[str, Any]], scale: int) -> List[Dict[str, Any]]:
    PROOF_ROOT.mkdir(parents=True, exist_ok=True)
    outputs = []
    for asset in assets:
        configure_scene(scene, plan, asset, scale)
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGBA" if asset["transparent_background"] else "RGB"
        scene.render.image_settings.color_depth = "8"
        for frame in asset["proof_frames"]:
            path = PROOF_ROOT / f"{asset['asset_id']}_{frame:04d}.png"
            scene.frame_set(int(frame))
            scene.render.filepath = str(path)
            started = perf_counter()
            bpy.ops.render.render(write_still=True, layer=asset["view_layer"])
            if not path.is_file() or path.stat().st_size < 1000:
                raise RuntimeError(f"Proof render failed: {path}")
            outputs.append({
                "asset_id": asset["asset_id"],
                "asset_type": asset["asset_type"],
                "field_id": asset.get("field_id"),
                "frame": frame,
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "elapsed_seconds": round(perf_counter() - started, 3),
            })
    return outputs


def configure_video(scene, asset: Dict[str, Any]) -> None:
    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = asset["container"]
    scene.render.ffmpeg.codec = asset["codec"]
    scene.render.image_settings.color_mode = asset["colour_mode"]
    scene.render.ffmpeg.audio_codec = "NONE"
    if asset["codec"] == "H264":
        try:
            scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
            scene.render.ffmpeg.ffmpeg_preset = "GOOD"
        except (AttributeError, TypeError):
            pass


def render_movies(scene, plan: Dict[str, Any], assets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    outputs = []
    for asset in assets:
        configure_scene(scene, plan, asset, 100)
        configure_video(scene, asset)
        path = ROOT / asset["output_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        scene.frame_start = int(asset["frame_start"])
        scene.frame_end = int(asset["frame_end"])
        scene.render.filepath = str(path)
        started = perf_counter()
        bpy.ops.render.render(animation=True, layer=asset["view_layer"])
        elapsed = round(perf_counter() - started, 3)
        if not path.is_file() or path.stat().st_size < 10_000 or b"ftyp" not in path.read_bytes()[:64]:
            raise RuntimeError(f"Movie render failed: {path}")
        outputs.append({
            **{key: asset.get(key) for key in ("asset_id", "asset_type", "field_id", "shelter_id", "camera_object", "view_layer")},
            "frame_start": asset["frame_start"],
            "frame_end": asset["frame_end"],
            "frame_count": asset["frame_count"],
            "duration_seconds": asset["duration_seconds"],
            "path": str(path),
            "project_relative_path": asset["output_path"],
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "render_elapsed_seconds": elapsed,
            "container": asset["container"],
            "codec": asset["codec"],
            "colour_mode": asset["colour_mode"],
            "transparent_background": asset["transparent_background"],
        })
    return outputs


def main() -> None:
    if Path(bpy.data.filepath).resolve() != BLEND.resolve():
        raise RuntimeError(f"Run this script with {BLEND}")
    args = parse_args()
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    assets = selected_assets(plan, args.asset, args.asset_type)
    scene = bpy.context.scene
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.is_file() else {
        "schema_version": "1.0",
        "scene_pack_id": plan["scene_pack_id"],
        "source_blend": str(BLEND),
        "proofs": {"status": "pending", "items": []},
        "assets": [],
    }
    manifest.update({
        "source_blend_bytes": BLEND.stat().st_size,
        "source_blend_sha256": sha256(BLEND),
        "plan_path": str(PLAN_PATH),
        "plan_sha256": sha256(PLAN_PATH),
    })
    selected_ids = {item["asset_id"] for item in assets}
    if args.mode == "proof":
        rendered = render_proofs(scene, plan, assets, args.proof_scale)
        retained = [item for item in manifest.get("proofs", {}).get("items", []) if item["asset_id"] not in selected_ids]
        manifest["proofs"] = {
            "status": "rendered_review_pending",
            "resolution": [int(plan["resolution"][0] * args.proof_scale / 100), int(plan["resolution"][1] * args.proof_scale / 100)],
            "items": retained + rendered,
        }
        manifest["status"] = "proofs_rendered_review_pending"
    else:
        rendered = render_movies(scene, plan, assets)
        expected = {item["asset_id"] for item in plan["assets"]}
        retained = [
            item
            for item in manifest.get("assets", [])
            if item["asset_id"] in expected and item["asset_id"] not in selected_ids
        ]
        manifest["assets"] = retained + rendered
        actual = {item["asset_id"] for item in manifest["assets"]}
        manifest["status"] = "rendered_validation_pending" if expected == actual else "partially_rendered"
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": manifest["status"],
        "mode": args.mode,
        "rendered_items": len(rendered),
        "manifest": str(MANIFEST_PATH),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
