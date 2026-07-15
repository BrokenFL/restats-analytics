#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="/Volumes/ExternalSSD/projects/restats-analytics"
cd "$PROJECT_ROOT"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="/usr/bin/python3"
fi

"$PYTHON_BIN" "$PROJECT_ROOT/scripts/ops/run_mls_auto_update.py" --headless "$@"
