"""Small application boundary for a team backend to call V23 directly."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

from guidance_v23_workflow import run_workflow_event
from runtime_config import ROOT, output_root


async def generate_guidance(
    event: Dict[str, Any],
    *,
    mode: str = "production",
    destination: Path | None = None,
) -> Dict[str, Any]:
    """Generate one personalized MP4 from an already-approved trigger event."""
    load_dotenv(ROOT / ".env")
    if mode not in {"staging", "production"}:
        raise ValueError("mode must be staging or production")
    return await run_workflow_event(
        event,
        mode,
        destination or (output_root() / "guidance_v23"),
    )
