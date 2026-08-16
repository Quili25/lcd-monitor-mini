"""Silent subprocess helpers (no flashing console on Windows)."""
from __future__ import annotations

import subprocess
import sys
from typing import Any, Sequence


def run_silent(
    args: Sequence[str],
    *,
    timeout: float | None = None,
    text: bool = True,
    cwd: str | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[Any]:
    kwargs: dict[str, Any] = {
        "args": list(args),
        "capture_output": True,
        "text": text,
        "timeout": timeout,
        "check": check,
        "cwd": cwd,
    }
    if sys.platform == "win32":
        # Prevent brief cmd.exe / console flashes from child tools (nvidia-smi, powershell).
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE
            kwargs["startupinfo"] = si
        except Exception:
            pass
    return subprocess.run(**kwargs)
