#!/usr/bin/env python3
"""Install the portable cached-media bundle used by V23."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from urllib.request import urlopen
import zipfile


ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "agents"
sys.path.insert(0, str(AGENTS))

from runtime_config import asset_root, blender_binary, font_path  # noqa: E402
from v23_runtime_asset_catalog import RuntimeAssetCatalog  # noqa: E402


BUNDLE_MANIFEST = ROOT / "config" / "runtime_asset_bundles_v23.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_extract(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    archive_prefix = Path("runtime_assets") / "v23"
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            member_path = Path(member.filename)
            try:
                relative = member_path.relative_to(archive_prefix)
            except ValueError as exc:
                raise RuntimeError(f"Unexpected ZIP member: {member.filename}") from exc
            target = (destination / relative).resolve()
            if destination not in target.parents and target != destination:
                raise RuntimeError(f"Unsafe ZIP member: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as input_stream, target.open("wb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)


def download(url: str, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(url, timeout=120) as response, temporary.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    temporary.replace(destination)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install V23 cached runtime assets")
    parser.add_argument("--archive-dir", type=Path, help="Use already-downloaded Release ZIP files")
    parser.add_argument("--download-dir", type=Path, default=ROOT / ".cache" / "v23-assets")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11 or newer is required")
    env_path = ROOT / ".env"
    if not env_path.exists() and (ROOT / ".env.example").is_file():
        shutil.copy2(ROOT / ".env.example", env_path)

    existing = RuntimeAssetCatalog.load(root=asset_root()).verify()
    installed = existing["all_verified"] and not args.force
    used_archives = []
    if not installed:
        document = json.loads(BUNDLE_MANIFEST.read_text(encoding="utf-8"))
        for item in document["bundles"]:
            archive = (args.archive_dir / item["filename"]) if args.archive_dir else (args.download_dir / item["filename"])
            if args.force or not archive.is_file() or archive.stat().st_size != item["bytes"]:
                if args.archive_dir:
                    raise RuntimeError(f"Missing local Release asset: {archive}")
                download(item["url"], archive)
            if archive.stat().st_size != item["bytes"] or sha256(archive) != item["sha256"]:
                raise RuntimeError(f"Release asset checksum failed: {archive}")
            safe_extract(archive, asset_root())
            used_archives.append(str(archive))

    verification = RuntimeAssetCatalog.load(root=asset_root()).verify()
    if not verification["all_verified"]:
        invalid = [item["asset_id"] for item in verification["items"] if item["status"] != "verified"]
        raise RuntimeError(f"V23 runtime asset verification failed: {invalid}")
    result = {
        "status": "ready",
        "asset_root": str(asset_root()),
        "asset_count": len(verification["items"]),
        "reused_existing_assets": installed,
        "archives": used_archives,
        "blender": str(blender_binary()),
        "font": str(font_path()),
        "env_file": str(env_path),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
