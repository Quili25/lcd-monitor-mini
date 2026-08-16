# Stop vendor UsbMonitor and free COM port for lcd-monitor-mini.
# Disabling the scheduled task usually requires Administrator.

$ErrorActionPreference = "Continue"

Write-Host "Stopping UsbMonitor processes..."
Get-Process -Name "UsbMonitor" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "  Killing PID $($_.Id)"
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}

$task = Get-ScheduledTask -TaskName "UsbMonitor" -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "Scheduled task 'UsbMonitor' not found (already removed or never installed)."
} else {
    Write-Host "Current task state: $($task.State)"
    try {
        Disable-ScheduledTask -TaskName "UsbMonitor" -ErrorAction Stop | Out-Null
        Write-Host "Scheduled task disabled. State: $((Get-ScheduledTask -TaskName 'UsbMonitor').State)"
    } catch {
        Write-Warning "Could not disable scheduled task (Access Denied is normal without Admin)."
        Write-Warning "Workaround: scripts/run.ps1 kills UsbMonitor before starting lcd-monitor-mini."
        Write-Warning "To disable permanently, run this script elevated:"
        Write-Warning "  Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass -File ""$PSCommandPath""'"
    }
}

Write-Host "Done. COM port should be free for lcd-monitor-mini."
