"""Autostart helper (Windows Startup folder shortcut)."""
from __future__ import annotations

import sys
from pathlib import Path

from app.paths import data_dir, exe_path, install_dir, is_frozen
from app.winproc import run_silent


def startup_shortcut_path() -> Path:
    appdata = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return appdata / "lcd-monitor-mini.lnk"


def is_autostart_enabled() -> bool:
    return startup_shortcut_path().is_file()


def set_autostart(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    shortcut = startup_shortcut_path()
    if not enabled:
        if shortcut.exists():
            shortcut.unlink(missing_ok=True)
        return

    if is_frozen():
        target = str(exe_path())
        workdir = str(install_dir())
        args = ""
    else:
        # Dev: launch pythonw -m app.main from repo
        root = install_dir()
        target = str(root / ".venv" / "Scripts" / "pythonw.exe")
        if not Path(target).is_file():
            target = str(root / ".venv" / "Scripts" / "python.exe")
        workdir = str(root)
        args = "-m app.main"

    # Escape for PowerShell single-quoted string
    def esc(s: str) -> str:
        return s.replace("'", "''")

    ps = f"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{esc(str(shortcut))}')
$s.TargetPath = '{esc(target)}'
$s.WorkingDirectory = '{esc(workdir)}'
$s.Arguments = '{esc(args)}'
$s.WindowStyle = 7
$s.Description = 'lcd-monitor-mini'
$s.Save()
"""
    run_silent(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-Command", ps],
        cwd=str(data_dir()),
    )
