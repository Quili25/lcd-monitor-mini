"""TRON gauge / ring / bar visual styles (accent gradients).

Style ids are stored on widgets as ``style`` and selected in Theme Studio.
"""
from __future__ import annotations

import math
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFont

# --- public style catalogs (id, label) ---

BAR_STYLES: list[tuple[str, str]] = [
    ("ribbon", "B1 Ribbon"),
    ("vertical", "B2 Vertical"),
    ("hud", "B3 HUD"),
    ("stripes", "B5 Stripes"),
]

GAUGE_STYLES: list[tuple[str, str]] = [
    ("donut", "G1 Donut"),
    ("ticks", "G2 Ticks"),
    ("arc", "G3 Arc"),
    ("needle", "G4 Needle"),
    ("dual", "G5 Dual"),
    ("solid", "G6 Solid"),
]

RING_STYLES: list[tuple[str, str]] = [
    ("donut", "G1 Donut"),
    ("ticks", "G2 Ticks"),
    ("dual", "G5 Dual"),
    ("solid", "G6 Solid"),
    ("arc", "G3 Arc"),
    ("needle", "G4 Needle"),
]

DEFAULT_BAR_STYLE = "ribbon"
DEFAULT_GAUGE_STYLE = "arc"
DEFAULT_RING_STYLE = "donut"

WHITE = (235, 245, 255)
MUTED = (28, 36, 48)
DIM = (16, 22, 32)


def normalize_style(kind: str, style: Any) -> str:
    raw = str(style or "").strip().lower()
    if kind == "bar":
        ids = {s for s, _ in BAR_STYLES}
        return raw if raw in ids else DEFAULT_BAR_STYLE
    if kind == "gauge":
        ids = {s for s, _ in GAUGE_STYLES}
        return raw if raw in ids else DEFAULT_GAUGE_STYLE
    if kind == "ring":
        ids = {s for s, _ in RING_STYLES}
        return raw if raw in ids else DEFAULT_RING_STYLE
    return raw


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
    if layer.mode != "RGBA":
        layer = layer.convert("RGBA")
    region = base.crop((xy[0], xy[1], xy[0] + layer.width, xy[1] + layer.height)).convert("RGBA")
    region = Image.alpha_composite(region, layer)
    base.paste(region.convert("RGB"), xy)


def _accent_ramp(color: tuple[int, int, int]) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    dim = _blend(color, (0, 12, 28), 0.45)
    hot = _blend(color, WHITE, 0.55)
    return dim, color, hot


def _ramp_at(color: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    dim, mid, hot = _accent_ramp(color)
    t = max(0.0, min(1.0, t))
    c = _blend(dim, mid, 0.2 + 0.8 * t)
    return _blend(c, hot, max(0.0, t - 0.5) * 0.85)


def _arc_stroke(
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
    """Solid track stroke — native Pillow arc (fast)."""
    if end <= start + 0.15:
        return
    d = ImageDraw.Draw(layer)
    bbox = [cx - r, cy - r, cx + r, cy + r]
    d.arc(bbox, start, end, fill=_rgba(color, alpha), width=max(1, int(round(width))))


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
    """Accent ramp along sweep using native arc segments (UI-safe; no pixel loops)."""
    if end <= start + 0.15:
        return
    span = end - start
    # Keep segment count low — each call is C-backed and must not stall the GIL.
    n = max(10, min(24, int(abs(span) / 10) or 10))
    dim, mid, hot = _accent_ramp(color)
    sweep_t = (phase * 1.35) % 1.4 - 0.2
    d = ImageDraw.Draw(layer)
    bbox = [cx - r, cy - r, cx + r, cy + r]
    w = max(1, int(round(width)))
    aa = max(0, min(255, int(alpha)))
    for i in range(n):
        t0 = i / n
        t1 = (i + 1) / n
        a0 = start + span * t0
        a1 = start + span * t1
        if i < n - 1:
            a1 += 0.6  # overlap hides gaps between round-capped segments
        t = (t0 + t1) * 0.5
        c = _blend(dim, mid, 0.2 + 0.8 * t)
        c = _blend(c, hot, max(0.0, t - 0.5) * 0.85)
        dist = abs(t - sweep_t) / 0.14
        c = _blend(c, hot, max(0.0, 1.0 - dist) * 0.55)
        d.arc(bbox, a0, a1, fill=_rgba(c, aa), width=w)


def _gradient_fill_h(
    fill: Image.Image,
    fw: int,
    h: int,
    color: tuple[int, int, int],
    phase: float,
) -> None:
    if fw <= 0:
        return
    dim, mid, hot = _accent_ramp(color)
    fd = ImageDraw.Draw(fill)
    sweep_x = (phase * 1.4 - 0.2) * fw
    for i in range(fw):
        t = i / max(1, fw - 1)
        c = _blend(dim, mid, 0.25 + 0.75 * t)
        dist = abs(i - sweep_x) / max(6.0, fw * 0.1)
        c = _blend(c, hot, max(0.0, 1.0 - dist) * 0.55)
        fd.line([(i, 2), (i, h - 3)], fill=_rgba(c, 255))


def _gradient_fill_v(
    fill: Image.Image,
    w: int,
    fh: int,
    color: tuple[int, int, int],
    phase: float,
) -> None:
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


def _center_text(
    d: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
) -> None:
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


def _draw_label_bottom(
    d: ImageDraw.ImageDraw,
    size: int,
    label: str,
    font: ImageFont.ImageFont | None,
    color: tuple[int, int, int],
) -> None:
    if not label or font is None:
        return
    lb = d.textbbox((0, 0), str(label), font=font)
    lw = lb[2] - lb[0]
    lh = lb[3] - lb[1]
    d.text((size / 2 - lw / 2, size - lh - 3), str(label), font=font, fill=_rgba(color, 230))


# --- bars ---


def draw_bar_ribbon(
    base: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    pct: float,
    *,
    color: tuple[int, int, int],
    phase: float,
) -> None:
    h = max(6, h)
    w = max(h, w)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rad = h // 2
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=rad, fill=_rgba(DIM, 230))
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=rad, outline=_rgba(color, 110), width=1)
    fw = max(h, int(w * pct / 100.0)) if pct > 0 else 0
    fw = min(w, fw)
    if fw:
        fill = Image.new("RGBA", (fw, h), (0, 0, 0, 0))
        _gradient_fill_h(fill, fw, h, color, phase)
        mask = Image.new("L", (fw, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fw - 1, h - 1], radius=rad, fill=255)
        fr, fg, fb, fa = fill.split()
        fill = Image.merge("RGBA", (fr, fg, fb, ImageChops.multiply(fa, mask)))
        layer.paste(fill, (0, 0), fill)
    _paste(base, layer, (x, y))


def draw_bar_vertical(
    base: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    pct: float,
    *,
    color: tuple[int, int, int],
    phase: float,
) -> None:
    w = max(6, w)
    h = max(w, h)
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


def draw_bar_hud(
    base: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    pct: float,
    *,
    color: tuple[int, int, int],
    phase: float,
) -> None:
    h = max(10, h)
    w = max(40, w)
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


def draw_bar_stripes(
    base: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    pct: float,
    *,
    color: tuple[int, int, int],
    phase: float,
) -> None:
    h = max(6, h)
    w = max(h, w)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rad = h // 2
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=rad, fill=_rgba(DIM, 230))
    fw = max(h, int(w * pct / 100.0)) if pct > 0 else 0
    fw = min(w, fw)
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


_BAR_DRAW = {
    "ribbon": draw_bar_ribbon,
    "vertical": draw_bar_vertical,
    "hud": draw_bar_hud,
    "stripes": draw_bar_stripes,
}


def draw_bar(
    base: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    pct: float,
    *,
    style: str,
    color: tuple[int, int, int],
    phase: float,
) -> None:
    fn = _BAR_DRAW.get(normalize_style("bar", style), draw_bar_ribbon)
    fn(base, x, y, w, h, pct, color=color, phase=phase)


# --- gauges / rings ---


def _draw_g_donut(
    base: Image.Image,
    x: int,
    y: int,
    size: int,
    pct: float,
    *,
    color: tuple[int, int, int],
    value: str,
    font: ImageFont.ImageFont,
    label: str,
    label_font: ImageFont.ImageFont | None,
    phase: float,
) -> None:
    size = max(40, size)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = cy = size / 2
    stroke = max(8, size // 7)
    r = size / 2 - stroke / 2 - 1
    _arc_stroke(layer, cx, cy, r, 0, 360, stroke, MUTED, 220)
    sweep = 360 * pct / 100.0
    if sweep > 0.5:
        _gradient_arc(layer, cx, cy, r, -90, -90 + sweep, stroke, color, phase)
    _center_text(d, cx, cy, value, font, _rgba(WHITE, 255))
    _draw_label_bottom(d, size, label, label_font, color)
    _paste(base, layer, (x, y))


def _draw_g_ticks(
    base: Image.Image,
    x: int,
    y: int,
    size: int,
    pct: float,
    *,
    color: tuple[int, int, int],
    value: str,
    font: ImageFont.ImageFont,
    label: str,
    label_font: ImageFont.ImageFont | None,
    phase: float,
) -> None:
    size = max(40, size)
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
        if lit:
            col = _ramp_at(color, i / max(1, filled - 1))
            # Soft inner→outer hint with two segments (cheap vs many steps)
            mid_r = (r0 + r1) * 0.5
            inner = _blend(col, MUTED, 0.35)
            if i == cascade:
                col = _blend(col, WHITE, 0.65)
                inner = _blend(inner, WHITE, 0.4)
            d.line(
                [cx + cos_a * r0, cy + sin_a * r0, cx + cos_a * mid_r, cy + sin_a * mid_r],
                fill=_rgba(inner, 255),
                width=w,
            )
            d.line(
                [cx + cos_a * mid_r, cy + sin_a * mid_r, cx + cos_a * r1, cy + sin_a * r1],
                fill=_rgba(col, 255),
                width=w,
            )
        else:
            d.line(
                [cx + cos_a * r0, cy + sin_a * r0, cx + cos_a * r1, cy + sin_a * r1],
                fill=_rgba(MUTED, 160),
                width=w,
            )
    _center_text(d, cx, cy, value, font, _rgba(WHITE, 255))
    _draw_label_bottom(d, size, label, label_font, color)
    _paste(base, layer, (x, y))


def _draw_g_arc(
    base: Image.Image,
    x: int,
    y: int,
    size: int,
    pct: float,
    *,
    color: tuple[int, int, int],
    value: str,
    font: ImageFont.ImageFont,
    label: str,
    label_font: ImageFont.ImageFont | None,
    phase: float,
) -> None:
    size = max(40, size)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = size / 2, size * 0.72
    stroke = max(7, size // 10)
    r = size * 0.38
    _arc_stroke(layer, cx, cy, r, 180, 360, stroke, MUTED, 220)
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
    try:
        bbox = font.getbbox(value)
        tw = bbox[2] - bbox[0]
        d.text((cx - tw / 2 - bbox[0], cy - bbox[3]), value, font=font, fill=_rgba(WHITE, 255))
    except Exception:
        bb = d.textbbox((0, 0), value, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        d.text((cx - tw / 2, cy - th), value, font=font, fill=_rgba(WHITE, 255))
    _draw_label_bottom(d, size, label, label_font, color)
    _paste(base, layer, (x, y))


def _draw_g_needle(
    base: Image.Image,
    x: int,
    y: int,
    size: int,
    pct: float,
    *,
    color: tuple[int, int, int],
    value: str,
    font: ImageFont.ImageFont,
    label: str,
    label_font: ImageFont.ImageFont | None,
    phase: float,
) -> None:
    """Value bottom-anchored above arc apex (grows up/sideways); graphic below."""
    size = max(48, size)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # Reserve top band for value; graphic in lower portion
    gap = 4
    try:
        vb = font.getbbox(value)
        value_h = vb[3] - vb[1]
    except Exception:
        value_h = int(getattr(font, "size", 18) or 18)
    top_band = value_h + gap + 2

    gw = size
    gh = max(36, size - top_band)
    gx, gy = 0, size - gh
    cx, cy = gw / 2, gy + gh * 0.88
    stroke = max(6, size // 12)
    r = min(gw, gh) * 0.48
    _arc_stroke(layer, cx, cy, r, 180, 360, stroke, MUTED, 220)
    end = 180 + 180 * pct / 100.0
    if end > 180.5:
        _gradient_arc(layer, cx, cy, r, 180, end, stroke, color, phase)
    tip = _ramp_at(color, pct / 100.0)
    ang = math.radians(end)
    nx = cx + math.cos(ang) * (r - stroke)
    ny = cy + math.sin(ang) * (r - stroke)
    d.line([cx, cy, nx, ny], fill=_rgba(tip, 255), width=2)
    d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=_rgba(WHITE, 255))

    arc_top = cy - (r + stroke / 2.0)
    try:
        bbox = font.getbbox(value)
        tw = bbox[2] - bbox[0]
        tx = cx - tw / 2 - bbox[0]
        ty = arc_top - gap - bbox[3]
        d.text((tx, ty), value, font=font, fill=_rgba(WHITE, 255))
    except Exception:
        bb = d.textbbox((0, 0), value, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        d.text((cx - tw / 2, arc_top - gap - th), value, font=font, fill=_rgba(WHITE, 255))

    _draw_label_bottom(d, size, label, label_font, color)
    _paste(base, layer, (x, y))


def _draw_g_dual(
    base: Image.Image,
    x: int,
    y: int,
    size: int,
    pct: float,
    *,
    color: tuple[int, int, int],
    value: str,
    font: ImageFont.ImageFont,
    label: str,
    label_font: ImageFont.ImageFont | None,
    phase: float,
) -> None:
    size = max(40, size)
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
    _arc_stroke(layer, cx, cy, r, 0, 360, stroke, MUTED, 200)
    sweep = 360 * pct / 100.0
    if sweep > 0.5:
        _gradient_arc(layer, cx, cy, r, -90, -90 + sweep, stroke, color, phase)
    _center_text(d, cx, cy, value, font, _rgba(WHITE, 255))
    _draw_label_bottom(d, size, label, label_font, color)
    _paste(base, layer, (x, y))


def _draw_g_solid(
    base: Image.Image,
    x: int,
    y: int,
    size: int,
    pct: float,
    *,
    color: tuple[int, int, int],
    value: str,
    font: ImageFont.ImageFont,
    label: str,
    label_font: ImageFont.ImageFont | None,
    phase: float,
) -> None:
    """Ring graphic with value below it, both inside the widget square."""
    size = max(48, size)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    try:
        vb = font.getbbox(value)
        value_h = vb[3] - vb[1]
    except Exception:
        value_h = int(getattr(font, "size", 18) or 18)
    label_h = 0
    if label and label_font is not None:
        lb = d.textbbox((0, 0), str(label), font=label_font)
        label_h = lb[3] - lb[1] + 4
    bottom = value_h + 4 + label_h
    gs = max(32, size - bottom)
    ox = (size - gs) / 2
    oy = 0.0

    cx = ox + gs / 2
    cy = oy + gs / 2
    stroke = max(8, gs // 8)
    r = gs / 2 - stroke / 2 - 2
    dim, mid, hot = _accent_ramp(color)
    scale = gs / 128.0
    d.ellipse([cx - 6 * scale, cy - 6 * scale, cx + 6 * scale, cy + 6 * scale], fill=_rgba(mid, 255))
    d.ellipse(
        [cx - 12 * scale, cy - 12 * scale, cx + 12 * scale, cy + 12 * scale],
        outline=_rgba(hot, 200),
        width=max(1, int(2 * scale)),
    )
    d.ellipse(
        [cx - 22 * scale, cy - 22 * scale, cx + 22 * scale, cy + 22 * scale],
        outline=_rgba(dim, 140),
        width=1,
    )
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
            _arc_stroke(layer, cx, cy, r, a0, a1, stroke * 0.85, MUTED, 200)

    try:
        bbox = font.getbbox(value)
        tw = bbox[2] - bbox[0]
        d.text((size / 2 - tw / 2 - bbox[0], oy + gs + 2 - bbox[1]), value, font=font, fill=_rgba(WHITE, 255))
    except Exception:
        bb = d.textbbox((0, 0), value, font=font)
        tw = bb[2] - bb[0]
        d.text((size / 2 - tw / 2, oy + gs + 2), value, font=font, fill=_rgba(WHITE, 255))

    if label and label_font is not None:
        _draw_label_bottom(d, size, label, label_font, color)
    _paste(base, layer, (x, y))


_GAUGE_DRAW = {
    "donut": _draw_g_donut,
    "ticks": _draw_g_ticks,
    "arc": _draw_g_arc,
    "needle": _draw_g_needle,
    "dual": _draw_g_dual,
    "solid": _draw_g_solid,
}


def draw_gauge(
    base: Image.Image,
    x: int,
    y: int,
    size: int,
    pct: float,
    *,
    style: str,
    color: tuple[int, int, int],
    value: str,
    font: ImageFont.ImageFont,
    label: str = "",
    label_font: ImageFont.ImageFont | None = None,
    phase: float = 0.0,
) -> None:
    sid = normalize_style("gauge", style)
    fn = _GAUGE_DRAW.get(sid, _draw_g_arc)
    fn(
        base,
        x,
        y,
        size,
        pct,
        color=color,
        value=value,
        font=font,
        label=label,
        label_font=label_font,
        phase=phase,
    )


def draw_ring(
    base: Image.Image,
    x: int,
    y: int,
    size: int,
    pct: float,
    *,
    style: str,
    color: tuple[int, int, int],
    value: str,
    font: ImageFont.ImageFont,
    phase: float = 0.0,
) -> None:
    sid = normalize_style("ring", style)
    fn = _GAUGE_DRAW.get(sid, _draw_g_donut)
    fn(
        base,
        x,
        y,
        size,
        pct,
        color=color,
        value=value,
        font=font,
        label="",
        label_font=None,
        phase=phase,
    )
