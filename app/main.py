"""lcd-monitor-mini product entrypoint."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Dev: ensure repo root on path
if not getattr(sys, "frozen", False):
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication

from app.display_session import DisplaySession
from app.paths import data_dir, ensure_user_data
from app.power_watch import WindowsIdleWatch
from app.recovery import soft_reset_python, stop_usbmonitor
from app.ui.settings import SettingsWindow, install_tray
from app.ui.theme_studio import ThemeStudioWindow


def _setup_logging() -> Path:
    ensure_user_data()
    log_path = data_dir() / "app.log"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    already = False
    for h in root.handlers:
        if isinstance(h, logging.FileHandler) and Path(getattr(h, "baseFilename", "")) == log_path:
            already = True
            break
    if not already:
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        root.addHandler(sh)
    return log_path


def main() -> int:
    log_path = _setup_logging()
    log = logging.getLogger("turing")
    log.info("starting lcd-monitor-mini log=%s", log_path)

    # Single instance (avoids duplicate tray icons). Stale locks from crashes are cleared.
    lock = QLockFile(str(data_dir() / "lcd-monitor-mini.lock"))
    lock.setStaleLockTime(30_000)
    if not lock.tryLock(100):
        log.info("another instance is already running; exiting")
        return 0

    try:
        stop_usbmonitor()
        soft_reset_python()
    except Exception as exc:
        log.warning("pre-start free COM: %s", exc)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("lcd-monitor-mini")
    app.setOrganizationName("lcd-monitor-mini")
    app.setProperty("_turing_instance_lock", lock)

    from app.ui.settings import APP_STYLE

    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)

    session = DisplaySession()
    studio_ref: dict = {"win": None}

    def open_studio(on_applied=None) -> None:
        if studio_ref["win"] is None:
            studio_ref["win"] = ThemeStudioWindow(session)
        studio_ref["win"].on_applied = on_applied
        studio_ref["win"].show()
        studio_ref["win"].raise_()
        studio_ref["win"].activateWindow()

    window = SettingsWindow(session, open_studio)
    tray = install_tray(app, window, session)
    window.show()

    idle_watch = WindowsIdleWatch(window)
    # winId is valid after show; register session/power notifications
    idle_watch.start(window)
    idle_watch.suspended.connect(session.suspend_display)
    idle_watch.resumed.connect(session.resume_display)
    app.aboutToQuit.connect(idle_watch.stop)

    def _auto_start() -> None:
        try:
            if session.conn.device_present():
                session.start()
                log.info("auto-start session ok")
            else:
                log.warning("auto-start skipped: device not present")
        except Exception as exc:
            log.warning("auto-start skipped: %s", exc)

    # Defer COM work until the Qt event loop is running (never block show()).
    QTimer.singleShot(0, _auto_start)

    code = app.exec()
    idle_watch.stop()
    tray.hide()
    session.stop()
    lock.unlock()
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
