"""Send calibration image using the known-good Rev A transfer pattern.

Matches:
- turing-smart-screen-python (rtscts=True, chunks = width*8)
- viktorkav/usb-lcd-dashboard shared.py (flush after every chunk)
- UsbMonitor.exe (SerialPort + DtrEnable/RtsEnable + Flush)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import serial
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "turing-smart-screen-python"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(VENDOR))

from library.lcd.serialize import image_to_RGB565  # noqa: E402

W, H = 320, 480
BAUD = 115200
CHUNK = W * 8  # 2560 bytes — vendor + community standard
OUT = ROOT / "themes" / "omar" / "calibration.png"

CMD_HELLO = 69
CMD_SCREEN_ON = 109
CMD_SET_BRIGHTNESS = 110
CMD_DISPLAY_BITMAP = 197


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_reset() -> None:
    if os.environ.get("TURING_SKIP_RESET", "").strip() in ("1", "true", "yes"):
        log("TURING_SKIP_RESET set - skipping reset-display")
        return
    ps1 = SCRIPTS / "reset-display.ps1"
    log("running reset-display.ps1 -SoftOnly ...")
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1),
            "-SoftOnly",
        ],
        cwd=str(ROOT),
    )
    if completed.returncode != 0:
        raise SystemExit(f"reset-display failed with code {completed.returncode}")
    time.sleep(0.5)


def _font(size: int):
    font_path = VENDOR / "res" / "fonts" / "jetbrains-mono" / "JetBrainsMono-Bold.ttf"
    try:
        return ImageFont.truetype(str(font_path), size)
    except OSError:
        return ImageFont.load_default()


def build_calibration() -> Image.Image:
    img = Image.new("RGB", (W, H), (16, 20, 28))
    d = ImageDraw.Draw(img)
    font_sm = _font(14)
    font_md = _font(18)

    d.rectangle([0, 0, W - 1, H - 1], outline=(255, 255, 255), width=1)
    d.rectangle([4, 4, W - 5, H - 5], outline=(255, 80, 80), width=1)
    d.rectangle([8, 8, W - 9, H - 9], outline=(80, 200, 255), width=1)
    d.rectangle([16, 16, W - 17, H - 17], outline=(120, 255, 140), width=1)

    for x0, y0, dx, dy in (
        (0, 0, 1, 1),
        (W - 1, 0, -1, 1),
        (0, H - 1, 1, -1),
        (W - 1, H - 1, -1, -1),
    ):
        d.line([(x0, y0), (x0 + dx * 24, y0)], fill=(255, 220, 0), width=3)
        d.line([(x0, y0), (x0, y0 + dy * 24)], fill=(255, 220, 0), width=3)

    cx, cy = W // 2, H // 2
    d.line([(cx - 40, cy), (cx + 40, cy)], fill=(255, 255, 255), width=1)
    d.line([(cx, cy - 40), (cx, cy + 40)], fill=(255, 255, 255), width=1)
    d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], outline=(255, 180, 0), width=2)

    for x in range(0, W, 40):
        d.line([(x, 0), (x, 10)], fill=(180, 180, 200), width=1)
        d.line([(x, H - 1), (x, H - 11)], fill=(180, 180, 200), width=1)
    for y in range(0, H, 40):
        d.line([(0, y), (10, y)], fill=(180, 180, 200), width=1)
        d.line([(W - 1, y), (W - 11, y)], fill=(180, 180, 200), width=1)

    d.text((24, 24), "TOP-LEFT 0,0", font=font_sm, fill=(255, 255, 255))
    d.text((W - 150, 24), f"TOP-RIGHT {W-1},0", font=font_sm, fill=(255, 255, 255))
    d.text((24, H - 40), f"BOT-LEFT 0,{H-1}", font=font_sm, fill=(255, 255, 255))
    d.text((W - 170, H - 40), f"BOT-RIGHT {W-1},{H-1}", font=font_sm, fill=(255, 255, 255))

    d.text((cx - 70, 60), "CALIBRATION", font=font_md, fill=(90, 180, 255))
    d.text((cx - 90, 88), f"{W}x{H} portrait", font=font_sm, fill=(180, 200, 220))
    d.text((cx - 110, cy + 20), "white=edge 1px", font=font_sm, fill=(255, 255, 255))
    d.text((cx - 110, cy + 40), "red=4  cyan=8  green=16", font=font_sm, fill=(200, 210, 220))
    d.text((cx - 100, cy + 60), "yellow=corners", font=font_sm, fill=(255, 220, 0))
    return img


def build_cmd(x: int, y: int, ex: int, ey: int, cmd: int) -> bytes:
    buf = bytearray(6)
    buf[0] = (x >> 2) & 0xFF
    buf[1] = (((x & 3) << 6) + (y >> 4)) & 0xFF
    buf[2] = (((y & 15) << 4) + (ex >> 6)) & 0xFF
    buf[3] = (((ex & 63) << 2) + (ey >> 8)) & 0xFF
    buf[4] = ey & 0xFF
    buf[5] = cmd
    return bytes(buf)


def open_screen(port: str) -> serial.Serial:
    # Exact community/vendor pattern: 115200 + hardware RTS/CTS, no write_timeout
    ser = serial.Serial(port, BAUD, timeout=2, rtscts=True)
    try:
        ser.dtr = True
        ser.rts = True
    except Exception:
        pass
    time.sleep(0.1)
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    return ser


def hello(ser: serial.Serial) -> bytes:
    ser.write(bytes([CMD_HELLO] * 6))
    ser.flush()
    time.sleep(0.2)
    resp = ser.read(6)
    ser.reset_input_buffer()
    return resp


def send_image(ser: serial.Serial, img: Image.Image) -> None:
    data = image_to_RGB565(img.convert("RGB"), "little")
    total = len(data)
    log(f"RGB565 bytes={total} chunk={CHUNK}")

    ser.write(build_cmd(0, 0, W - 1, H - 1, CMD_DISPLAY_BITMAP))
    ser.flush()

    t0 = time.perf_counter()
    sent = 0
    nchunks = (total + CHUNK - 1) // CHUNK
    for i, off in enumerate(range(0, total, CHUNK)):
        piece = data[off : off + CHUNK]
        ser.write(piece)
        ser.flush()  # required — without this Windows usbser stalls mid-frame
        sent += len(piece)
        if i % 10 == 0 or i == nchunks - 1:
            pct = int(sent * 100 / total)
            log(f"  chunk {i + 1}/{nchunks}  {pct}%")
    log(f"frame sent in {time.perf_counter() - t0:.2f}s")


def find_port() -> str:
    from serial.tools.list_ports import comports

    for p in comports():
        if p.serial_number == "USB35INCHIPSV2":
            return p.device
        if p.vid == 0x1A86 and p.pid == 0x5722:
            return p.device
    return "COM4"


def main() -> int:
    ensure_reset()

    img = build_calibration()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    log(f"saved {OUT}")

    port = find_port()
    log(f"port={port}")

    ser = open_screen(port)
    try:
        log("hello...")
        resp = hello(ser)
        log(f"hello_response={list(resp)!r}")

        log("screen on + brightness...")
        ser.write(build_cmd(0, 0, 0, 0, CMD_SCREEN_ON))
        ser.flush()
        # brightness: 0=brightest .. 255=darkest ; ~30% -> absolute
        level = int(255 - (30 / 100) * 255)
        ser.write(build_cmd(level, 0, 0, 0, CMD_SET_BRIGHTNESS))
        ser.flush()
        time.sleep(0.05)

        log("sending full-frame with flush-per-chunk (vendor pattern)...")
        send_image(ser, img)
        log("CALIBRATION_OK - check borders/corners on the panel")
        return 0
    finally:
        ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
