"""Quick Rev A hello/smoke test for Turing 3.5\" (USB35INCHIPSV2)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "turing-smart-screen-python"
sys.path.insert(0, str(VENDOR))

from library.lcd.lcd_comm_rev_a import LcdCommRevA  # noqa: E402


def main() -> int:
    port = LcdCommRevA.auto_detect_com_port()
    print("auto_port=", port)
    if not port:
        print("No Turing Rev A device found (USB35INCHIPSV2 / 1A86:5722)")
        return 1

    lcd = LcdCommRevA(com_port=port, display_width=320, display_height=480)
    print("sub_revision=", getattr(lcd, "sub_revision", None))
    print("size=", lcd.get_width(), "x", lcd.get_height())
    lcd.ScreenOff()
    lcd.ScreenOn()
    lcd.SetBrightness(level=20)
    lcd.closeSerial()
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
