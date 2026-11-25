#!/usr/bin/env bash
# Run the full Murmur AI verification suite. Exits non-zero if anything fails.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail() { echo "VERIFY FAILED: $1" >&2; exit 1; }

echo "==> [1/8] Python tests (backend)"
if [ -x backend/.venv/bin/python ]; then
  PY=backend/.venv/bin/python
elif [ -x backend/.venv/Scripts/python.exe ]; then
  PY=backend/.venv/Scripts/python.exe
else
  PY=python3
fi
MURMUR_AI_AUTO_DOWNLOAD_WEIGHTS=0 "$PY" -m pytest backend/tests tests/e2e -q || fail "pytest"

echo "==> [2/8] Backend compile check"
"$PY" -c "import compileall,sys; sys.exit(0 if compileall.compile_dir('backend', quiet=1) else 1)" || fail "backend compile"

echo "==> [3/8] Frontend type-check"
npm run typecheck || fail "tsc"

echo "==> [4/8] Frontend unit tests"
npm test || fail "vitest"

echo "==> [5/8] WCAG 2.2 / ARIA accessibility regression suite"
npm run test:a11y || fail "accessibility suite"

echo "==> [6/8] Frontend production build + website build"
npm run build || fail "npm build"
(cd website && npm run build) || fail "website build"

echo "==> [7/8] Rust check"
CI=true GITHUB_ACTIONS=true node scripts/prepare-sidecar.mjs >/dev/null 2>&1 || true
mkdir -p src-tauri/binaries
for t in x86_64-pc-windows-msvc.exe x86_64-apple-darwin aarch64-apple-darwin x86_64-unknown-linux-gnu aarch64-unknown-linux-gnu; do
  [ -f "src-tauri/binaries/murmur-backend-$t" ] || printf 'PLACEHOLDER\n' > "src-tauri/binaries/murmur-backend-$t"
done
(cd src-tauri && cargo check --quiet) || fail "cargo check"

echo "==> [8/8] Pre-release smoke test"
bash scripts/smoke-test.sh || fail "smoke test"

echo "ALL CHECKS PASSED"
