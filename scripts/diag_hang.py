"""Diagnose Theme Studio / LCD hangs. Writes timing log to userdata.

Usage:
  .\\.venv\\Scripts\\python.exe .\\scripts\\diag_hang.py
"""
from __future__ import annotations

import logging
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.display_session import DisplaySession
from app.paths import data_dir, ensure_user_data
from app.ui.theme_studio import ThemeStudioWindow


def main() -> int:
    ensure_user_data()
    log_path = data_dir() / "diag_hang.log"
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8", mode="w"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )
    log = logging.getLogger("diag")
    log.info("diag start log=%s", log_path)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    t0 = time.perf_counter()
    session = DisplaySession()
    log.info("DisplaySession created in %.0fms", (time.perf_counter() - t0) * 1000)

    try:
        t1 = time.perf_counter()
        present = session.conn.device_present()
        log.info("device_present=%s (%.0fms)", present, (time.perf_counter() - t1) * 1000)
        if present:
            t2 = time.perf_counter()
            session.start()
            log.info(
                "session.start returned in %.0fms (COM connect is in background loop)",
                (time.perf_counter() - t2) * 1000,
            )
        else:
            log.warning("device not present — continuing without session loop")
    except Exception:
        log.exception("session.start failed")

    hb = QTimer()
    hb.setInterval(500)
    n = {"i": 0}

    def on_hb() -> None:
        n["i"] += 1
        log.info(
            "UI_ALIVE #%s phase=%s ready=%s paused=%s",
            n["i"],
            session.ui_phase,
            session.conn.is_ready,
            session.conn.is_paused,
        )
        if n["i"] >= 24:
            log.info("diag finished cleanly")
            session.stop()
            app.quit()

    hb.timeout.connect(on_hb)

    try:
        t3 = time.perf_counter()
        log.info("creating ThemeStudioWindow…")
        studio = ThemeStudioWindow(session)
        log.info("ThemeStudioWindow created in %.0fms", (time.perf_counter() - t3) * 1000)
        studio.show()
        log.info("ThemeStudio shown")
    except Exception:
        log.exception("ThemeStudio create/show failed")
        session.stop()
        return 1

    def do_preview() -> None:
        log.info("calling studio.preview()…")
        t4 = time.perf_counter()
        try:
            studio.preview()
            log.info("studio.preview() returned in %.0fms", (time.perf_counter() - t4) * 1000)
        except Exception:
            log.exception("preview raised")

    QTimer.singleShot(2000, do_preview)
    hb.start()
    log.info("entering app.exec")
    code = app.exec()
    session.stop()
    log.info("diag exit code=%s", code)
    print(f"\nLog written to: {log_path}")
    return int(code)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise
