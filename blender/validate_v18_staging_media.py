"""Validate V18 staging audio by decoding source files and the final MP4 with Blender aud."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import aud
import numpy as np


def arguments():
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    return parser.parse_args(values)


def decoded(path: Path):
    sound = aud.Sound.file(str(path)).cache()
    samples = sound.data()
    rate, channels = sound.specs
    return samples, int(rate), int(channels)


def statistics(samples):
    if samples.size == 0:
        return {"rms": 0.0, "peak": 0.0, "active_ratio": 0.0}
    absolute = np.abs(samples.astype(np.float64))
    return {
        "rms": round(float(math.sqrt(np.mean(np.square(samples.astype(np.float64))))), 6),
        "peak": round(float(np.max(absolute)), 6),
        "active_ratio": round(float(np.mean(absolute > 0.001)), 6),
    }


def main():
    args = arguments()
    run_dir = args.run_dir.resolve()
    manifest = json.loads((run_dir / "guidance_manifest.json").read_text(encoding="utf-8"))
    composition = json.loads((run_dir / "composition_report.json").read_text(encoding="utf-8"))
    video = Path(manifest["output_video"]).resolve()
    failures = []
    if not video.is_file() or video.stat().st_size < 100_000:
        failures.append("FINAL_MP4_MISSING_OR_TOO_SMALL")
    if composition.get("image_strips") != 5 or composition.get("sound_strips") != 5:
        failures.append("SEQUENCER_STRIP_COUNT_INVALID")
    if composition.get("audio_crop_policy") != "forced_to_segment_end_frame":
        failures.append("AUDIO_CROP_POLICY_MISSING")

    source_audio = []
    for item in manifest["segments"]:
        audio_path = Path(item["audio_path"]).resolve()
        samples, rate, channels = decoded(audio_path)
        duration = len(samples) / rate
        overflow = duration - float(item["duration_seconds"])
        source_audio.append({
            "segment": item["id"],
            "path": str(audio_path),
            "rate": rate,
            "channels": channels,
            "duration_seconds": round(duration, 3),
            "assigned_seconds": item["duration_seconds"],
            "overflow_seconds": round(max(0.0, overflow), 3),
            **statistics(samples),
        })
        if overflow > 0.25:
            failures.append(f"SOURCE_AUDIO_OVERFLOW:{item['id']}")

    final_samples, final_rate, final_channels = decoded(video)
    final_duration = len(final_samples) / final_rate
    final_segments = []
    for item in manifest["segments"]:
        start = round(((item["start_frame"] - 1) / manifest["fps"]) * final_rate)
        end = round((item["end_frame"] / manifest["fps"]) * final_rate)
        stats = statistics(final_samples[start:end])
        final_segments.append({"segment": item["id"], **stats})
        if stats["rms"] < 0.001 or stats["active_ratio"] < 0.01:
            failures.append(f"FINAL_AUDIO_SILENT:{item['id']}")
    expected_duration = float(manifest["duration_seconds"])
    if not 59.9 <= final_duration <= 120.1:
        failures.append("FINAL_AUDIO_DURATION_INVALID")
    if abs(final_duration - expected_duration) > 0.15:
        failures.append("FINAL_AUDIO_DURATION_MANIFEST_MISMATCH")

    report = {
        "status": "passed" if not failures else "failed",
        "video": str(video),
        "video_bytes": video.stat().st_size if video.is_file() else 0,
        "frames": composition.get("frames"),
        "fps": composition.get("fps"),
        "source_audio": source_audio,
        "final_audio": {
            "rate": final_rate,
            "channels": final_channels,
            "duration_seconds": round(final_duration, 3),
            "expected_duration_seconds": expected_duration,
            "segments": final_segments,
        },
        "failures": failures,
    }
    (run_dir / "staging_media_validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise RuntimeError(f"V18 staging media validation failed: {failures}")


if __name__ == "__main__":
    main()
