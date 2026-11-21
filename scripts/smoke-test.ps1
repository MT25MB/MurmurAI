# Pre-release smoke test: local sidecar, /health, /ws, tool schemas and artifacts.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "==> Smoke test"
& $py scripts/smoke_check.py
if ($LASTEXITCODE -ne 0) {
  Write-Error "SMOKE FAILED"
  exit 1
}
Write-Host "SMOKE PASSED"
