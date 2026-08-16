# Re-enable vendor UsbMonitor scheduled task (stops competing with lcd-monitor-mini if you switch back).
# Stop lcd-monitor-mini first so COM is free.

$ErrorActionPreference = "Continue"

Write-Host "Tip: stop lcd-monitor-mini (tray Exit or scripts/stop.ps1) before starting UsbMonitor."

$task = Get-ScheduledTask -TaskName "UsbMonitor" -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "Scheduled task 'UsbMonitor' not found."
    Write-Host "You can still launch: & 'C:\Program Files (x86)\35inchENG\UsbMonitor.exe'"
} else {
    try {
        Enable-ScheduledTask -TaskName "UsbMonitor" | Out-Null
        Write-Host "Scheduled task enabled. State: $((Get-ScheduledTask -TaskName 'UsbMonitor').State)"
        Write-Host "It will run at next logon, or start now with: Start-ScheduledTask -TaskName UsbMonitor"
    } catch {
        Write-Warning "Could not enable task (try Run as Administrator): $($_.Exception.Message)"
    }
}
