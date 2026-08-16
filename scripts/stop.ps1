# Stop lcd-monitor-mini product processes.

Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe' OR Name = 'lcd-monitor-mini.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -match 'lcd-monitor-mini|turing-lcd|app\.main|show_calibration|smoke_test' -or
        $_.Name -eq 'lcd-monitor-mini.exe'
    } |
    ForEach-Object {
        Write-Host "Stopping PID $($_.ProcessId) ($($_.Name))"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Get-Process -Name "python","pythonw","lcd-monitor-mini","turing-lcd" -ErrorAction SilentlyContinue |
    Where-Object {
        try {
            $_.Path -like "*\lcd-monitor-mini*" -or $_.Path -like "*\turing-lcd*" -or
            $_.Name -in @("lcd-monitor-mini","turing-lcd")
        } catch { $false }
    } |
    ForEach-Object {
        Write-Host "Stopping $($_.ProcessName) PID $($_.Id)"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }

# Stale single-instance lock after force-kill
$lock = Join-Path $env:LOCALAPPDATA "lcd-monitor-mini\lcd-monitor-mini.lock"
if (Test-Path $lock) {
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
    Write-Host "Cleared stale lock"
}

Write-Host "Done."
