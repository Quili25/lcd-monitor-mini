"""Quick Rev A hello/smoke test via app.connection."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.connection import ConnectionManager  # noqa: E402


def main() -> int:
    conn = ConnectionManager(port="AUTO")
    if not conn.device_present():
        print("No Rev A device found (USB35INCHIPSV2 / 1A86:5722)")
        return 1
    try:
        port = conn.connect()
        print("port=", port)
        conn.screen_on()
        conn.set_brightness(20)
        conn.screen_off()
        print("SMOKE_OK")
        return 0
    except Exception as exc:
        print("SMOKE_FAIL:", exc)
        return 1
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
