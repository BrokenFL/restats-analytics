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

# Build the most recently completed monthly report after a successful data
# refresh.  The job is idempotent and exits quickly once the target month is
# present; a snapshot failure must not mark the MLS data refresh as failed.
set +e
"$PYTHON_BIN" "$PROJECT_ROOT/scripts/ops/generate_market_report_snapshots.py" --if-missing
snapshot_status=$?
set -e
if [[ $snapshot_status -ne 0 ]]; then
  print "Monthly report snapshot generation failed; the next refresh will retry." >&2
fi
