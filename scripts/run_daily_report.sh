#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="/usr/bin/python3"

cd "$PROJECT_DIR"

if [ -f ".venv/bin/python" ]; then
  PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
fi

"$PYTHON_BIN" src/binance_futures_report.py --env-file .env
