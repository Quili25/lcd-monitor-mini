"""Single-flight ConnectionManager for Rev A USB serial LCD."""
from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Callable, Optional

import serial
from PIL import Image
from serial.tools.list_ports import comports

from app import protocol as P

log = logging.getLogger("turing.connection")

ProgressCb = Callable[[int, int], None]


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    SENDING = "sending"
    ERROR = "error"


class ConnectionError(RuntimeError):
    pass


def find_port(preferred: str = "AUTO") -> Optional[str]:
    if preferred and preferred.upper() != "AUTO":
        return preferred
    for p in comports():
        if p.serial_number == P.SERIAL_ID:
            return p.device
        if p.vid == P.VID and p.pid == P.PID:
            return p.device
    return None


def _open_serial(
    port: str,
    baud: int,
    *,
    timeout: float = 2.0,
    open_timeout_s: float = 4.0,
    rtscts: bool = True,
) -> serial.Serial:
    """Open serial with a hard deadline — Windows can block forever if COM is busy."""
    holder: dict[str, object] = {}
    cancel = threading.Event()

    def _worker() -> None:
        ser: Optional[serial.Serial] = None
        try:
            # write_timeout=None: enforce deadline in _write_flush_locked (RTS/CTS-safe).
            ser = serial.Serial(
                port,
                baud,
                timeout=timeout,
                write_timeout=None,
                rtscts=rtscts,
            )
            if cancel.is_set():
                try:
                    ser.close()
                except Exception:
                    pass
                return
            holder["ser"] = ser
        except Exception as exc:  # noqa: BLE001 — surface to joiner
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass
            holder["err"] = exc

    t = threading.Thread(target=_worker, name=f"serial-open-{port}", daemon=True)
    t.start()
    t.join(open_timeout_s)
    if t.is_alive():
        cancel.set()
        t.join(1.0)
        raise ConnectionError(f"opening {port} timed out after {open_timeout_s:.0f}s (port busy?)")
    if "err" in holder:
        raise ConnectionError(str(holder["err"])) from holder["err"]  # type: ignore[arg-type]
    ser = holder.get("ser")
    if not isinstance(ser, serial.Serial):
        raise ConnectionError(f"opening {port} failed")
    return ser


def _image_to_rgb565(image: Image.Image) -> bytes:
    # Local copy to avoid depending on vendor path at import time for core
    import numpy as np

    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    rgb = np.asarray(image)
    rgb = rgb.reshape((image.size[1] * image.size[0], -1))
    r = rgb[:, 0].astype(np.uint16) >> 3
    g = rgb[:, 1].astype(np.uint16) >> 2
    b = rgb[:, 2].astype(np.uint16) >> 3
    rgb565 = (r << 11) | (g << 5) | b
    return rgb565.astype("<u2").tobytes()


class ConnectionManager:
    """Owns the serial port. All LCD I/O must go through this class."""

    def __init__(self, port: str = "AUTO", width: int = P.WIDTH, height: int = P.HEIGHT):
        self.port_pref = port
        self.width = width
        self.height = height
        self._ser: Optional[serial.Serial] = None
        self._lock = threading.RLock()
        self._pause = threading.Event()
        self._pause.clear()
        self._idle_blank = False
        self.state = ConnectionState.DISCONNECTED
        self.last_error: str = ""
        self.write_watchdog_s = 5.0
        self.orientation = P.ORIENT_PORTRAIT

    @property
    def is_ready(self) -> bool:
        return self.state == ConnectionState.READY and self._ser is not None and self._ser.is_open

    def pause(self) -> None:
        """Ask background senders (session loop) to idle; does not block this thread."""
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    @property
    def is_paused(self) -> bool:
        return self._pause.is_set()

    def set_idle_blank(self, blank: bool) -> None:
        """When True, bitmap pushes are skipped so the panel stays off while locked."""
        self._idle_blank = bool(blank)

    def wait_if_paused(self, timeout: float = 30.0, stop_event: Optional[threading.Event] = None) -> bool:
        """For session loop only: block until resume. Returns False on timeout/stop."""
        if not self._pause.is_set():
            return True
        end = time.monotonic() + timeout
        while self._pause.is_set():
            if stop_event is not None and stop_event.is_set():
                return False
            if time.monotonic() >= end:
                return False
            time.sleep(0.05)
        return True

    def connect(self) -> str:
        with self._lock:
            if self.is_ready:
                assert self._ser is not None
                return self._ser.portstr
            self.state = ConnectionState.CONNECTING
            port = find_port(self.port_pref)
            if not port:
                self.state = ConnectionState.ERROR
                self.last_error = "device not found"
                raise ConnectionError(self.last_error)
            try:
                # Rev A requires RTS/CTS; no-flow is only a recovery fallback.
                try:
                    ser = _open_serial(port, P.BAUD, timeout=2.0, open_timeout_s=4.0, rtscts=True)
                    log.info("opened %s with RTS/CTS", port)
                except Exception as first_exc:
                    log.warning("open with RTS/CTS failed (%s); retry without flow control", first_exc)
                    ser = _open_serial(port, P.BAUD, timeout=2.0, open_timeout_s=4.0, rtscts=False)
                    log.info("opened %s without RTS/CTS (fallback)", port)
                try:
                    ser.dtr = True
                    ser.rts = True
                except Exception:
                    pass
                time.sleep(0.15)
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                self._ser = ser
                resp = self._hello_locked()
                log.info("connected %s hello=%s", port, list(resp))
                self._screen_on_locked()
                self.state = ConnectionState.READY
                self.last_error = ""
                return port
            except Exception as exc:
                self.last_error = str(exc)
                self.state = ConnectionState.ERROR
                self._close_locked()
                raise ConnectionError(self.last_error) from exc

    def disconnect(self) -> None:
        with self._lock:
            self._close_locked()
            self.state = ConnectionState.DISCONNECTED

    def reconnect(self) -> str:
        with self._lock:
            self._close_locked()
        time.sleep(0.3)
        return self.connect()

    def set_brightness(self, percent: int) -> None:
        percent = max(0, min(100, int(percent)))
        level = int(255 - (percent / 100) * 255)
        with self._lock:
            self._ensure_ready_locked()
            self._write_flush_locked(P.build_cmd(level, 0, 0, 0, P.CMD_SET_BRIGHTNESS))

    def screen_on(self) -> None:
        with self._lock:
            self._ensure_ready_locked()
            self._screen_on_locked()

    def screen_off(self) -> None:
        with self._lock:
            self._ensure_ready_locked()
            self._write_flush_locked(P.build_cmd(0, 0, 0, 0, P.CMD_SCREEN_OFF))
            # Some firmware ignores SCREEN_OFF alone; force backlight down too.
            self._write_flush_locked(P.build_cmd(0, 0, 0, 0, P.CMD_SET_BRIGHTNESS))

    def set_orientation(self, orientation: int = P.ORIENT_PORTRAIT) -> None:
        """Set panel orientation. Values match vendor Orientation enum."""
        self.orientation = int(orientation)
        aw, ah = self.active_size
        buf = bytearray(16)
        buf[5] = P.CMD_SET_ORIENTATION
        buf[6] = self.orientation + 100
        buf[7] = (aw >> 8) & 0xFF
        buf[8] = aw & 0xFF
        buf[9] = (ah >> 8) & 0xFF
        buf[10] = ah & 0xFF
        with self._lock:
            self._ensure_ready_locked()
            self._write_flush_locked(bytes(buf))

    @property
    def active_size(self) -> tuple[int, int]:
        """Logical framebuffer size for current orientation (portrait native = width x height)."""
        if self.orientation in (P.ORIENT_LANDSCAPE, P.ORIENT_REVERSE_LANDSCAPE):
            return self.height, self.width
        return self.width, self.height

    def send_image(
        self,
        image: Image.Image,
        *,
        progress: Optional[ProgressCb] = None,
        x: int = 0,
        y: int = 0,
    ) -> None:
        aw, ah = self.active_size
        if image.size != (aw, ah) and (x, y) == (0, 0):
            image = image.resize((aw, ah))
        # Pause is for the session loop only — UI/stress callers pause then send themselves.
        with self._lock:
            if self._idle_blank:
                return
            self._ensure_ready_locked()
            self.state = ConnectionState.SENDING
            try:
                self._send_image_locked(image, progress=progress, x=x, y=y)
                self.state = ConnectionState.READY
            except Exception as exc:
                self.last_error = str(exc)
                self.state = ConnectionState.ERROR
                raise

    def send_image_safe(self, image: Image.Image, *, retries: int = 1) -> bool:
        for attempt in range(retries + 1):
            try:
                self.send_image(image)
                return True
            except Exception as exc:
                log.warning("send_image attempt %s failed: %s", attempt + 1, exc)
                try:
                    self.reconnect()
                except Exception as rexc:
                    log.error("reconnect failed: %s", rexc)
                    return False
        return False

    def device_present(self) -> bool:
        return find_port(self.port_pref) is not None

    # --- locked helpers ---

    def _ensure_ready_locked(self) -> None:
        if self._ser is None or not self._ser.is_open:
            raise ConnectionError("not connected")

    def _close_locked(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def _write_flush_locked(self, data: bytes) -> None:
        assert self._ser is not None
        err: dict[str, BaseException] = {}

        def _do_write() -> None:
            try:
                assert self._ser is not None
                self._ser.write(data)
                self._ser.flush()
            except BaseException as exc:  # noqa: BLE001
                err["e"] = exc

        t = threading.Thread(target=_do_write, name="serial-write", daemon=True)
        t.start()
        t.join(self.write_watchdog_s)
        if t.is_alive():
            # Port is wedged — force close so the next connect can recover.
            self._close_locked()
            self.state = ConnectionState.ERROR
            raise ConnectionError("write watchdog exceeded (COM wedged)")
        if "e" in err:
            raise err["e"]

    def _hello_locked(self) -> bytes:
        assert self._ser is not None
        self._write_flush_locked(bytes([P.CMD_HELLO] * 6))
        time.sleep(0.2)
        resp = self._ser.read(6)
        self._ser.reset_input_buffer()
        return resp

    def _screen_on_locked(self) -> None:
        self._write_flush_locked(P.build_cmd(0, 0, 0, 0, P.CMD_SCREEN_ON))

    def _send_image_locked(
        self,
        image: Image.Image,
        *,
        progress: Optional[ProgressCb],
        x: int,
        y: int,
    ) -> None:
        w, h = image.size
        x1, y1 = x + w - 1, y + h - 1
        data = _image_to_rgb565(image.convert("RGB"))
        self._write_flush_locked(P.build_cmd(x, y, x1, y1, P.CMD_DISPLAY_BITMAP))
        # Chunk by active scan width (320 portrait / 480 landscape), same as vendor Rev A.
        chunk = self.active_size[0] * 8
        total = len(data)
        nchunks = (total + chunk - 1) // chunk
        for i, off in enumerate(range(0, total, chunk)):
            if self._idle_blank:
                return
            piece = data[off : off + chunk]
            self._write_flush_locked(piece)
            if progress:
                progress(i + 1, nchunks)
