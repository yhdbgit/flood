#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi
EVENT_PATH="${1:-$PROJECT_DIR/data/v23/events/valid_forecast_and_hydrology.json}"
exec "$PYTHON_BIN" "$PROJECT_DIR/agents/guidance_v23_workflow.py" --event "$EVENT_PATH" --mode production
