# Smoke-test Rev A handshake. Stops UsbMonitor first so COM is free.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "Stopping UsbMonitor if present..."
Get-Process -Name "UsbMonitor" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

& $VenvPython (Join-Path $PSScriptRoot "smoke_test.py")
exit $LASTEXITCODE
