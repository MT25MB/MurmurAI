# Run the full Murmur AI verification suite. Exits non-zero if anything fails.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Fail($msg) { Write-Error "VERIFY FAILED: $msg"; exit 1 }

Write-Host "==> [1/9] Python tests (backend)"
$py = "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:MURMUR_AI_AUTO_DOWNLOAD_WEIGHTS = "0"
& $py -m pytest backend/tests tests/e2e -q
if ($LASTEXITCODE -ne 0) { Fail "pytest" }

Write-Host "==> [2/9] Backend compile check"
& $py -c "import compileall,sys; sys.exit(0 if compileall.compile_dir('backend', quiet=1) else 1)"
if ($LASTEXITCODE -ne 0) { Fail "backend compile" }

Write-Host "==> [3/9] Generated docs are current"
& $py scripts\generate_docs.py --check
if ($LASTEXITCODE -ne 0) { Fail "generated docs" }

Write-Host "==> [4/9] Frontend type-check"
& npm run typecheck
if ($LASTEXITCODE -ne 0) { Fail "tsc" }

Write-Host "==> [5/9] Frontend unit tests"
& npm test
if ($LASTEXITCODE -ne 0) { Fail "vitest" }

Write-Host "==> [6/9] WCAG 2.2 / ARIA accessibility regression suite"
& npm run test:a11y
if ($LASTEXITCODE -ne 0) { Fail "accessibility suite" }

Write-Host "==> [7/9] Frontend build + website build"
& npm run build
if ($LASTEXITCODE -ne 0) { Fail "npm build" }
Push-Location website
& npm run build
$webCode = $LASTEXITCODE
Pop-Location
if ($webCode -ne 0) { Fail "website build" }

Write-Host "==> [8/9] Rust check"
New-Item -ItemType Directory -Force -Path "src-tauri\binaries" | Out-Null
foreach ($t in @("x86_64-pc-windows-msvc.exe","x86_64-pc-windows-gnu.exe","x86_64-apple-darwin","aarch64-apple-darwin","x86_64-unknown-linux-gnu","aarch64-unknown-linux-gnu")) {
  $f = "src-tauri\binaries\murmur-backend-$t"
  if (-not (Test-Path $f)) { Set-Content -Path $f -Value "PLACEHOLDER" }
}
$env:PATH += ";$env:USERPROFILE\.cargo\bin"
Push-Location src-tauri
& cargo check --quiet
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Fail "cargo check" }
# Rust unit tests run in CI on a fresh runner; a local debug build would need
# several GB and can fill the disk on contributor machines.

Write-Host "==> [9/9] Pre-release smoke test"
& powershell -File scripts\smoke-test.ps1
if ($LASTEXITCODE -ne 0) { Fail "smoke test" }

Write-Host "ALL CHECKS PASSED"
