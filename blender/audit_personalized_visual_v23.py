#!/usr/bin/env python3
"""Audit a Stage 7 personalized MP4 and attach decoder evidence to its report."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy


def parse_args() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Audit a V23 personalized visual")
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args(values)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    video = Path(report["video_path"])
    clip = bpy.data.movieclips.load(str(video), check_existing=False)
    image = bpy.data.images.load(str(video), check_existing=False)
    checks = {
        "resolution": list(image.size) == [1280, 720],
        "frame_duration": int(clip.frame_duration) == 960,
        "source": clip.source == "MOVIE" and image.source == "MOVIE",
        "file_size": video.stat().st_size == report["video_bytes"],
        "cached_media_only": report.get("cached_media_only") is True,
        "no_3d_scene_render": report.get("blender_3d_scene_render") is False,
    }
    audit = {
        "status": "passed" if all(checks.values()) else "failed",
        "resolution": list(image.size),
        "frame_duration": int(clip.frame_duration),
        "channels": int(image.channels),
        "video_bytes": video.stat().st_size,
        "video_sha256": sha256(video),
        "checks": checks,
    }
    report["decoder_audit"] = audit
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    if audit["status"] != "passed":
        raise RuntimeError("V23 personalized visual audit failed")


if __name__ == "__main__":
    main()
