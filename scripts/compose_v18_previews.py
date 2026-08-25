#!/usr/bin/env python3
"""Compose readable V18 guidance panels over clean Blender preview frames."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "guidance_v18_preview"
REPORT_PATH = OUT / "scene_report.json"
RAW_DIR = OUT / "raw"
FONT_CANDIDATES = [
    Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
    Path("/System/Library/Fonts/Supplemental/NotoSansGothic-Regular.ttf"),
]


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def supports_hangul(path: Path):
    candidate = ImageFont.truetype(str(path), size=24)
    samples = []
    for character in ("가", "나", "다", "□"):
        mask = candidate.getmask(character)
        samples.append((mask.size, bytes(mask)))
    return len(set(samples[:3])) == 3 and all(sample != samples[3] for sample in samples[:3])


def selected_font_path():
    path = next((candidate for candidate in FONT_CANDIDATES if candidate.is_file() and supports_hangul(candidate)), None)
    if path is None:
        raise RuntimeError("A Korean-capable font is required for V18 preview composition")
    return path


def font(size: int):
    return ImageFont.truetype(str(selected_font_path()), size=size)


def panel(draw, bounds):
    draw.rounded_rectangle(bounds, radius=14, fill=(5, 17, 34, 218), outline=(87, 196, 255, 230), width=2)


def compose(raw_path: Path, output_path: Path, spec: dict):
    base = Image.open(raw_path).convert("RGBA")
    if base.size != (960, 540):
        raise RuntimeError(f"Unexpected V18 preview size: {base.size}")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    panel(draw, (28, 22, 720, 132))
    panel(draw, (28, 398, 800, 510))
    title_font = font(32)
    line_font = font(21)
    draw.text((50, 39), spec["title"], font=title_font, fill=(255, 255, 255, 255))
    draw.text((50, 91), spec["forecast_line"], font=line_font, fill=(196, 232, 255, 255))
    draw.text((50, 416), spec["reference_line"], font=line_font, fill=(255, 255, 255, 255))
    draw.text((50, 463), spec["impact_line"], font=line_font, fill=(255, 222, 92, 255))
    Image.alpha_composite(base, overlay).convert("RGB").save(output_path, "PNG", optimize=True)


def main():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    if report.get("status") != "rendered_pending_automated_visual_review":
        raise RuntimeError("V18 Blender previews are not ready for composition")
    specs = {item["code"]: item for item in report["previews"]}
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    composed = []
    for rendered in report["rendered_previews"]:
        code = rendered["code"]
        if code not in specs:
            raise RuntimeError(f"Missing V18 preview spec: {code}")
        source = Path(rendered["path"])
        raw = RAW_DIR / source.name
        shutil.copy2(source, raw)
        compose(raw, source, specs[code])
        composed.append({
            "code": code,
            "raw_path": str(raw),
            "raw_sha256": sha256(raw),
            "path": str(source),
            "bytes": source.stat().st_size,
            "sha256": sha256(source),
            "text_layer": "downstream_composition",
        })
    report["status"] = "composed_pending_automated_visual_review"
    report["guidance_text_composited_downstream"] = True
    report["composed_previews"] = composed
    report["visual_review"] = "pending"
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "composed_preview_count": len(composed),
        "paths": [item["path"] for item in composed],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
