#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="/Users/brookesnader/Library/Mobile Documents/com~apple~CloudDocs/ReStatsProgram DEC 2025"
cd "$PROJECT_ROOT"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

exec /usr/bin/python3 "$PROJECT_ROOT/scripts/ops/run_mls_auto_update.py" --headless
