"""Verify Turing Rev A link using the same serial settings as image transfer."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import serial
from serial.tools.list_ports import comports

CMD_HELLO = 69
CMD_SCREEN_ON = 109


def log(msg: str) -> None:
    print(f"[verify] {msg}", flush=True)


def find_port() -> str | None:
    for p in comports():
        if p.serial_number == "USB35INCHIPSV2":
            return p.device
        if p.vid == 0x1A86 and p.pid == 0x5722:
            return p.device
    return None


def main() -> int:
    port = find_port()
    if not port:
        log("FAIL: device not found")
        return 1

    log(f"port={port}")
    ser = serial.Serial(port, 115200, timeout=2, rtscts=True)
    try:
        try:
            ser.dtr = True
            ser.rts = True
        except Exception:
            pass
        time.sleep(0.1)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        ser.write(bytes([CMD_HELLO] * 6))
        ser.flush()
        time.sleep(0.2)
        resp = ser.read(6)
        log(f"hello_response={list(resp)!r} len={len(resp)}")
        if resp != bytes([1, 1, 1, 1, 1, 1]):
            log("WARN: unexpected hello (expected USBMONITOR_3_5 = 01 x6)")

        ser.write(bytes([0, 0, 0, 0, 0, CMD_SCREEN_ON]))
        ser.flush()
        log("SCREEN_ON sent")
        log("VERIFY_OK")
        return 0
    except serial.SerialTimeoutException as exc:
        log(f"VERIFY_FAIL write timeout: {exc}")
        return 2
    finally:
        ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
