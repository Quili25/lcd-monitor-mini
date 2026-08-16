# Install or remove Windows Startup shortcut for lcd-monitor-mini (no admin needed).
param(
    [ValidateSet("install", "uninstall", "status")]
    [string]$Action = "install"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Startup = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $Startup "lcd-monitor-mini.lnk"
$RunScript = Join-Path $PSScriptRoot "run-hidden.vbs"

switch ($Action) {
    "uninstall" {
        if (Test-Path $ShortcutPath) {
            Remove-Item -Force $ShortcutPath
            Write-Host "Removed $ShortcutPath"
        } else {
            Write-Host "No startup shortcut present."
        }
    }
    "status" {
        if (Test-Path $ShortcutPath) {
            Write-Host "Installed: $ShortcutPath"
        } else {
            Write-Host "Not installed."
        }
    }
    "install" {
        if (-not (Test-Path $RunScript)) {
            throw "Missing $RunScript"
        }
        $shell = New-Object -ComObject WScript.Shell
        $sc = $shell.CreateShortcut($ShortcutPath)
        $sc.TargetPath = $RunScript
        $sc.WorkingDirectory = $Root
        $sc.WindowStyle = 7
        $sc.Description = "lcd-monitor-mini system monitor (3.5 inch USB LCD)"
        $sc.Save()
        Write-Host "Installed startup shortcut: $ShortcutPath"
        Write-Host "It launches scripts\run-hidden.vbs which kills UsbMonitor then starts the Python monitor."
    }
}
