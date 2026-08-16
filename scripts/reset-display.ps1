# Recover Turing 3.5" USB LCD when COM is stuck / hung mid-transfer.
# Steps: stop holders -> optional protocol note -> PnP disable/enable -> wait for COM -> HELLO check.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\reset-display.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\reset-display.ps1 -SkipVerify
#   powershell -ExecutionPolicy Bypass -File .\scripts\reset-display.ps1 -SoftOnly   # no PnP cycle

param(
    [switch]$SkipVerify,
    [switch]$SoftOnly,
    [switch]$Elevate,
    [switch]$ThenCalibrate
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$VidPid = "VID_1A86&PID_5722"

# Re-launch elevated when hard USB restart is required
if ($Elevate) {
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath)
    if ($SkipVerify) { $argList += '-SkipVerify' }
    if ($SoftOnly) { $argList += '-SoftOnly' }
    if ($ThenCalibrate) { $argList += '-ThenCalibrate' }
    Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $argList -Wait
    exit $LASTEXITCODE
}

function Write-Step([string]$msg) {
    Write-Host "[reset-display] $msg"
}

function Stop-ComHolders {
    Write-Step "Stopping UsbMonitor / lcd-monitor-mini Python holders..."
    Get-Process -Name "UsbMonitor" -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Step "  kill UsbMonitor PID $($_.Id)"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }

    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -match 'lcd-monitor-mini|turing-smart-screen-python|show_calibration|smoke_test|main\.py'
        } |
        ForEach-Object {
            Write-Step "  kill $($_.Name) PID $($_.ProcessId)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }

    # Also stop venv interpreters under this project (covers hung writes without cmdline match)
    Get-Process -Name "python", "pythonw" -ErrorAction SilentlyContinue |
        Where-Object {
            try { $_.Path -like "*\lcd-monitor-mini\.venv\*" } catch { $false }
        } |
        ForEach-Object {
            Write-Step "  kill venv $($_.ProcessName) PID $($_.Id)"
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }

    Start-Sleep -Seconds 1
}

function Get-TuringDevice {
    Get-PnpDevice -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -like "*$VidPid*" } |
        Select-Object -First 1
}

function Get-TuringComPort {
    $map = Get-ItemProperty "HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM" -ErrorAction SilentlyContinue
    if (-not $map) { return $null }

    # Prefer device with our serial / bus name via WMI
    $pnp = Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
        Where-Object { $_.DeviceID -like "*$VidPid*" -and $_.Name -match 'COM\d+' }
    if ($pnp -and $pnp.Name -match '\((COM\d+)\)') {
        return $Matches[1]
    }

    # Fallback: first USBSER* mapping
    foreach ($prop in $map.PSObject.Properties) {
        if ($prop.Name -like '*USBSER*' -or $prop.Name -like '*VCP*') {
            return [string]$prop.Value
        }
    }
    return $null
}

function Ensure-DeviceEnabled {
    $dev = Get-TuringDevice
    if (-not $dev) { return $false }

    # Refresh status
    $dev = Get-PnpDevice -InstanceId $dev.InstanceId -ErrorAction SilentlyContinue
    if ($dev.Status -eq 'OK') { return $true }

    Write-Step "Device status=$($dev.Status) problem=$($dev.Problem) - enabling..."
    $pnputil = Join-Path $env:SystemRoot "System32\pnputil.exe"
    if (Test-Path $pnputil) {
        $out = & $pnputil /enable-device $dev.InstanceId 2>&1 | Out-String
        Write-Host $out
    }
    try {
        Enable-PnpDevice -InstanceId $dev.InstanceId -Confirm:$false -ErrorAction Stop
    } catch {
        Write-Warning "Enable-PnpDevice: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 2
    $dev = Get-PnpDevice -InstanceId $dev.InstanceId -ErrorAction SilentlyContinue
    Write-Step "After enable: status=$($dev.Status) problem=$($dev.Problem)"
    return ($dev.Status -eq 'OK')
}

function Restart-TuringUsb {
    $dev = Get-TuringDevice
    if (-not $dev) {
        Write-Warning "Turing USB device not found ($VidPid). Plug the screen in."
        return $false
    }

    Write-Step "Found: $($dev.FriendlyName) [$($dev.Status)] problem=$($dev.Problem)"
    Write-Step "InstanceId: $($dev.InstanceId)"

    # If already disabled, enable first (do NOT disable again - that is what stuck us)
    if ($dev.Problem -eq 'CM_PROB_DISABLED' -or $dev.Status -eq 'Error') {
        Write-Step "Device is disabled/error - enable only (no disable cycle)"
        return (Ensure-DeviceEnabled)
    }

    $pnputil = Join-Path $env:SystemRoot "System32\pnputil.exe"
    if (Test-Path $pnputil) {
        Write-Step "pnputil /restart-device ..."
        $out = & $pnputil /restart-device $dev.InstanceId 2>&1 | Out-String
        Write-Host $out
        $failed = ($LASTEXITCODE -ne 0) -or ($out -match '(?i)acceso denegado|access denied|no se pudo|not connected|no est')
        if (-not $failed) {
            Start-Sleep -Seconds 2
            # restart can leave the node DISABLED on Windows - always re-enable
            return (Ensure-DeviceEnabled)
        }
        Write-Warning "pnputil restart failed (exit=$LASTEXITCODE). Trying enable-only recovery..."
        return (Ensure-DeviceEnabled)
    }

    return (Ensure-DeviceEnabled)
}

function Wait-ForCom([int]$seconds = 30) {
    Write-Step "Waiting for COM port (up to ${seconds}s)..."
    for ($i = 0; $i -lt $seconds; $i++) {
        $dev = Get-TuringDevice
        if ($dev -and ($dev.Problem -eq 'CM_PROB_DISABLED' -or $dev.Status -eq 'Error')) {
            if (($i % 5) -eq 0) { Ensure-DeviceEnabled | Out-Null }
        }
        $dev = Get-TuringDevice
        $com = $null
        # Prefer live enumeration via python/list if registry lags
        try {
            $py = & $VenvPython -c "from serial.tools.list_ports import comports
for p in comports():
    if p.serial_number=='USB35INCHIPSV2' or (p.vid==0x1A86 and p.pid==0x5722):
        print(p.device); break" 2>$null
            if ($py) { $com = $py.Trim() }
        } catch {}
        if (-not $com) { $com = Get-TuringComPort }

        $status = if ($dev) { $dev.Status } else { "missing" }
        if ($com -and $dev -and $status -eq 'OK') {
            Write-Step "COM ready: $com (device OK)"
            return $com
        }
        if (($i % 5) -eq 0) {
            Write-Step "  ... still waiting (status=$status problem=$($dev.Problem) com=$com)"
        }
        Start-Sleep -Seconds 1
    }
    Write-Warning "COM did not come back OK. If Status=Error/Disabled, run elevated enable:"
    Write-Warning "  powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Elevate -ThenCalibrate"
    return $null
}

# --- main ---
Stop-ComHolders

if (-not $SoftOnly) {
    $ok = Restart-TuringUsb
    if (-not $ok) {
        Write-Warning "Hardware restart incomplete. Soft continue - unplug/replug if verify fails."
    }
} else {
    Write-Step "SoftOnly: skipped USB PnP restart"
}

$com = Wait-ForCom
if (-not $com) {
    Write-Error "No Turing COM port. Unplug USB-C for 3s, plug back, re-run this script."
    exit 2
}

if ($SkipVerify) {
    Write-Step "SkipVerify: done (port=$com)"
    exit 0
}

if (-not (Test-Path $VenvPython)) {
    Write-Warning "No venv python; skipped HELLO verify. Port=$com"
    exit 0
}

Write-Step "HELLO verify via Python..."
& $VenvPython (Join-Path $PSScriptRoot "verify_display.py")
$code = $LASTEXITCODE
if ($code -ne 0) {
    exit $code
}

if ($ThenCalibrate) {
    Write-Step "VERIFY_OK - sending calibration image..."
    $env:TURING_SKIP_RESET = "1"
    & $VenvPython -u (Join-Path $PSScriptRoot "show_calibration.py")
    exit $LASTEXITCODE
}

exit 0
