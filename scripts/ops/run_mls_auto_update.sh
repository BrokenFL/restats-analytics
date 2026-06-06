#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="/Volumes/ExternalSSD/projects/restats-analytics"
cd "$PROJECT_ROOT"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

exec /usr/bin/python3 "$PROJECT_ROOT/scripts/ops/run_mls_auto_update.py" --headless
