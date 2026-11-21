# Run the full Murmur AI verification suite. Exits non-zero if anything fails.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Fail($msg) { Write-Error "VERIFY FAILED: $msg"; exit 1 }

Write-Host "==> [1/7] Python tests (backend)"
$py = "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:MURMUR_AI_AUTO_DOWNLOAD_WEIGHTS = "0"
& $py -m pytest backend/tests -q
if ($LASTEXITCODE -ne 0) { Fail "pytest" }

Write-Host "==> [2/7] Backend compile check"
& $py -c "import compileall,sys; sys.exit(0 if compileall.compile_dir('backend', quiet=1) else 1)"
if ($LASTEXITCODE -ne 0) { Fail "backend compile" }

Write-Host "==> [3/7] Frontend type-check"
& npm run typecheck
if ($LASTEXITCODE -ne 0) { Fail "tsc" }

Write-Host "==> [4/7] Frontend unit tests"
& npm test
if ($LASTEXITCODE -ne 0) { Fail "vitest" }

Write-Host "==> [5/7] Frontend build + website build"
& npm run build
if ($LASTEXITCODE -ne 0) { Fail "npm build" }
Push-Location website
& npm run build
$webCode = $LASTEXITCODE
Pop-Location
if ($webCode -ne 0) { Fail "website build" }

Write-Host "==> [6/7] Rust check"
New-Item -ItemType Directory -Force -Path "src-tauri\binaries" | Out-Null
foreach ($t in @("x86_64-pc-windows-msvc.exe","x86_64-apple-darwin","aarch64-apple-darwin","x86_64-unknown-linux-gnu","aarch64-unknown-linux-gnu")) {
  $f = "src-tauri\binaries\murmur-backend-$t"
  if (-not (Test-Path $f)) { Set-Content -Path $f -Value "PLACEHOLDER" }
}
$env:PATH += ";$env:USERPROFILE\.cargo\bin"
Push-Location src-tauri
& cargo check --quiet 2>$null
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Fail "cargo check" }

Write-Host "==> [7/7] Pre-release smoke test"
& powershell -File scripts\smoke-test.ps1
if ($LASTEXITCODE -ne 0) { Fail "smoke test" }

Write-Host "ALL CHECKS PASSED"
