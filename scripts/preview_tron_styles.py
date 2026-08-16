"""Preview TRON gauge/bar style proposals on the physical 3.5\" LCD.

Shows page 1 (6 gauges/rings) then page 2 (6 bars). Does not change Theme Studio.

Usage:
  powershell -ExecutionPolicy Bypass -File .\\scripts\\stop.ps1
  .\\.venv\\Scripts\\python.exe .\\scripts\\preview_tron_styles.py
  .\\.venv\\Scripts\\python.exe .\\scripts\\preview_tron_styles.py --page gauges
  .\\.venv\\Scripts\\python.exe .\\scripts\\preview_tron_styles.py --page bars
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import protocol as P
from app.connection import ConnectionManager
from app.paths import fonts_dir

W, H = 320, 480
BG = (6, 8, 14)
CYAN = (0, 220, 255)
BLUE = (40, 100, 255)
MAGENTA = (255, 60, 180)
WHITE = (235, 245, 255)
MUTED = (28, 36, 48)
DIM = (16, 22, 32)


def _font(size: int) -> ImageFont.ImageFont:
    path = fonts_dir() / "jetbrains-mono" / "JetBrainsMono-Bold.ttf"
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _rgba(rgb: tuple[int, int, int], a: int) -> tuple[int, int, int, int]:
    return (*rgb, max(0, min(255, int(a))))


def _paste(base: Image.Image, layer: Image.Image, xy: tuple[int, int]) -> None:
    region = base.crop((xy[0], xy[1], xy[0] + layer.width, xy[1] + layer.height)).convert("RGBA")
    region = Image.alpha_composite(region, layer)
    base.paste(region.convert("RGB"), xy)


def _label(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font: ImageFont.ImageFont) -> None:
    draw.text((x, y), text, font=font, fill=(140, 160, 190))


def _flat_arc(
    layer: Image.Image,
    cx: float,
    cy: float,
    r: float,
    start: float,
    end: float,
    width: float,
    color: tuple[int, int, int],
    alpha: int = 255,
) -> None:
    """Thick arc with flat radial ends (no Pillow round line-caps)."""
    if end <= start + 0.15:
        return
    w = max(1.0, float(width))
    ro = r + w / 2.0
    ri = max(0.0, r - w / 2.0)
    mask = Image.new("L", layer.size, 0)
    md = ImageDraw.Draw(mask)
    md.pieslice([cx - ro, cy - ro, cx + ro, cy + ro], start, end, fill=255)
    if ri > 0.5:
        md.ellipse([cx - ri, cy - ri, cx + ri, cy + ri], fill=0)
    tint = Image.new("RGBA", layer.size, _rgba(color, alpha))
    overlay = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    overlay.paste(tint, (0, 0), mask)
    composed = Image.alpha_composite(layer, overlay)
    layer.paste(composed)


def _arc_stroke(
    d: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    r: float,
    start: float,
    end: float,
    width: float,
    color: tuple[int, int, int],
    alpha: int = 255,
    *,
    caps: bool = False,
    layer: Image.Image | None = None,
) -> None:
    """Prefer flat annular arcs when ``layer`` is provided; else legacy arc(+optional caps)."""
    if layer is not None and not caps:
        _flat_arc(layer, cx, cy, r, start, end, width, color, alpha)
        return
    if end <= start + 0.15:
        return
    bbox = [int(cx - r), int(cy - r), int(cx + r), int(cy + r)]
    d.arc(bbox, start, end, fill=_rgba(color, alpha), width=max(1, int(round(width))))
    if caps:
        cap = max(1.0, width / 2.0)
        for deg in (start, end):
            rad = math.radians(deg)
            px, py = cx + r * math.cos(rad), cy + r * math.sin(rad)
            d.ellipse([px - cap, py - cap, px + cap, py + cap], fill=_rgba(color, alpha))


def _accent_ramp(color: tuple[int, int, int]) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    """Dim → accent → hot white mix, for ribbon-style gradients of any accent."""
    dim = _blend(color, (0, 12, 28), 0.45)
    hot = _blend(color, WHITE, 0.55)
    return dim, color, hot


def _gradient_arc(
    layer: Image.Image,
    cx: float,
    cy: float,
    r: float,
    start: float,
    end: float,
    width: float,
    color: tuple[int, int, int],
    phase: float = 0.0,
    *,
    alpha: int = 255,
) -> None:
    """Filled arc with accent ramp along the sweep (dim → accent → hot) + phase highlight."""
    if end <= start + 0.15:
        return
    span = end - start
    n = max(20, min(72, int(abs(span) / 3.5)))
    dim, mid, hot = _accent_ramp(color)
    sweep_t = (phase * 1.35) % 1.4 - 0.2
    for i in range(n):
        t0 = i / n
        t1 = (i + 1) / n
        a0 = start + span * t0
        a1 = start + span * t1
        if i < n - 1:
            a1 += 0.4  # tiny overlap kills hairline gaps between wedges
        t = (t0 + t1) * 0.5
        c = _blend(dim, mid, 0.2 + 0.8 * t)
        c = _blend(c, hot, max(0.0, t - 0.5) * 0.85)
        dist = abs(t - sweep_t) / 0.14
        c = _blend(c, hot, max(0.0, 1.0 - dist) * 0.55)
        _flat_arc(layer, cx, cy, r, a0, a1, width, c, alpha)


def _ramp_at(color: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """Sample accent ramp at t in [0, 1]."""
    dim, mid, hot = _accent_ramp(color)
    t = max(0.0, min(1.0, t))
    c = _blend(dim, mid, 0.2 + 0.8 * t)
    return _blend(c, hot, max(0.0, t - 0.5) * 0.85)


def _center_text(
    d: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
) -> None:
    """True visual center using font.getbbox when available."""
    try:
        bbox = font.getbbox(text)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), text, font=font, fill=fill)
        return
    except Exception:
        pass
    try:
        d.text((cx, cy), text, font=font, fill=fill, anchor="mm")
    except TypeError:
        bb = d.textbbox((0, 0), text, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        d.text((cx - tw / 2 - bb[0], cy - th / 2 - bb[1]), text, font=font, fill=fill)


def draw_g1_donut(
    base: Image.Image,
    x: int,
    y: int,
    size: int,
    pct: float,
    phase: float,
    *,
    font_size: int = 22,
    color: tuple[int, int, int] = CYAN,
) -> None:
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = cy = size / 2
    stroke = max(8, size // 7)
    r = size / 2 - stroke / 2 - 1
    _arc_stroke(d, cx, cy, r, 0, 360, stroke, MUTED, 220, caps=False, layer=layer)
    sweep = 360 * pct / 100.0
    if sweep > 0.5:
        _gradient_arc(layer, cx, cy, r, -90, -90 + sweep, stroke, color, phase)
    font = _font(font_size)
    _center_text(d, cx, cy, f"{pct:.0f}", font, _rgba(WHITE, 255))
    _paste(base, layer, (x, y))


def draw_g2_ticks(
    base: Image.Image,
    x: int,
    y: int,
    size: int,
    pct: float,
    phase: float,
    *,
    font_size: int = 22,
    color: tuple[int, int, int] = CYAN,
) -> None:
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = cy = size / 2
    ticks = 40
    filled = int(round(ticks * pct / 100.0))
    cascade = int(phase * (ticks + 3)) % (ticks + 3)
    for i in range(ticks):
        a = (i / ticks) * math.tau - math.pi / 2
        cos_a, sin_a = math.cos(a), math.sin(a)
        r0, r1 = size * 0.30, size * 0.46
        lit = i < filled
        w = 3 if lit else 2
        # Radial gradient per tick: dim at inner tip → hot at outer tip
        steps = max(8, int(r1 - r0))
        for s in range(steps):
            t0 = s / steps
            t1 = (s + 1) / steps
            rr0 = r0 + (r1 - r0) * t0
            rr1 = r0 + (r1 - r0) * t1
            if lit:
                col = _ramp_at(color, (t0 + t1) * 0.5)
                if i == cascade:
                    col = _blend(col, WHITE, 0.65)
                alpha = 255
            else:
                col = MUTED
                alpha = 160
            d.line(
                [cx + cos_a * rr0, cy + sin_a * rr0, cx + cos_a * rr1, cy + sin_a * rr1],
                fill=_rgba(col, alpha),
                width=w,
            )
    font = _font(font_size)
    _center_text(d, cx, cy, f"{pct:.0f}", font, _rgba(WHITE, 255))
    _paste(base, layer, (x, y))


def draw_g3_arc_ticks(
    base: Image.Image,
    x: int,
    y: int,
    size: int,
    pct: float,
    phase: float,
    *,
    font_size: int = 22,
    color: tuple[int, int, int] = MAGENTA,
) -> None:
    w = size
    h = int(size * 0.78)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = w / 2, h * 0.78
    stroke = max(7, size // 10)
    r = min(w, h) * 0.42
    _arc_stroke(d, cx, cy, r, 180, 360, stroke, MUTED, 220, caps=False, layer=layer)
    end = 180 + 180 * pct / 100.0
    if end > 180.5:
        _gradient_arc(layer, cx, cy, r, 180, end, stroke, color, phase)
    for i in range(9):
        ang = math.pi + (i / 8) * math.pi
        d.line(
            [
                cx + math.cos(ang) * (r + stroke * 0.55),
                cy + math.sin(ang) * (r + stroke * 0.55),
                cx + math.cos(ang) * (r + stroke * 0.95),
                cy + math.sin(ang) * (r + stroke * 0.95),
            ],
            fill=_rgba(WHITE, 90),
            width=1,
        )
    # Value baseline sits on the arc chord (graphic base at cy)
    font = _font(font_size)
    val = f"{pct:.0f}"
    try:
        bbox = font.getbbox(val)
        tw = bbox[2] - bbox[0]
        d.text((cx - tw / 2 - bbox[0], cy - bbox[3]), val, font=font, fill=_rgba(WHITE, 255))
    except Exception:
        bb = d.textbbox((0, 0), val, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        d.text((cx - tw / 2, cy - th), val, font=font, fill=_rgba(WHITE, 255))
    _paste(base, layer, (x, y))


def draw_g4_needle(
    base: Image.Image,
    x: int,
    y: int,
    size: int,
    pct: float,
    phase: float,
    *,
    font_size: int = 18,
    color: tuple[int, int, int] = CYAN,
) -> None:
    """Semicircle + needle; value bottom-anchored at the arc apex (grows up/sideways only)."""
    w, h = size, int(size * 0.72)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = w / 2, h * 0.88
    stroke = max(6, size // 12)
    r = min(w, h) * 0.48
    _arc_stroke(d, cx, cy, r, 180, 360, stroke, MUTED, 220, caps=False, layer=layer)
    end = 180 + 180 * pct / 100.0
    if end > 180.5:
        _gradient_arc(layer, cx, cy, r, 180, end, stroke, color, phase)
    tip = _ramp_at(color, pct / 100.0)
    ang = math.radians(end)
    nx = cx + math.cos(ang) * (r - stroke)
    ny = cy + math.sin(ang) * (r - stroke)
    d.line([cx, cy, nx, ny], fill=_rgba(tip, 255), width=2)
    d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=_rgba(WHITE, 255))
    _paste(base, layer, (x, y))
    # Bottom of glyphs just above arc apex — larger font grows up + sideways only
    gap = 4
    arc_top = y + cy - (r + stroke / 2.0)
    font = _font(font_size)
    val = f"{pct:.0f}"
    bd = ImageDraw.Draw(base)
    try:
        bbox = font.getbbox(val)
        tw = bbox[2] - bbox[0]
        tx = x + cx - tw / 2 - bbox[0]
        ty = arc_top - gap - bbox[3]
        bd.text((tx, ty), val, font=font, fill=WHITE)
    except Exception:
        bb = bd.textbbox((0, 0), val, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        bd.text((x + cx - tw / 2, arc_top - gap - th), val, font=font, fill=WHITE)


def draw_g5_dual(
    base: Image.Image,
    x: int,
    y: int,
    size: int,
    pct: float,
    phase: float,
    *,
    font_size: int = 22,
    color: tuple[int, int, int] = CYAN,
) -> None:
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = cy = size / 2.0
    dim, _mid, hot = _accent_ramp(color)
    for i in range(6, 0, -1):
        rr = size * 0.22 * (i / 6)
        col = _blend(dim, hot, i / 6)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=_rgba(col, 230))
    stroke = max(5, size // 12)
    r = size / 2 - stroke / 2 - 2
    _arc_stroke(d, cx, cy, r, 0, 360, stroke, MUTED, 200, caps=False, layer=layer)
    sweep = 360 * pct / 100.0
    if sweep > 0.5:
        _gradient_arc(layer, cx, cy, r, -90, -90 + sweep, stroke, color, phase)
    font = _font(font_size)
    _center_text(d, cx, cy, f"{pct:.0f}", font, _rgba(WHITE, 255))
    _paste(base, layer, (x, y))


def draw_g6_solid_dash(
    base: Image.Image,
    x: int,
    y: int,
    size: int,
    pct: float,
    phase: float,
    *,
    font_size: int = 18,
    color: tuple[int, int, int] = CYAN,
) -> None:
    """Ring graphic only; value is drawn below the widget on the base canvas."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = cy = size / 2
    stroke = max(8, size // 8)
    r = size / 2 - stroke / 2 - 2
    dim, mid, hot = _accent_ramp(color)
    d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=_rgba(mid, 255))
    d.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], outline=_rgba(hot, 200), width=2)
    d.ellipse([cx - 22, cy - 22, cx + 22, cy + 22], outline=_rgba(dim, 140), width=1)
    solid = max(40.0, min(300.0, 360.0 * pct / 100.0))
    _gradient_arc(layer, cx, cy, r, -90, -90 + solid, stroke, color, phase)
    rem_start = -90 + solid + 8
    rem_end = 270
    n = 10
    span = rem_end - rem_start
    if span > 10:
        for i in range(n):
            a0 = rem_start + span * (i / n)
            a1 = a0 + span / n * 0.45
            _arc_stroke(d, cx, cy, r, a0, a1, stroke * 0.85, MUTED, 200, caps=False, layer=layer)
    _paste(base, layer, (x, y))
    # Number below the graphic (not inside the ring)
    font = _font(font_size)
    val = f"{pct:.0f}"
    bd = ImageDraw.Draw(base)
    bb = bd.textbbox((0, 0), val, font=font)
    tw = bb[2] - bb[0]
    bd.text((x + (size - tw) / 2, y + size + 2), val, font=font, fill=WHITE)


def _gradient_fill_h(
    fill: Image.Image,
    fw: int,
    h: int,
    color: tuple[int, int, int],
    phase: float,
    *,
    y0: int = 2,
    y1: int | None = None,
) -> None:
    """Horizontal energy ramp + sweep highlight using accent color."""
    if fw <= 0:
        return
    dim, mid, hot = _accent_ramp(color)
    fd = ImageDraw.Draw(fill)
    y1 = h - 3 if y1 is None else y1
    sweep_x = (phase * 1.4 - 0.2) * fw
    for i in range(fw):
        t = i / max(1, fw - 1)
        c = _blend(dim, mid, 0.25 + 0.75 * t)
        dist = abs(i - sweep_x) / max(6.0, fw * 0.1)
        c = _blend(c, hot, max(0.0, 1.0 - dist) * 0.55)
        fd.line([(i, y0), (i, y1)], fill=_rgba(c, 255))


def _gradient_fill_v(
    fill: Image.Image,
    w: int,
    fh: int,
    color: tuple[int, int, int],
    phase: float,
) -> None:
    """Vertical energy ramp (base→tip) using accent color."""
    if fh <= 0:
        return
    dim, mid, hot = _accent_ramp(color)
    fd = ImageDraw.Draw(fill)
    sweep_y = (phase * 1.4 - 0.2) * fh
    for yy in range(fh):
        t = yy / max(1, fh - 1)
        c = _blend(dim, mid, 0.25 + 0.75 * t)
        dist = abs(yy - sweep_y) / max(6.0, fh * 0.1)
        c = _blend(c, hot, max(0.0, 1.0 - dist) * 0.55)
        fd.line([(2, fh - 1 - yy), (w - 3, fh - 1 - yy)], fill=_rgba(c, 255))


def draw_b1_ribbon(
    base: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    pct: float,
    phase: float,
    *,
    color: tuple[int, int, int] = CYAN,
) -> None:
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rad = h // 2
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=rad, fill=_rgba(DIM, 230))
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=rad, outline=_rgba(color, 110), width=1)
    fw = max(h, int(w * pct / 100.0)) if pct > 0 else 0
    if fw:
        fill = Image.new("RGBA", (fw, h), (0, 0, 0, 0))
        _gradient_fill_h(fill, fw, h, color, phase)
        mask = Image.new("L", (fw, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fw - 1, h - 1], radius=rad, fill=255)
        fr, fg, fb, fa = fill.split()
        fill = Image.merge("RGBA", (fr, fg, fb, ImageChops.multiply(fa, mask)))
        layer.paste(fill, (0, 0), fill)
    _paste(base, layer, (x, y))


def draw_b2_vertical(
    base: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    pct: float,
    phase: float,
    *,
    color: tuple[int, int, int] = CYAN,
) -> None:
    """Single vertical neon bar with ribbon-style color ramp (base→tip)."""
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rad = max(2, w // 2)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=rad, fill=_rgba(DIM, 230))
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=rad, outline=_rgba(color, 110), width=1)
    fh = int(h * max(0.0, min(100.0, pct)) / 100.0)
    if fh > 0:
        fill = Image.new("RGBA", (w, fh), (0, 0, 0, 0))
        _gradient_fill_v(fill, w, fh, color, phase)
        mask = Image.new("L", (w, fh), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, fh - 1], radius=rad, fill=255)
        fr, fg, fb, fa = fill.split()
        fill = Image.merge("RGBA", (fr, fg, fb, ImageChops.multiply(fa, mask)))
        layer.paste(fill, (0, h - fh), fill)
    _paste(base, layer, (x, y))


def draw_b3_hud_segs(
    base: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    pct: float,
    phase: float,
    *,
    color: tuple[int, int, int] = CYAN,
) -> None:
    segs = 12
    filled = int(round(segs * pct / 100.0))
    gap = 3
    pad = 4
    inner_w = w - pad * 2
    seg_w = max(4, (inner_w - gap * (segs - 1)) // segs)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=4, fill=_rgba(DIM, 220), outline=_rgba(color, 90), width=1)
    dim, mid, hot = _accent_ramp(color)
    cascade = int(phase * (segs + 2)) % (segs + 2)
    for i in range(segs):
        sx = pad + i * (seg_w + gap)
        sy = pad
        sh = h - pad * 2
        if i < filled:
            t = i / max(1, filled - 1)
            col = _blend(dim, mid, 0.2 + 0.8 * t)
            if i == cascade:
                col = hot
            # Mini vertical gradient inside each pill
            for yy in range(sh):
                vt = yy / max(1, sh - 1)
                c = _blend(_blend(col, (0, 0, 0), 0.25), _blend(col, WHITE, 0.35), vt)
                d.line([(sx + 1, sy + yy), (sx + seg_w - 2, sy + yy)], fill=_rgba(c, 255))
        else:
            d.rounded_rectangle(
                [sx, sy, sx + seg_w - 1, sy + sh - 1],
                radius=2,
                fill=_rgba(MUTED, 180),
                outline=_rgba(color, 50),
                width=1,
            )
    _paste(base, layer, (x, y))


def draw_b5_stripes(
    base: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    pct: float,
    phase: float,
    *,
    color: tuple[int, int, int] = CYAN,
) -> None:
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rad = h // 2
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=rad, fill=_rgba(DIM, 230))
    fw = max(h, int(w * pct / 100.0)) if pct > 0 else 0
    if fw:
        fill = Image.new("RGBA", (fw, h), (0, 0, 0, 0))
        _gradient_fill_h(fill, fw, h, color, phase)
        fd = ImageDraw.Draw(fill)
        off = int(phase * 16)
        for i in range(-h, fw + h, 8):
            fd.line([(i + off, h - 1), (i + off + h, 0)], fill=_rgba(WHITE, 55), width=3)
        mask = Image.new("L", (fw, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fw - 1, h - 1], radius=rad, fill=255)
        fr, fg, fb, fa = fill.split()
        fill = Image.merge("RGBA", (fr, fg, fb, ImageChops.multiply(fa, mask)))
        layer.paste(fill, (0, 0), fill)
    _paste(base, layer, (x, y))


def render_gauges(phase: float = 0.0) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    title = _font(18)
    small = _font(11)
    d.text((12, 8), "GAUGES · accent gradients", font=title, fill=CYAN)
    d.text((12, 30), "Each ring ramps its own color (dim → accent → hot)", font=small, fill=(120, 140, 170))

    amber = (255, 170, 40)
    green = (60, 230, 140)
    cells = [
        ("G1 Donut · cyan", draw_g1_donut, 72, 20, CYAN),
        ("G2 Ticks · magenta", draw_g2_ticks, 65, 20, MAGENTA),
        ("G3 Arc · amber", draw_g3_arc_ticks, 72, 22, amber),
        ("G4 Needle · cyan", draw_g4_needle, 50, 28, CYAN),
        ("G5 Dual · green", draw_g5_dual, 65, 22, green),
        ("G6 Solid · magenta", draw_g6_solid_dash, 55, 18, MAGENTA),
    ]
    # Leave room above G4 for value, and below G6
    positions = [
        (12, 52),
        (168, 52),
        (12, 188),
        (168, 200),  # G4: extra top margin for value above graphic
        (12, 328),
        (168, 328),
    ]
    size = 128
    for (label, fn, pct, fsz, col), (px, py) in zip(cells, positions):
        _label(d, px, py, label, small)
        fn(img, px, py + 14, size, float(pct), phase, font_size=fsz, color=col)
    return img


def render_bars(phase: float = 0.0) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    title = _font(18)
    small = _font(11)
    d.text((12, 10), "BARS · accent gradients", font=title, fill=CYAN)
    d.text((12, 34), "Each bar ramps its own color (dim → accent → hot)", font=small, fill=(120, 140, 170))

    amber = (255, 170, 40)
    green = (60, 230, 140)
    y = 56
    for label, fn, pct, bh, col in (
        ("B1 Ribbon · cyan", draw_b1_ribbon, 70, 22, CYAN),
        ("B1 Ribbon · magenta", draw_b1_ribbon, 58, 22, MAGENTA),
        ("B3 HUD · amber", draw_b3_hud_segs, 66, 28, amber),
        ("B5 Stripes · green", draw_b5_stripes, 64, 22, green),
    ):
        _label(d, 12, y, label, small)
        fn(img, 12, y + 16, 296, bh, float(pct), phase, color=col)
        y += bh + 34

    _label(d, 12, y, "B2 Vertical · cyan / magenta / amber", small)
    draw_b2_vertical(img, 40, y + 18, 36, 180, 68.0, phase, color=CYAN)
    draw_b2_vertical(img, 100, y + 18, 28, 180, 42.0, phase, color=MAGENTA)
    draw_b2_vertical(img, 150, y + 18, 48, 180, 85.0, phase, color=amber)
    return img


def push(conn: ConnectionManager, img: Image.Image) -> None:
    conn.send_image(img)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page", choices=("all", "gauges", "bars"), default="all")
    parser.add_argument("--hold", type=float, default=10.0, help="Seconds to hold each page")
    parser.add_argument("--fps", type=float, default=4.0, help="Animation refresh while holding")
    args = parser.parse_args()

    conn = ConnectionManager(port="AUTO")
    print("Connecting…")
    port = conn.connect()
    print(f"Connected {port}")
    conn.set_orientation(P.ORIENT_PORTRAIT)
    conn.set_brightness(40)
    conn.screen_on()

    pages: list[tuple[str, object]] = []
    if args.page in ("all", "gauges"):
        pages.append(("gauges", render_gauges))
    if args.page in ("all", "bars"):
        pages.append(("bars", render_bars))

    try:
        for name, renderer in pages:
            print(f"Showing {name} for {args.hold:.0f}s…")
            t0 = time.monotonic()
            frame_i = 0
            while time.monotonic() - t0 < args.hold:
                phase = (time.monotonic() * 0.35) % 1.0
                img = renderer(phase)
                # save first frame of each page for chat reference
                if frame_i == 0:
                    out = ROOT / f".tmp_preview_{name}.png"
                    img.save(out)
                    print(f"  wrote {out}")
                push(conn, img)
                frame_i += 1
                time.sleep(max(0.05, 1.0 / max(0.5, args.fps)))
            print(f"  done {name} ({frame_i} frames)")
        print("Preview complete.")
        return 0
    except Exception as exc:
        print(f"FAILED: {exc}")
        return 1
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
