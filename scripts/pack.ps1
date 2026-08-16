#Requires -Version 5.1
<#
.SYNOPSIS
  lcd-monitor-mini: sync VERSION markers and build Windows onedir + Inno Setup installer.

.PARAMETER Version
  Optional SemVer override (default: ./VERSION).

.NOTES
  Artifacts land in dist\ (installer + onedir). No Cloudflare R2 / external feed.
#>
param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$synced = & (Join-Path $PSScriptRoot "sync-version.ps1") -Version $Version
$v = ($synced | Select-Object -Last 1).ToString().Trim()
if ($v -notmatch '^\d+\.\d+\.\d+$') {
    throw "sync-version returned invalid version: [$v]"
}

Write-Host "== Pack lcd-monitor-mini $v =="
& (Join-Path $PSScriptRoot "build-windows.ps1") -Version $v
if ($LASTEXITCODE -ne 0) { throw "build-windows.ps1 failed ($LASTEXITCODE)" }

$setup = Join-Path $root "dist\lcd-monitor-mini-Setup-$v.exe"
$exe = Join-Path $root "dist\lcd-monitor-mini\lcd-monitor-mini.exe"
if (-not (Test-Path $exe)) { throw "Missing onedir exe: $exe" }
if (-not (Test-Path $setup)) {
    throw "Missing installer: $setup (Inno Setup required for release packs)"
}

Write-Host "Pack OK:"
Write-Host "  $exe"
Write-Host "  $setup"
Write-Output $v
