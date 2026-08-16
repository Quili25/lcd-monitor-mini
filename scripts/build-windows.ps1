# Build lcd-monitor-mini Windows onedir + optional Inno Setup installer.
# Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File .\scripts\build-windows.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\build-windows.ps1 -Version 1.2.3
param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $Version) {
    $vf = Join-Path $Root "VERSION"
    if (Test-Path $vf) {
        $Version = (Get-Content $vf -Raw).Trim()
    }
}
if ($Version -and $Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Invalid -Version (expected X.Y.Z): '$Version'"
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$VenvPip = Join-Path $Root ".venv\Scripts\pip.exe"
if (-not (Test-Path $VenvPython)) {
    throw "Missing .venv. Create it and install requirements-app.txt first."
}

# PyInstaller cannot overwrite dist\ while lcd-monitor-mini.exe (or its DLLs) are loaded.
function Stop-ProductHolders {
    Write-Host "== Stopping running lcd-monitor-mini (unlock dist) =="
    Get-Process -Name "lcd-monitor-mini","turing-lcd" -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "  stop PID $($_.Id)"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'app\.main|\\lcd-monitor-mini\\dist\\|\\turing-lcd\\dist\\' } |
        ForEach-Object {
            Write-Host "  stop $($_.Name) PID $($_.ProcessId)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Start-Sleep -Seconds 1
    foreach ($name in @("lcd-monitor-mini", "turing-lcd")) {
        $distApp = Join-Path $Root "dist\$name"
        if (Test-Path $distApp) {
            try {
                Remove-Item -LiteralPath $distApp -Recurse -Force -ErrorAction Stop
                Write-Host "  cleared dist\${name}"
            } catch {
                Write-Warning "Could not delete dist\${name}: $($_.Exception.Message)"
                throw
            }
        }
    }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warning "Building as Administrator is unnecessary. Prefer a normal PowerShell window."
}

Stop-ProductHolders

Write-Host "== Refresh packaging seed/fonts/scripts =="
New-Item -ItemType Directory -Force -Path "packaging\seed\themes","packaging\fonts","packaging\scripts" | Out-Null
if (Test-Path "packaging\seed\themes\omar") {
    Remove-Item -Recurse -Force "packaging\seed\themes\omar"
}
Copy-Item -Recurse -Force "themes\omar" "packaging\seed\themes\omar"
Copy-Item -Force "config.yaml" "packaging\seed\config.yaml"
if (Test-Path "vendor\turing-smart-screen-python\res\fonts\jetbrains-mono") {
    if (Test-Path "packaging\fonts\jetbrains-mono") {
        Remove-Item -Recurse -Force "packaging\fonts\jetbrains-mono"
    }
    Copy-Item -Recurse -Force "vendor\turing-smart-screen-python\res\fonts\jetbrains-mono" "packaging\fonts\jetbrains-mono"
}
Copy-Item -Force "scripts\reset-display.ps1","scripts\disable-usbmonitor.ps1" "packaging\scripts\"

Write-Host "== Ensure icon (desktop source preferred) =="
$DesktopIcon = Join-Path $env:USERPROFILE "Desktop\lcd-monitor-mini icon.png"
$LegacyDesktopIcon = Join-Path $env:USERPROFILE "Desktop\turing-lcd icon.png"
& $VenvPython -c @"
from PIL import Image
from pathlib import Path
src_desktop = Path(r'$DesktopIcon')
src_legacy = Path(r'$LegacyDesktopIcon')
src = src_desktop if src_desktop.is_file() else (src_legacy if src_legacy.is_file() else Path('packaging/icon.png'))
out = Path('packaging')
assets = Path('app/assets')
assets.mkdir(parents=True, exist_ok=True)
if src.is_file():
    im = Image.open(src).convert('RGBA')
    pix = im.load()
    w,h = im.size
    for y in range(h):
        for x in range(w):
            r,g,b,a = pix[x,y]
            if r < 18 and g < 18 and b < 18:
                pix[x,y] = (0,0,0,0)
    im.save(out/'icon.png')
    sizes = [16,24,32,48,64,128,256]
    imgs = [im.resize((s,s), Image.Resampling.NEAREST) for s in sizes]
    imgs[-1].save(out/'icon.ico', format='ICO', append_images=imgs[:-1][::-1])
    im.save(assets/'icon.png')
    imgs[-1].save(assets/'icon.ico', format='ICO', append_images=imgs[:-1][::-1])
    print('icon refreshed', (out/'icon.ico').stat().st_size)
else:
    print('icon source missing')
"@

Write-Host "== Install PyInstaller =="
& $VenvPip install -q "pyinstaller>=6.0"

Write-Host "== PyInstaller (onedir) =="
& $VenvPython -m PyInstaller --noconfirm --clean "packaging\lcd-monitor-mini.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }

$Exe = Join-Path $Root "dist\lcd-monitor-mini\lcd-monitor-mini.exe"
if (-not (Test-Path $Exe)) { throw "Missing $Exe" }
Write-Host "Built: $Exe"

# Also place recovery scripts next to exe for recovery.py install_dir fallback
$DistScripts = Join-Path $Root "dist\lcd-monitor-mini\scripts"
New-Item -ItemType Directory -Force -Path $DistScripts | Out-Null
Copy-Item -Force "scripts\reset-display.ps1","scripts\disable-usbmonitor.ps1" $DistScripts

Write-Host "== Inno Setup (optional) =="
$Iscc = @(
    "${env:LocalAppData}\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($Iscc) {
    Write-Host "Compiling with $Iscc"
    $issArgs = @("packaging\lcd-monitor-mini.iss")
    if ($Version) {
        $issArgs = @("/DMyAppVersion=$Version") + $issArgs
        Write-Host "Inno MyAppVersion=$Version"
    }
    & $Iscc @issArgs
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed: $LASTEXITCODE" }
    Get-ChildItem "dist\lcd-monitor-mini-Setup-*.exe" | ForEach-Object { Write-Host "Installer: $($_.FullName)" }
} else {
    Write-Warning "Inno Setup 6 not found (ISCC.exe). Onedir is ready; install Inno to build Setup.exe."
    Write-Host "Download: https://jrsoftware.org/isinfo.php"
}

Write-Host "Done."
