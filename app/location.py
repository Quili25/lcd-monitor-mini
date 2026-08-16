"""Resolve approximate location from Windows for weather."""
from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger("turing.location")

_cache: tuple[float, Optional[str]] = (0.0, None)


def weather_query(*, force: bool = False) -> str:
    """
    Return a wttr.in location token:
    - "~lat,lon" from Windows location services when available
    - "" for IP-based wttr.in fallback
    """
    global _cache
    now = time.monotonic()
    if not force and _cache[1] is not None and now - _cache[0] < 3600:
        return _cache[1]

    query = _windows_lat_lon_query() or ""
    _cache = (now, query)
    if query:
        log.info("weather location from Windows: %s", query)
    else:
        log.info("weather location: IP fallback (wttr.in)")
    return query


def _windows_lat_lon_query() -> Optional[str]:
    """Best-effort GeoCoordinateWatcher via PowerShell (no extra pip deps)."""
    ps = r"""
$ErrorActionPreference = 'Stop'
try {
  Add-Type -AssemblyName System.Device -ErrorAction Stop
  $w = New-Object System.Device.Location.GeoCoordinateWatcher
  $w.Start()
  $deadline = (Get-Date).AddSeconds(4)
  while ($w.Status -ne 'Ready' -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 200
  }
  if ($w.Permission -eq 'Denied') { exit 2 }
  $loc = $w.Position.Location
  if ($null -eq $loc -or $loc.IsUnknown) { exit 3 }
  Write-Output ("{0},{1}" -f $loc.Latitude, $loc.Longitude)
  $w.Stop()
  exit 0
} catch {
  exit 1
}
"""
    try:
        from app.winproc import run_silent

        completed = run_silent(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-Command",
                ps,
            ],
            timeout=8,
        )
        if completed.returncode != 0:
            return None
        line = (completed.stdout or "").strip().splitlines()
        if not line:
            return None
        latlon = line[-1].strip()
        parts = latlon.split(",")
        if len(parts) != 2:
            return None
        float(parts[0])
        float(parts[1])
        return f"~{latlon}"
    except Exception as exc:
        log.debug("windows geolocation failed: %s", exc)
        return None
