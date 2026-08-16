"""Rev A serial protocol constants and helpers."""
from __future__ import annotations

BAUD = 115200
WIDTH = 320
HEIGHT = 480
CHUNK = WIDTH * 8  # 2560

CMD_HELLO = 69
CMD_RESET = 101
CMD_CLEAR = 102
CMD_SCREEN_OFF = 108
CMD_SCREEN_ON = 109
CMD_SET_BRIGHTNESS = 110
CMD_SET_ORIENTATION = 121
CMD_DISPLAY_BITMAP = 197

# Matches vendor Orientation enum (lcd_comm.py) — not sequential.
ORIENT_PORTRAIT = 0
ORIENT_REVERSE_PORTRAIT = 1
ORIENT_LANDSCAPE = 2
ORIENT_REVERSE_LANDSCAPE = 3

VID = 0x1A86
PID = 0x5722
SERIAL_ID = "USB35INCHIPSV2"


def build_cmd(x: int, y: int, ex: int, ey: int, cmd: int) -> bytes:
    buf = bytearray(6)
    buf[0] = (x >> 2) & 0xFF
    buf[1] = (((x & 3) << 6) + (y >> 4)) & 0xFF
    buf[2] = (((y & 15) << 4) + (ex >> 6)) & 0xFF
    buf[3] = (((ex & 63) << 2) + (ey >> 8)) & 0xFF
    buf[4] = ey & 0xFF
    buf[5] = cmd & 0xFF
    return bytes(buf)
