"""Soft/hard recovery for the USB serial LCD device."""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from app.winproc import run_silent

log = logging.getLogger("turing.recovery")


def _scripts_dir() -> Path:
    from app.paths import install_dir, is_frozen, resource_dir

    if is_frozen():
        bundled = resource_dir() / "scripts"
        if bundled.is_dir():
            return bundled
        return install_dir() / "scripts"
    return Path(__file__).resolve().parents[1] / "scripts"


def soft_reset(*, skip_verify: bool = True) -> int:
    """Kill COM holders; optionally skip HELLO verify."""
    ps1 = _scripts_dir() / "reset-display.ps1"
    if ps1.is_file():
        args = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(ps1),
            "-SoftOnly",
        ]
        if skip_verify:
            args.append("-SkipVerify")
        log.info("soft_reset: %s", " ".join(args))
        completed = run_silent(args)
        return int(completed.returncode)
    return soft_reset_python()


def soft_reset_python() -> int:
    """Kill UsbMonitor holders without PowerShell scripts.

    Does not terminate other lcd-monitor-mini instances (that left ghost tray icons).
    Single-instance lock in app.main prevents duplicate product processes.
    """
    try:
        import psutil
    except ImportError:
        return 1
    me = psutil.Process().pid
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
        try:
            if proc.pid == me:
                continue
            name = (proc.info.get("name") or "").lower()
            if name.startswith("usbmonitor"):
                proc.terminate()
        except (psutil.Error, OSError, TypeError):
            continue
    time.sleep(0.5)
    return 0


def hard_reset_elevated(*, then_calibrate: bool = False) -> int:
    """UAC prompt: enable/restart USB device."""
    ps1 = _scripts_dir() / "reset-display.ps1"
    if not ps1.is_file():
        log.error("reset-display.ps1 not found")
        return 1
    args = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-File",
        str(ps1),
        "-Elevate",
    ]
    if then_calibrate:
        args.append("-ThenCalibrate")
    log.info("hard_reset_elevated")
    completed = run_silent(args)
    return int(completed.returncode)


def stop_usbmonitor() -> None:
    """Stop vendor UsbMonitor process (best-effort)."""
    try:
        import psutil
    except ImportError:
        return
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info.get("name") or "").lower().startswith("usbmonitor"):
                proc.terminate()
        except (psutil.Error, OSError):
            continue


def stop_product_processes() -> None:
    """Best-effort stop of other lcd-monitor-mini workers (not self)."""
    if sys.platform != "win32":
        return
    try:
        import psutil
    except ImportError:
        return
    me = psutil.Process().pid
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
        try:
            if proc.pid == me:
                continue
            cmd = " ".join(proc.info.get("cmdline") or [])
            exe = proc.info.get("exe") or ""
            if "lcd-monitor-mini.exe" in exe.lower() or "turing-lcd.exe" in exe.lower() or (
                ("lcd-monitor-mini" in cmd or "turing-lcd" in cmd) and "app.main" in cmd
            ):
                proc.terminate()
        except (psutil.Error, OSError, TypeError):
            continue
