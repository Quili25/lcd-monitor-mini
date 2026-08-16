"""Display session: metrics loop + theme rendering over ConnectionManager."""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Optional

from PIL import Image

from app import protocol as P
from app.config_store import get_nested, load_config, save_config
from app.connection import ConnectionManager
from app.metrics import MetricsService
from app.renderer import render_theme, set_anim_tuning
from app.theme_service import load_theme

log = logging.getLogger("turing.session")

# Defaults: light on CPU/COM while still feeling live.
DEFAULT_INTERVAL_S = 0.8
ECO_INTERVAL_S = 1.0
SMOOTH_INTERVAL_S = 0.55


class DisplaySession:
    def __init__(self) -> None:
        self.config = load_config()
        port = get_nested(self.config, "config", "COM_PORT", default="AUTO")
        self.conn = ConnectionManager(port=port)
        eth = get_nested(self.config, "config", "ETH", default="Ethernet") or "Ethernet"
        city = str(get_nested(self.config, "config", "WEATHER_CITY", default="") or "")
        self.metrics = MetricsService(eth_name=str(eth), weather_city=city)
        self.theme_name = str(get_nested(self.config, "config", "THEME", default="Default"))
        self.theme = load_theme(self.theme_name)
        self.brightness = int(get_nested(self.config, "display", "BRIGHTNESS", default=30))
        self.orientation = str(
            get_nested(self.config, "display", "DISPLAY_ORIENTATION", default="portrait") or "portrait"
        ).lower()
        if self.orientation not in ("portrait", "landscape"):
            self.orientation = "portrait"
        self.flip = bool(get_nested(self.config, "display", "DISPLAY_REVERSE", default=False))
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._running = False
        self.interval_s = DEFAULT_INTERVAL_S
        self.eco_mode = True
        self.skip_unchanged_frames = True
        self.last_status = "idle"
        self.ui_phase = "idle"  # idle | connected | updating | error | disconnected
        self.send_progress = 0
        self.last_error = ""
        self._preview_hold = False
        self.ui_busy = False  # True only during Apply / Reconnect (shows progress in UI)
        self._system_idle = False
        self.blank_when_idle = bool(
            get_nested(self.config, "display", "BLANK_WHEN_IDLE", default=True)
        )
        self._last_frame_fp: Optional[bytes] = None
        self._apply_perf_from_config()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def system_idle(self) -> bool:
        return self._system_idle

    def set_blank_when_idle(self, enabled: bool) -> None:
        self.blank_when_idle = bool(enabled)
        self.config.setdefault("display", {})["BLANK_WHEN_IDLE"] = self.blank_when_idle
        save_config(self.config)

    def _apply_perf_from_config(self) -> None:
        """Load eco / refresh / anim tuning from config.yaml."""
        disp = self.config.setdefault("display", {})
        # Default eco on for low resource use; Smooth is opt-in.
        self.eco_mode = bool(disp.get("ECO_MODE", True))
        self.skip_unchanged_frames = bool(disp.get("SKIP_UNCHANGED_FRAMES", True))
        raw_interval = disp.get("REFRESH_INTERVAL_S")
        if raw_interval is not None:
            try:
                self.interval_s = max(0.35, min(2.5, float(raw_interval)))
            except (TypeError, ValueError):
                self.interval_s = ECO_INTERVAL_S if self.eco_mode else SMOOTH_INTERVAL_S
        else:
            self.interval_s = ECO_INTERVAL_S if self.eco_mode else SMOOTH_INTERVAL_S
        if self.eco_mode:
            set_anim_tuning(period_s=float(disp.get("ANIM_PERIOD_S", 5.0) or 5.0), steps=int(disp.get("ANIM_STEPS", 5) or 5))
        else:
            set_anim_tuning(period_s=float(disp.get("ANIM_PERIOD_S", 2.8) or 2.8), steps=int(disp.get("ANIM_STEPS", 8) or 8))
        log.info(
            "perf eco=%s interval=%.2fs skip_unchanged=%s",
            self.eco_mode,
            self.interval_s,
            self.skip_unchanged_frames,
        )

    def set_eco_mode(self, enabled: bool) -> None:
        self.eco_mode = bool(enabled)
        disp = self.config.setdefault("display", {})
        disp["ECO_MODE"] = self.eco_mode
        # Clear explicit interval so mode defaults apply unless user set one later.
        if "REFRESH_INTERVAL_S" in disp and disp.get("REFRESH_INTERVAL_S") in (
            DEFAULT_INTERVAL_S,
            ECO_INTERVAL_S,
            SMOOTH_INTERVAL_S,
            0.45,
        ):
            disp.pop("REFRESH_INTERVAL_S", None)
        save_config(self.config)
        self._apply_perf_from_config()
        self.invalidate_frame_cache()

    def invalidate_frame_cache(self) -> None:
        self._last_frame_fp = None

    @staticmethod
    def _frame_fingerprint(image: Image.Image) -> bytes:
        return hashlib.blake2b(image.tobytes(), digest_size=16).digest()

    def suspend_display(self, reason: str = "") -> None:
        """PC locked / sleeping / display off — pause updates and blank the panel."""
        if not self.blank_when_idle:
            return
        if self._system_idle:
            return
        self._system_idle = True
        log.info("suspend display (%s)", reason or "idle")
        self.conn.set_idle_blank(True)
        self.conn.pause()
        if not self.ui_busy:
            self.ui_phase = "idle" if not self._running else "connected"
        self.last_status = f"blank:{reason or 'idle'}"

        def _blank() -> None:
            try:
                if self.conn.is_ready:
                    self.conn.screen_off()
            except Exception as exc:
                log.warning("screen_off failed: %s", exc)

        threading.Thread(target=_blank, name="lcd-blank", daemon=True).start()

    def resume_display(self, reason: str = "") -> None:
        """PC unlocked / awake — turn panel back on and refresh (never blocks UI)."""
        if not self._system_idle:
            return
        self._system_idle = False
        log.info("resume display (%s)", reason or "active")
        self.conn.set_idle_blank(False)

        def _wake() -> None:
            try:
                if not self.conn.is_ready:
                    if self.conn.device_present():
                        self.conn.connect()
                if self.conn.is_ready:
                    self.conn.screen_on()
                    self.conn.set_brightness(self.brightness)
                    self.conn.set_orientation(self.protocol_orientation())
                    if self._running:
                        frame = self.render_frame()
                        self.conn.send_image(frame)
                        self._last_frame_fp = self._frame_fingerprint(frame)
                    if not self.ui_busy:
                        self.ui_phase = "connected"
                    self.last_status = "ok"
            except Exception as exc:
                log.warning("resume display failed: %s", exc)
                self.last_error = str(exc)
                try:
                    if self._running:
                        self.reconnect()
                except Exception:
                    pass
            finally:
                self.conn.resume()

        threading.Thread(target=_wake, name="lcd-wake", daemon=True).start()

    def protocol_orientation(self) -> int:
        if self.orientation == "landscape":
            return P.ORIENT_REVERSE_LANDSCAPE if self.flip else P.ORIENT_LANDSCAPE
        return P.ORIENT_REVERSE_PORTRAIT if self.flip else P.ORIENT_PORTRAIT

    def render_frame(self) -> Image.Image:
        """Render theme; rotate only when session orientation differs from theme canvas size."""
        frame = render_theme(self.theme, self.metrics.snapshot())
        if self.orientation == "landscape" and frame.size == (320, 480):
            # Portrait-designed theme → rotate to fill landscape panel
            frame = frame.rotate(90, expand=True)
        elif self.orientation == "portrait" and frame.size == (480, 320):
            # Landscape-designed theme on portrait session → rotate to portrait
            frame = frame.rotate(-90, expand=True)
        return frame

    def start(self) -> None:
        """Start the background session loop. Never blocks on COM (connect is in-loop)."""
        if self._running:
            return
        self.config = load_config()
        self.conn.port_pref = str(get_nested(self.config, "config", "COM_PORT", default="AUTO"))
        self.theme_name = str(get_nested(self.config, "config", "THEME", default="Default"))
        self.theme = load_theme(self.theme_name)
        self.brightness = int(get_nested(self.config, "display", "BRIGHTNESS", default=30))
        self.orientation = str(
            get_nested(self.config, "display", "DISPLAY_ORIENTATION", default=self.orientation) or "portrait"
        ).lower()
        self.flip = bool(get_nested(self.config, "display", "DISPLAY_REVERSE", default=self.flip))
        self.blank_when_idle = bool(
            get_nested(self.config, "display", "BLANK_WHEN_IDLE", default=True)
        )
        self._apply_perf_from_config()
        self.invalidate_frame_cache()
        self._system_idle = False
        self._stop.clear()
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="display-session", daemon=True)
        self._thread.start()
        self.last_status = "running"
        self.ui_phase = "connected"
        self.send_progress = 0
        self.last_error = ""
        log.info(
            "session started theme=%s orient=%s flip=%s interval=%.2fs eco=%s",
            self.theme_name,
            self.orientation,
            self.flip,
            self.interval_s,
            self.eco_mode,
        )

    def stop(self) -> None:
        self._stop.set()
        self._running = False
        # Unblock session loop if paused for preview/apply.
        try:
            self.conn.resume()
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        try:
            self.metrics.stop()
        except Exception:
            pass
        try:
            self.conn.disconnect()
        except Exception:
            pass
        self.last_status = "stopped"
        self.ui_phase = "idle"
        self.send_progress = 0
        log.info("session stopped")

    def reconnect(self) -> None:
        was = self._running
        if was:
            self._stop.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5)
            self._running = False
        self.conn.reconnect()
        self.conn.set_brightness(self.brightness)
        self.conn.set_orientation(self.protocol_orientation())
        if was:
            self._stop.clear()
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="display-session", daemon=True)
            self._thread.start()
            self.last_status = "running"

    def set_brightness(self, percent: int) -> None:
        self.brightness = percent
        self.config.setdefault("display", {})["BRIGHTNESS"] = percent
        save_config(self.config)
        if self.conn.is_ready:
            self.conn.pause()
            try:
                self.conn.set_brightness(percent)
            finally:
                self.conn.resume()

    def set_display_geometry(self, orientation: str, flip: bool) -> None:
        orientation = orientation.lower().strip()
        if orientation not in ("portrait", "landscape"):
            orientation = "portrait"
        self.orientation = orientation
        self.flip = flip
        self.config.setdefault("display", {})["DISPLAY_ORIENTATION"] = orientation
        self.config.setdefault("display", {})["DISPLAY_REVERSE"] = flip
        save_config(self.config)
        self.apply_panel_orientation(push_frame=True)

    def apply_panel_orientation(self, *, push_frame: bool = True) -> None:
        self.invalidate_frame_cache()
        self.conn.pause()
        try:
            if not self.conn.is_ready:
                self.conn.connect()
            self.conn.set_orientation(self.protocol_orientation())
            if push_frame:
                frame = self.render_frame()
                self.conn.send_image(frame, progress=self._progress_cb if self.ui_busy else None)
                self._last_frame_fp = self._frame_fingerprint(frame)
        finally:
            self.conn.resume()

    def set_theme(self, name: str) -> None:
        theme = load_theme(name)
        self.conn.pause()
        try:
            self.theme_name = name
            self.theme = theme
            self.config.setdefault("config", {})["THEME"] = name
            save_config(self.config)
            if not self.conn.is_ready:
                self.conn.connect()
            self.conn.set_orientation(self.protocol_orientation())
            frame = self.render_frame()
            self.conn.send_image(frame, progress=self._progress_cb if self.ui_busy else None)
            self._last_frame_fp = self._frame_fingerprint(frame)
        finally:
            self.conn.resume()
        self.last_status = f"theme={name}"

    def set_flip(self, reverse: bool) -> None:
        self.set_display_geometry(self.orientation, reverse)

    def begin_busy(self) -> None:
        """User-visible progress (Apply / Reconnect only)."""
        self.ui_busy = True
        self.ui_phase = "updating"
        self.send_progress = 0

    def end_busy(self) -> None:
        self.ui_busy = False
        self.send_progress = 0
        if self._running and self.conn.is_ready:
            self.ui_phase = "connected"
        elif self._running:
            self.ui_phase = "disconnected"
        else:
            self.ui_phase = "idle"

    def preview_image(self, image, *, hold: bool = True) -> None:
        """Push a one-shot frame. If hold=True, pause the session loop until end_preview()."""
        self.conn.pause()
        self._preview_hold = hold
        try:
            if not self.conn.is_ready:
                self.conn.connect()
            frame = image
            # Match panel orientation to the frame size (studio may design landscape or portrait).
            if frame.size == (480, 320):
                orient = P.ORIENT_REVERSE_LANDSCAPE if self.flip else P.ORIENT_LANDSCAPE
            elif frame.size == (320, 480) and self.orientation == "landscape":
                frame = frame.rotate(90, expand=True)
                orient = P.ORIENT_REVERSE_LANDSCAPE if self.flip else P.ORIENT_LANDSCAPE
            else:
                orient = P.ORIENT_REVERSE_PORTRAIT if self.flip else P.ORIENT_PORTRAIT
            self.conn.set_orientation(orient)
            self.conn.send_image(frame)
        except Exception as exc:
            self.ui_phase = "error"
            self.last_error = str(exc)
            self.last_status = f"error: {exc}"
            raise
        finally:
            if not hold:
                self.conn.resume()
                self._preview_hold = False

    def end_preview(self) -> None:
        if self._preview_hold:
            self._preview_hold = False
            self.conn.resume()
        if not self.ui_busy:
            self.ui_phase = "connected" if self._running else "idle"
            self.send_progress = 0

    def _progress_cb(self, i: int, n: int) -> None:
        if self.ui_busy:
            self.send_progress = int(100 * i / max(1, n))
            self.ui_phase = "updating"
            # Do NOT call QApplication.processEvents() here — it re-enters the UI
            # from the display thread and freezes Theme Studio / Settings.

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self._system_idle:
                    self._stop.wait(0.5)
                    continue
                if self.conn.is_paused:
                    if not self.conn.wait_if_paused(30.0, stop_event=self._stop):
                        continue
                if not self.conn.device_present():
                    if not self.ui_busy:
                        self.ui_phase = "disconnected"
                    self.last_status = "device missing"
                    time.sleep(1.0)
                    continue
                if not self.conn.is_ready:
                    self.conn.connect()
                    self.conn.set_brightness(self.brightness)
                    self.conn.set_orientation(self.protocol_orientation())
                frame = self.render_frame()
                if self.conn.is_paused or self._system_idle:
                    continue
                if self.skip_unchanged_frames and not self.ui_busy:
                    fp = self._frame_fingerprint(frame)
                    if fp == self._last_frame_fp:
                        self.last_status = "ok"
                        self.last_error = ""
                        if not self.ui_busy:
                            self.ui_phase = "connected"
                        self._stop.wait(self.interval_s)
                        continue
                    self._last_frame_fp = fp
                else:
                    self._last_frame_fp = self._frame_fingerprint(frame)
                # Background refresh — silent (no Updating UI)
                self.conn.send_image(frame, progress=self._progress_cb if self.ui_busy else None)
                if not self.ui_busy:
                    self.ui_phase = "connected"
                    self.send_progress = 0
                self.last_status = "ok"
                self.last_error = ""
            except Exception as exc:
                if self._system_idle:
                    self._stop.wait(0.5)
                    continue
                self.ui_phase = "error"
                self.last_error = str(exc)
                self.last_status = f"error: {exc}"
                log.exception("session loop error")
                time.sleep(1.5)
                try:
                    self.conn.reconnect()
                    self.conn.set_orientation(self.protocol_orientation())
                except Exception:
                    pass
            self._stop.wait(self.interval_s)
