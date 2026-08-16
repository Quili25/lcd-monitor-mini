# Launch lcd-monitor-mini product UI (UsbMonitor replacement).
# Soft-frees COM holders first.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Missing venv. Run: python -m venv .venv; .\.venv\Scripts\pip install -r requirements-app.txt -r vendor\turing-smart-screen-python\requirements.txt"
}

Write-Host "Freeing COM (soft)..."
& (Join-Path $PSScriptRoot "reset-display.ps1") -SoftOnly -SkipVerify
if ($LASTEXITCODE -notin @(0, $null)) {
    Write-Warning "reset-display returned $LASTEXITCODE - continuing anyway"
}

Set-Location $Root
Write-Host "Starting app.main ..."
& $VenvPython -m app.main
