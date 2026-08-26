"""Ask Blender's bundled FFmpeg decoder to open every portable V23 asset."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import bpy


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
from v23_runtime_asset_catalog import RuntimeAssetCatalog  # noqa: E402


def main() -> None:
    catalog = RuntimeAssetCatalog.load()
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    requested = values[0] if values else None
    items = []
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    editor = scene.sequence_editor_create()
    for source in catalog.document["assets"]:
        if requested and source["asset_id"] != requested:
            continue
        path = catalog.root / source["relative_path"]
        try:
            strip = editor.strips.new_movie(source["asset_id"], str(path), 1, 1, fit_method="FIT")
            resolution = [int(strip.elements[0].orig_width), int(strip.elements[0].orig_height)]
            frames = int(strip.frame_duration)
            ok = frames > 0 and resolution == [1280, 720]
            items.append({
                "asset_id": source["asset_id"],
                "status": "decoded" if ok else "invalid",
                "frames": frames,
                "resolution": resolution,
            })
            editor.strips.remove(strip)
        except Exception as exc:
            items.append({"asset_id": source["asset_id"], "status": "invalid", "error": str(exc)})
    result = {"status": "passed" if all(item["status"] == "decoded" for item in items) else "failed", "items": items}
    print("V23_MEDIA_CHECK=" + json.dumps(result, ensure_ascii=False))
    if result["status"] != "passed":
        raise RuntimeError("One or more V23 cached assets cannot be decoded by Blender")


if __name__ == "__main__":
    main()
