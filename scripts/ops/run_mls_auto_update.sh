#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="/Volumes/ExternalSSD/projects/restats-analytics"
cd "$PROJECT_ROOT"

export HOME="/Users/brookesnader"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
VENV_SITE="$PROJECT_ROOT/.venv/lib/python3.14/site-packages"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ReStats MLS refresh cannot run: required Python interpreter is missing at $PYTHON_BIN" >&2
  exit 78
fi
if [[ ! -d "$VENV_SITE" ]]; then
  echo "ReStats MLS refresh cannot run: project package environment is missing at $VENV_SITE" >&2
  exit 78
fi

if [[ ! -f "$PROJECT_ROOT/scripts/ops/run_mls_auto_update.py" ]]; then
  echo "ReStats MLS refresh cannot run: shared runner is missing" >&2
  exit 78
fi

export PYTHONPATH="$VENV_SITE${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON_BIN" "$PROJECT_ROOT/scripts/ops/run_mls_auto_update.py" --headless "$@"
