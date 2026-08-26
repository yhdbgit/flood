#!/usr/bin/env python3
"""Render reviewed proofs or lossless RGBA V23 flood-layer movie segments."""
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
PLAN_PATH = ROOT / "data" / "v23" / "flood_assets" / "flood_render_plan_v23.json"
MANIFEST_PATH = ROOT / "data" / "v23" / "flood_assets" / "flood_assets_manifest_v23.json"
PROOF_ROOT = ROOT / "output" / "flood_assets" / "v23" / "proofs"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Render V23 flood RGBA assets")
    parser.add_argument("--mode", choices=("proof", "render"), required=True)
    parser.add_argument("--segment", action="append", help="Segment ID; repeatable. Omit for all.")
    parser.add_argument("--proof-scale", type=int, default=50, choices=(25, 50, 100))
    return parser.parse_args(args)


def selected_segments(plan: Dict[str, Any], names: Iterable[str] | None) -> List[Dict[str, Any]]:
    available = {item["segment_id"]: item for item in plan["segments"]}
    if not names:
        return list(plan["segments"])
    unknown = sorted(set(names) - set(available))
    if unknown:
        raise ValueError(f"Unknown segment IDs: {', '.join(unknown)}")
    return [available[name] for name in names]


def configure_base(scene, plan: Dict[str, Any]) -> None:
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.fps = int(plan["fps"])
    scene.render.resolution_x = int(plan["resolution"][0])
    scene.render.resolution_y = int(plan["resolution"][1])
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.use_file_extension = True


def render_proofs(scene, plan: Dict[str, Any], segments: List[Dict[str, Any]], scale: int) -> List[Dict[str, Any]]:
    scene.render.resolution_percentage = scale
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    PROOF_ROOT.mkdir(parents=True, exist_ok=True)
    outputs = []
    for segment in segments:
        view_layer = segment.get("view_layer", plan["view_layer"])
        if scene.view_layers.get(view_layer) is None:
            raise RuntimeError(f"Missing view layer: {view_layer}")
        for layer in scene.view_layers:
            layer.use = layer.name == view_layer
        camera = bpy.data.objects.get(segment["camera_object"])
        if camera is None:
            raise RuntimeError(f"Missing camera: {segment['camera_object']}")
        scene.camera = camera
        for frame in segment["proof_frames"]:
            path = PROOF_ROOT / f"{segment['segment_id']}_{frame:04d}.png"
            scene.frame_set(int(frame))
            scene.render.filepath = str(path)
            started = perf_counter()
            bpy.ops.render.render(write_still=True, layer=view_layer)
            if not path.is_file() or path.stat().st_size < 1000:
                raise RuntimeError(f"Proof render failed: {path}")
            outputs.append({
                "segment_id": segment["segment_id"],
                "field_id": segment.get("field_id"),
                "camera_object": segment["camera_object"],
                "view_layer": view_layer,
                "frame": frame,
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "elapsed_seconds": round(perf_counter() - started, 3),
            })
    return outputs


def render_movies(scene, plan: Dict[str, Any], segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = plan["codec_contract"]["container"]
    scene.render.ffmpeg.codec = plan["codec_contract"]["codec"]
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.ffmpeg.audio_codec = "NONE"
    outputs = []
    for segment in segments:
        view_layer = segment.get("view_layer", plan["view_layer"])
        if scene.view_layers.get(view_layer) is None:
            raise RuntimeError(f"Missing view layer: {view_layer}")
        for layer in scene.view_layers:
            layer.use = layer.name == view_layer
        camera = bpy.data.objects.get(segment["camera_object"])
        if camera is None:
            raise RuntimeError(f"Missing camera: {segment['camera_object']}")
        path = ROOT / segment["output_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        scene.camera = camera
        scene.frame_start = int(segment["frame_start"])
        scene.frame_end = int(segment["frame_end"])
        scene.render.filepath = str(path)
        started = perf_counter()
        bpy.ops.render.render(animation=True, layer=view_layer)
        elapsed = round(perf_counter() - started, 3)
        if not path.is_file() or path.stat().st_size < 10_000 or b"ftyp" not in path.read_bytes()[:64]:
            raise RuntimeError(f"Flood-layer movie render failed: {path}")
        outputs.append({
            "segment_id": segment["segment_id"],
            "field_id": segment.get("field_id"),
            "camera_object": segment["camera_object"],
            "view_layer": view_layer,
            "frame_start": segment["frame_start"],
            "frame_end": segment["frame_end"],
            "frame_count": segment["frame_count"],
            "duration_seconds": segment["duration_seconds"],
            "path": str(path),
            "project_relative_path": segment["output_path"],
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "render_elapsed_seconds": elapsed,
            "container": plan["codec_contract"]["container"],
            "codec": plan["codec_contract"]["codec"],
            "colour_mode": "RGBA",
            "transparent_background": True,
        })
    return outputs


def main() -> None:
    if Path(bpy.data.filepath).resolve() != BLEND.resolve():
        raise RuntimeError(f"Run this script with {BLEND}")
    args = parse_args()
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    scene = bpy.context.scene
    configure_base(scene, plan)
    segments = selected_segments(plan, args.segment)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.is_file() else {
        "schema_version": "1.0",
        "scene_pack_id": plan["scene_pack_id"],
        "source_blend": str(BLEND),
        "source_blend_bytes": BLEND.stat().st_size,
        "source_blend_sha256": sha256(BLEND),
        "plan_path": str(PLAN_PATH),
        "plan_sha256": sha256(PLAN_PATH),
        "codec_contract": plan["codec_contract"],
        "proofs": {"status": "pending", "items": []},
        "segments": [],
    }
    manifest["source_blend_bytes"] = BLEND.stat().st_size
    manifest["source_blend_sha256"] = sha256(BLEND)
    manifest["plan_sha256"] = sha256(PLAN_PATH)
    manifest["codec_contract"] = plan["codec_contract"]
    if args.mode == "proof":
        items = render_proofs(scene, plan, segments, args.proof_scale)
        retained = [item for item in manifest.get("proofs", {}).get("items", []) if item["segment_id"] not in {s["segment_id"] for s in segments}]
        manifest["proofs"] = {
            "status": "rendered_review_pending",
            "resolution": [int(plan["resolution"][0] * args.proof_scale / 100), int(plan["resolution"][1] * args.proof_scale / 100)],
            "items": retained + items,
        }
        manifest["status"] = "proofs_rendered_review_pending"
    else:
        items = render_movies(scene, plan, segments)
        expected = {item["segment_id"] for item in plan["segments"]}
        selected = {item["segment_id"] for item in segments}
        retained = [
            item
            for item in manifest.get("segments", [])
            if item["segment_id"] in expected and item["segment_id"] not in selected
        ]
        manifest["segments"] = retained + items
        rendered = {item["segment_id"] for item in manifest["segments"]}
        manifest["status"] = "rendered_validation_pending" if expected == rendered else "partially_rendered"
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": manifest["status"],
        "mode": args.mode,
        "rendered_items": len(items),
        "manifest": str(MANIFEST_PATH),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
