"""Stress: connect, send theme frames repeatedly, optional reconnects."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.connection import ConnectionManager
from app.metrics import MetricsService
from app.renderer import render_theme
from app.theme_service import list_themes, load_theme


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=20)
    parser.add_argument("--theme", default="Default")
    args = parser.parse_args()

    themes = [args.theme]
    all_themes = list_themes()
    if len(all_themes) > 1:
        themes = [args.theme] + [t for t in all_themes if t != args.theme][:3]

    conn = ConnectionManager()
    metrics = MetricsService()
    print(f"connecting...", flush=True)
    port = conn.connect()
    print(f"port={port}", flush=True)
    conn.set_brightness(30)

    for i in range(args.cycles):
        name = themes[i % len(themes)]
        theme = load_theme(name)
        frame = render_theme(theme, metrics.snapshot())
        t0 = time.perf_counter()
        conn.pause()
        try:
            conn.send_image(frame)
        finally:
            conn.resume()
        dt = time.perf_counter() - t0
        print(f"cycle {i + 1}/{args.cycles} theme={name} {dt:.2f}s", flush=True)

    conn.disconnect()
    print("STRESS_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
