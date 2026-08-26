"""Cross-platform runtime paths for the V23 handoff package."""
from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ASSET_ROOT = ROOT / "runtime_assets" / "v23"
DEFAULT_OUTPUT_ROOT = ROOT / "output"


def _configured_path(name: str) -> Path | None:
    value = os.getenv(name, "").strip().strip('"')
    return Path(value).expanduser() if value else None


def asset_root() -> Path:
    return (_configured_path("V23_ASSET_ROOT") or DEFAULT_ASSET_ROOT).resolve()


def output_root() -> Path:
    return (_configured_path("V23_OUTPUT_ROOT") or DEFAULT_OUTPUT_ROOT).resolve()


def blender_binary() -> Path:
    configured = _configured_path("BLENDER_BIN")
    if configured:
        if configured.is_file():
            return configured.resolve()
        raise RuntimeError(f"BLENDER_BIN does not point to a file: {configured}")

    discovered = shutil.which("blender")
    if discovered:
        return Path(discovered).resolve()

    candidates: list[Path] = []
    system = platform.system()
    if system == "Darwin":
        candidates.extend([
            Path("/Applications/Blender.app/Contents/MacOS/Blender"),
            Path.home() / "Applications" / "Blender.app" / "Contents" / "MacOS" / "Blender",
        ])
    elif system == "Windows":
        for variable in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
            base = os.getenv(variable)
            if not base:
                continue
            root = Path(base)
            candidates.extend(sorted(root.glob("Blender Foundation/Blender */blender.exe"), reverse=True))
            candidates.append(root / "Blender Foundation" / "Blender" / "blender.exe")

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError("Blender was not found. Install Blender or set BLENDER_BIN in .env.")


def font_path() -> Path:
    configured = _configured_path("V23_FONT_PATH")
    candidates = [
        configured,
        ROOT / "assets" / "fonts" / "NotoSansKR-Regular.ttf",
        Path("C:/Windows/Fonts/malgun.ttf"),
        Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    raise RuntimeError("A Korean font was not found. Run scripts/setup_v23.py or set V23_FONT_PATH.")

