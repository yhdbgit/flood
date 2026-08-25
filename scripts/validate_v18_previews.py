#!/usr/bin/env python3
"""Automated structural and visual checks for V18 composed preview frames."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "output" / "guidance_v18_preview" / "scene_report.json"


def changed_ratio(left: Image.Image, right: Image.Image) -> float:
    difference = ImageChops.difference(left.convert("RGB"), right.convert("RGB"))
    gray = difference.convert("L")
    changed = sum(1 for value in gray.getdata() if value >= 8)
    return changed / (gray.width * gray.height)


def image_metrics(path: Path):
    image = Image.open(path).convert("RGB")
    stats = ImageStat.Stat(image)
    return image, {
        "path": str(path),
        "size": list(image.size),
        "bytes": path.stat().st_size,
        "channel_stddev": [round(value, 2) for value in stats.stddev],
    }


def main():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    if report.get("status") != "composed_pending_automated_visual_review":
        raise RuntimeError("V18 previews are not ready for automated review")
    composed = report.get("composed_previews", [])
    if len(composed) != 3:
        raise RuntimeError("V18 requires exactly three composed previews")
    metrics = []
    finals = []
    raws = []
    for item in composed:
        final, final_metrics = image_metrics(Path(item["path"]))
        raw, raw_metrics = image_metrics(Path(item["raw_path"]))
        if final.size != (960, 540) or raw.size != final.size:
            raise RuntimeError("V18 preview dimensions are invalid")
        if item["bytes"] < 10_000 or min(final_metrics["channel_stddev"]) < 20:
            raise RuntimeError(f"V18 preview lacks visual information: {item['code']}")
        overlay_ratio = changed_ratio(raw, final)
        if overlay_ratio < 0.08:
            raise RuntimeError(f"V18 guidance overlay is missing: {item['code']}")
        metrics.append({
            "code": item["code"],
            "final": final_metrics,
            "raw": raw_metrics,
            "overlay_changed_ratio": round(overlay_ratio, 4),
        })
        finals.append(final)
        raws.append(raw)
    hazard_change = changed_ratio(raws[0], raws[1])
    camera_change = changed_ratio(raws[1], raws[2])
    if hazard_change < 0.01:
        raise RuntimeError("Normal and hazard reference frames are visually indistinguishable")
    if camera_change < 0.10:
        raise RuntimeError("Overview and field-close frames are visually indistinguishable")
    report["status"] = "validated_ready_for_workflow_integration"
    report["visual_review"] = "automated_pass"
    report["automated_visual_validation"] = {
        "status": "passed",
        "checks": {
            "dimensions": [960, 540],
            "composed_preview_count": 3,
            "normal_to_hazard_changed_ratio": round(hazard_change, 4),
            "overview_to_field_close_changed_ratio": round(camera_change, 4),
            "hydraulic_event_forecast_claimed": report.get("hydraulic_event_forecast"),
            "video_rendered": report.get("video_rendered"),
        },
        "images": metrics,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["automated_visual_validation"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
