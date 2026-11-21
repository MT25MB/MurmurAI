#!/usr/bin/env bash
# Pre-release smoke test: local sidecar, /health, /ws, tool schemas and artifacts.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -x backend/.venv/bin/python ]; then
  PY=backend/.venv/bin/python
elif [ -x backend/.venv/Scripts/python.exe ]; then
  PY=backend/.venv/Scripts/python.exe
else
  PY=python3
fi

echo "==> Smoke test"
"$PY" scripts/smoke_check.py
echo "SMOKE PASSED"
