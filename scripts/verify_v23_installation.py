#!/usr/bin/env python3
"""Verify that a clone can execute the V23 workflow on macOS or Windows."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))

from runtime_config import asset_root, blender_binary, font_path  # noqa: E402
from v23_runtime_asset_catalog import RuntimeAssetCatalog  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-openai", action="store_true")
    parser.add_argument("--decode-media", action="store_true", help="Open all cached media with Blender's decoder")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    checks = {
        "python_3_11_or_newer": sys.version_info >= (3, 11),
        "openai_key": bool(os.getenv("OPENAI_API_KEY")),
    }
    errors = []
    try:
        blender = str(blender_binary())
        checks["blender"] = True
    except RuntimeError as exc:
        blender = None
        checks["blender"] = False
        errors.append(str(exc))
    try:
        font = str(font_path())
        checks["font"] = True
    except RuntimeError as exc:
        font = None
        checks["font"] = False
        errors.append(str(exc))
    asset_report = RuntimeAssetCatalog.load(root=asset_root()).verify()
    checks["runtime_assets"] = asset_report["all_verified"]
    if not checks["runtime_assets"]:
        errors.append("Run python scripts/setup_v23.py to install the cached media bundle")
    if args.decode_media and checks["runtime_assets"] and checks["blender"]:
        decoder_results = []
        catalog = RuntimeAssetCatalog.load(root=asset_root())
        for item in catalog.document["assets"]:
            decoder = subprocess.run(
                [blender, "--background", "--python", str(ROOT / "blender" / "verify_runtime_media_v23.py"), "--", item["asset_id"]],
                cwd=str(ROOT), capture_output=True, text=True,
            )
            decoder_results.append(decoder.returncode == 0 and "\"status\": \"passed\"" in decoder.stdout)
        checks["blender_media_decoder"] = all(decoder_results)
        if not checks["blender_media_decoder"]:
            errors.append("Blender could not decode one or more V23 cached media files")
    required = ["python_3_11_or_newer", "blender", "font", "runtime_assets"]
    if args.require_openai:
        required.append("openai_key")
    if args.decode_media:
        required.append("blender_media_decoder")
    result = {
        "status": "ready" if all(checks[name] for name in required) else "not_ready",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "checks": checks,
        "blender": blender,
        "font": font,
        "asset_root": str(asset_root()),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "ready":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
