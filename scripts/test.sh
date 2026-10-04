#!/usr/bin/env bash
# Run the suite on Linux. From Windows: wsl -- bash scripts/test.sh
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "run via: wsl -- bash scripts/test.sh" >&2
  exit 1
fi

cd "$(dirname "$0")/.."

if [[ ! -x .venv-wsl/bin/python ]] || ! .venv-wsl/bin/python -c "import sys" >/dev/null 2>&1; then
  rm -rf .venv-wsl
  python3 -m venv .venv-wsl || true
  if ! .venv-wsl/bin/python -c "import sys" >/dev/null 2>&1; then
    rm -rf .venv-wsl
    python3 -m venv --copies .venv-wsl
  fi
fi

stamp=".venv-wsl/.requirements-dev.stamp"
if [[ ! -f "$stamp" || requirements-dev.txt -nt "$stamp" ]]; then
  .venv-wsl/bin/pip install -q -r requirements-dev.txt
  touch "$stamp"
fi

exec .venv-wsl/bin/python -m pytest "$@"
