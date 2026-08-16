"""System metrics without admin (psutil + GPUtil when available).

Heavy work (process scan, WMI/temp, weather, nvidia-smi) runs on a background
worker. ``snapshot()`` only does cheap psutil reads + returns cached values so
the display/UI threads never stall.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import psutil

log = logging.getLogger("turing.metrics")


@dataclass
class Metrics:
    cpu_percent: float = 0.0
    cpu_temp: Optional[float] = None
    cpu_freq_ghz: Optional[float] = None
    ram_percent: float = 0.0
    ram_used_gb: float = 0.0
    gpu_percent: Optional[float] = None
    gpu_temp: Optional[float] = None
    gpu_mem_percent: Optional[float] = None
    gpu_mem_used_gb: Optional[float] = None
    gpu_mem_total_gb: Optional[float] = None
    disk_percent: float = 0.0
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    net_up_kb: float = 0.0
    net_down_kb: float = 0.0
    volume_percent: Optional[float] = None
    time_str: str = ""
    date_str: str = ""
    weather_text: str = ""
    top_by_cpu: list[str] = field(default_factory=list)
    top_by_memory: list[str] = field(default_factory=list)
    top_by_disk: list[str] = field(default_factory=list)
    top_by_network: list[str] = field(default_factory=list)
    top_by_gpu: list[str] = field(default_factory=list)


@dataclass
class MetricsService:
    eth_name: str = "Ethernet"
    weather_city: str = ""
    _last_net: Optional[tuple[float, float, float]] = field(default=None, repr=False)
    _weather_cache: tuple[float, str] = field(default=(0.0, ""), repr=False)
    _top_cache_at: float = field(default=0.0, repr=False)
    _top_cache: dict[str, list[str]] = field(default_factory=dict, repr=False)
    _gpu_top_cache_at: float = field(default=0.0, repr=False)
    _gpu_top_cache: list[str] = field(default_factory=list, repr=False)
    _cpu_temp_cache: tuple[float, Optional[float]] = field(default=(0.0, None), repr=False)
    _cpu_primed: bool = field(default=False, repr=False)
    _gpu_cache: tuple[float, Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]] = field(
        default=(0.0, None, None, None, None, None), repr=False
    )
    _volume_cache: tuple[float, Optional[float]] = field(default=(0.0, None), repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _worker_stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _worker: Optional[threading.Thread] = field(default=None, repr=False)
    _started: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        try:
            psutil.cpu_percent(interval=None)
            self._cpu_primed = True
        except Exception:
            self._cpu_primed = False
        self.start()

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._worker_stop.clear()
        self._worker = threading.Thread(target=self._worker_loop, name="metrics-worker", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._worker_stop.set()
        t = self._worker
        if t and t.is_alive():
            t.join(timeout=2.0)
        self._worker = None
        self._started = False

    def snapshot(self) -> Metrics:
        """Fast path only — never sleeps, never scans all processes, never hits network/WMI."""
        self.start()
        m = Metrics()
        try:
            if not self._cpu_primed:
                psutil.cpu_percent(interval=None)
                self._cpu_primed = True
            m.cpu_percent = float(psutil.cpu_percent(interval=None))
        except Exception:
            m.cpu_percent = 0.0
        try:
            freq = psutil.cpu_freq()
            if freq:
                m.cpu_freq_ghz = round(freq.current / 1000.0, 2)
        except Exception:
            pass
        try:
            vm = psutil.virtual_memory()
            m.ram_percent = float(vm.percent)
            m.ram_used_gb = round(vm.used / (1024**3), 1)
        except Exception:
            pass
        try:
            usage = psutil.disk_usage("C:\\")
            m.disk_percent = float(usage.percent)
            m.disk_used_gb = round(usage.used / (1024**3), 1)
            m.disk_total_gb = round(usage.total / (1024**3), 1)
        except Exception:
            m.disk_percent = 0.0
        self._fill_net(m)
        now = datetime.now()
        m.time_str = now.strftime("%H:%M:%S")
        m.date_str = now.strftime("%Y-%m-%d")

        with self._lock:
            _at, temp = self._cpu_temp_cache
            m.cpu_temp = temp
            _gat, gp, gt, gmp, gmu, gmt = self._gpu_cache
            m.gpu_percent = gp
            m.gpu_temp = gt
            m.gpu_mem_percent = gmp
            m.gpu_mem_used_gb = gmu
            m.gpu_mem_total_gb = gmt
            _vat, vol = self._volume_cache
            m.volume_percent = vol
            _wat, weather = self._weather_cache
            m.weather_text = weather
            tops = self._top_cache
            m.top_by_cpu = list(tops.get("cpu", []))
            m.top_by_memory = list(tops.get("memory", []))
            m.top_by_disk = list(tops.get("disk", []))
            m.top_by_network = list(tops.get("network", []))
            m.top_by_gpu = list(tops.get("gpu", []))
        return m

    def _worker_loop(self) -> None:
        # Stagger expensive jobs so we don't spike CPU/GIL all at once.
        tick = 0
        while not self._worker_stop.wait(1.0):
            tick += 1
            try:
                if tick % 2 == 0:
                    self._refresh_gpu()
                if tick % 3 == 0:
                    self._refresh_volume()
                if tick % 5 == 0:
                    self._refresh_cpu_temp()
                if tick % 4 == 0:
                    self._refresh_top_processes()
                if tick % 30 == 0:
                    self._refresh_weather()
            except Exception:
                log.exception("metrics worker tick failed")

    def _refresh_cpu_temp(self) -> None:
        # Cache misses (including None) for 45s so we never hammer WMI/PowerShell.
        now = time.monotonic()
        with self._lock:
            cached_at, _cached = self._cpu_temp_cache
            if now - cached_at < 45.0 and cached_at > 0:
                return
        value = self._read_cpu_temp()
        with self._lock:
            self._cpu_temp_cache = (now, value)

    def _read_cpu_temp(self) -> Optional[float]:
        try:
            temps = psutil.sensors_temperatures() or {}
            prefer = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz")
            for key in prefer:
                entries = temps.get(key) or []
                for e in entries:
                    if e.current and 0 < float(e.current) < 125:
                        return float(e.current)
            for entries in temps.values():
                for e in entries:
                    if e.current and 0 < float(e.current) < 125:
                        return float(e.current)
        except Exception:
            pass

        for ns in ("root\\LibreHardwareMonitor", "root\\OpenHardwareMonitor"):
            t = self._wmi_cpu_temp(ns)
            if t is not None:
                return t

        return self._acpi_thermal_temp()

    def _wmi_cpu_temp(self, namespace: str) -> Optional[float]:
        try:
            import wmi  # type: ignore

            client = wmi.WMI(namespace=namespace)
            best: Optional[float] = None
            for sensor in client.Sensor():
                stype = str(getattr(sensor, "SensorType", "") or "")
                name = str(getattr(sensor, "Name", "") or "")
                if stype.lower() != "temperature":
                    continue
                val = getattr(sensor, "Value", None)
                if val is None:
                    continue
                temp = float(val)
                if not (1 < temp < 125):
                    continue
                lname = name.lower()
                if "cpu" in lname or "tctl" in lname or "tdie" in lname or "package" in lname:
                    return temp
                if best is None:
                    best = temp
            return best
        except Exception:
            return None

    def _acpi_thermal_temp(self) -> Optional[float]:
        try:
            from app.winproc import run_silent

            completed = run_silent(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
                    "-ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty CurrentTemperature)",
                ],
                timeout=1.5,
            )
            raw = (completed.stdout or "").strip()
            if not raw:
                return None
            kelvin_tenths = float(raw)
            celsius = kelvin_tenths / 10.0 - 273.15
            if 1 < celsius < 125:
                return round(celsius, 1)
        except Exception:
            return None
        return None

    def _refresh_gpu(self) -> None:
        gp = gt = gmp = gmu = gmt = None
        try:
            import GPUtil

            gpus = GPUtil.getGPUs()
            if gpus:
                g = gpus[0]
                gp = float(g.load * 100)
                gt = float(g.temperature) if g.temperature is not None else None
                if g.memoryTotal:
                    gmp = float(g.memoryUtil * 100)
                    gmu = round(float(g.memoryUsed) / 1024.0, 1)
                    gmt = round(float(g.memoryTotal) / 1024.0, 1)
        except Exception:
            pass
        with self._lock:
            self._gpu_cache = (time.monotonic(), gp, gt, gmp, gmu, gmt)

    def _fill_net(self, m: Metrics) -> None:
        try:
            counters = psutil.net_io_counters(pernic=True)
            nic = None
            if self.eth_name and self.eth_name in counters:
                nic = counters[self.eth_name]
            else:
                for name, c in counters.items():
                    if not name.lower().startswith("loopback") and c.bytes_recv > 0:
                        nic = c
                        break
            if nic is None:
                return
            now = time.monotonic()
            if self._last_net is None:
                self._last_net = (now, nic.bytes_sent, nic.bytes_recv)
                return
            t0, up0, down0 = self._last_net
            dt = max(0.001, now - t0)
            m.net_up_kb = (nic.bytes_sent - up0) / dt / 1024.0
            m.net_down_kb = (nic.bytes_recv - down0) / dt / 1024.0
            self._last_net = (now, nic.bytes_sent, nic.bytes_recv)
        except Exception:
            return

    def _refresh_volume(self) -> None:
        value: Optional[float] = None
        try:
            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            value = float(volume.GetMasterVolumeLevelScalar() * 100)
        except Exception:
            value = None
        with self._lock:
            self._volume_cache = (time.monotonic(), value)

    def _refresh_weather(self) -> None:
        now = time.monotonic()
        with self._lock:
            cached_at, cached = self._weather_cache
            if cached and now - cached_at < 600:
                return
        text = ""
        try:
            import urllib.parse
            import urllib.request

            from app.location import weather_query

            token = (self.weather_city or "").strip() or weather_query()
            if token:
                path = urllib.parse.quote(token, safe="~,.")
                url = f"https://wttr.in/{path}?format=%t+%C"
            else:
                url = "https://wttr.in/?format=%t+%C"
            req = urllib.request.Request(url, headers={"User-Agent": "lcd-monitor-mini"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                text = resp.read().decode("utf-8", errors="replace").strip()
            if text and "Unknown" not in text:
                with self._lock:
                    self._weather_cache = (now, text)
                return
        except Exception:
            pass
        with self._lock:
            if not self._weather_cache[1]:
                self._weather_cache = (now, cached if cached else "")

    def _refresh_top_processes(self) -> None:
        now = time.monotonic()
        with self._lock:
            if self._top_cache and now - self._top_cache_at < 4.0:
                return
        try:
            # Prime CPU counters (worker thread only — sleep is OK here).
            for p in psutil.process_iter(["pid"]):
                try:
                    p.cpu_percent(interval=None)
                except (psutil.Error, OSError):
                    pass
            time.sleep(0.08)
            rows: list[tuple[str, float, float, float, float]] = []
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    info = p.info
                    name = (info.get("name") or "").strip()
                    if not name or name.lower() in ("system idle process", "system", "registry"):
                        continue
                    cpu = float(p.cpu_percent(interval=None) or 0.0)
                    mem = float(p.memory_info().rss)
                    disk = 0.0
                    net = 0.0
                    try:
                        io = p.io_counters()
                        disk = float(io.read_bytes + io.write_bytes)
                        other = getattr(io, "other_bytes", 0) or 0
                        net = float(other)
                    except (psutil.Error, OSError, AttributeError):
                        pass
                    rows.append((name, cpu, mem, disk, net))
                except (psutil.Error, OSError):
                    continue

            def top_names(key_idx: int) -> list[str]:
                ranked = sorted(rows, key=lambda r: r[key_idx], reverse=True)
                names: list[str] = []
                seen: set[str] = set()
                for name, *_rest in ranked:
                    display = path_name(name)
                    key = display.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    names.append(display)
                    if len(names) >= 3:
                        break
                return names

            cache = {
                "cpu": top_names(1),
                "memory": top_names(2),
                "disk": top_names(3),
                "network": top_names(4),
                "gpu": self._top_gpu_processes() or top_names(1)[:3],
            }
            with self._lock:
                self._top_cache = cache
                self._top_cache_at = now
        except Exception:
            return

    def _top_gpu_processes(self) -> list[str]:
        now = time.monotonic()
        with self._lock:
            if self._gpu_top_cache and now - self._gpu_top_cache_at < 15.0:
                return list(self._gpu_top_cache)
        try:
            from app.winproc import run_silent

            completed = run_silent(
                [
                    "nvidia-smi",
                    "--query-compute-apps=process_name",
                    "--format=csv,noheader",
                ],
                timeout=1.5,
            )
            if completed.returncode != 0:
                return []
            names: list[str] = []
            seen: set[str] = set()
            for line in (completed.stdout or "").splitlines():
                name = path_name(line.strip())
                if not name or "insufficient" in name.lower() or name.startswith("["):
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                names.append(name)
                if len(names) >= 3:
                    break
            with self._lock:
                self._gpu_top_cache = names
                self._gpu_top_cache_at = now
            return names
        except Exception:
            return []


def path_name(name: str) -> str:
    """Strip path / extension noise from process display name."""
    base = name.replace("\\", "/").split("/")[-1]
    if base.lower().endswith(".exe"):
        base = base[:-4]
    return base or name


# Back-compat alias used by older call sites / tests
PathName = path_name


def list_nics() -> list[str]:
    try:
        return sorted(psutil.net_io_counters(pernic=True).keys())
    except Exception:
        return []
