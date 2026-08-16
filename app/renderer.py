"""Render a theme frame with Pillow from metrics + theme.yaml widgets."""
from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.metrics import Metrics
from app.paths import fonts_dir
from app.theme_service import orientation_size
from app import tron_styles as styles

VENDOR_FONTS = fonts_dir()

TOP_BY_ATTR = {
    "cpu": "top_by_cpu",
    "memory": "top_by_memory",
    "disk": "top_by_disk",
    "network": "top_by_network",
    "gpu": "top_by_gpu",
}

DEFAULT_FONT = "jetbrains-mono/JetBrainsMono-Bold.ttf"


def list_available_fonts() -> list[str]:
    root = fonts_dir()
    found: list[str] = []
    if root.is_dir():
        for p in root.rglob("*"):
            if p.suffix.lower() in (".ttf", ".otf"):
                found.append(p.relative_to(root).as_posix())
    return sorted(found) or [DEFAULT_FONT]


@lru_cache(maxsize=96)
def _font(rel: str, size: int) -> ImageFont.ImageFont:
    path = VENDOR_FONTS / str(rel).replace("\\", "/")
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        try:
            return ImageFont.truetype(str(VENDOR_FONTS / DEFAULT_FONT), size)
        except OSError:
            return ImageFont.load_default()


def _parse_color(value: Any, default: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return int(value[0]), int(value[1]), int(value[2])
    if isinstance(value, str) and "," in value:
        parts = [int(p.strip()) for p in value.split(",")]
        return parts[0], parts[1], parts[2]
    return default


def _fmt_rate_kb(kb: float) -> str:
    if kb >= 1024.0:
        return f"{kb / 1024.0:.1f}M"
    return f"{kb:.0f}K"


def _metric_value(m: Metrics, key: str) -> str:
    """Human-readable value with the natural unit for each binding."""
    mapping = {
        "cpu_percent": f"{m.cpu_percent:.0f}%",
        "cpu_temp": f"{m.cpu_temp:.0f}°C" if m.cpu_temp is not None else "--°C",
        "cpu_freq": f"{m.cpu_freq_ghz:.2f}GHz" if m.cpu_freq_ghz is not None else "--GHz",
        "ram_percent": f"{m.ram_used_gb:.1f}G",
        "ram_used": f"{m.ram_used_gb:.1f}G",
        "gpu_percent": f"{m.gpu_percent:.0f}%" if m.gpu_percent is not None else "--%",
        "gpu_temp": f"{m.gpu_temp:.0f}°C" if m.gpu_temp is not None else "--°C",
        "gpu_mem": (
            f"{m.gpu_mem_used_gb:.1f}GB"
            if m.gpu_mem_used_gb is not None
            else ("--GB" if m.gpu_mem_percent is None else f"{m.gpu_mem_percent:.0f}%")
        ),
        "disk_percent": f"{m.disk_used_gb:.0f}G" if m.disk_total_gb else f"{m.disk_percent:.0f}%",
        "net_up": _fmt_rate_kb(m.net_up_kb),
        "net_down": _fmt_rate_kb(m.net_down_kb),
        "volume": f"{m.volume_percent:.0f}%" if m.volume_percent is not None else "--%",
        "time": m.time_str,
        "date": m.date_str,
        "weather": m.weather_text or "--",
    }
    return mapping.get(key, key)


def _metric_pct(m: Metrics, key: str) -> float:
    """Normalize metric to 0..100 for gauges/bars."""
    raw = {
        "cpu_percent": m.cpu_percent,
        "ram_percent": m.ram_percent,
        "gpu_percent": m.gpu_percent or 0.0,
        "gpu_mem": m.gpu_mem_percent or 0.0,
        "disk_percent": m.disk_percent,
        "volume": m.volume_percent or 0.0,
        "cpu_temp": min(100.0, (m.cpu_temp or 0.0)),
        "gpu_temp": min(100.0, (m.gpu_temp or 0.0)),
        "cpu_freq": min(100.0, ((m.cpu_freq_ghz or 0.0) / 5.0) * 100.0),
        "net_up": min(100.0, (m.net_up_kb / 1024.0) * 100.0),
        "net_down": min(100.0, (m.net_down_kb / 1024.0) * 100.0),
    }.get(key, 0.0)
    return max(0.0, min(100.0, float(raw or 0.0)))


def _metric_display(m: Metrics, key: str, *, as_percent: bool = False) -> str:
    """Value text for widgets. as_percent=True forces 0–100% label (gauge option)."""
    if as_percent:
        return f"{_metric_pct(m, key):.0f}%"
    return _metric_value(m, key)


def migrate_static_text_to_widgets(theme: dict[str, Any]) -> dict[str, Any]:
    data = dict(theme)
    widgets = list(data.get("widgets") or [])
    static = data.get("static_text") or {}
    if static:
        for _name, node in static.items():
            if not isinstance(node, dict):
                continue
            widgets.insert(
                0,
                {
                    "type": "label",
                    "text": str(node.get("TEXT", "")),
                    "x": int(node.get("X", 0)),
                    "y": int(node.get("Y", 0)),
                    "font_size": int(node.get("FONT_SIZE", 16)),
                    "font": str(node.get("FONT", DEFAULT_FONT)),
                    "color": list(_parse_color(node.get("FONT_COLOR"), (230, 236, 245))),
                },
            )
        data["static_text"] = {}
    data["widgets"] = widgets
    return data


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _rgba(rgb: tuple[int, int, int], a: int) -> tuple[int, int, int, int]:
    return (rgb[0], rgb[1], rgb[2], max(0, min(255, int(a))))


def _anim_phase(*, period_s: float = 4.0, steps: int = 6) -> float:
    """0..1 TRON sweep, quantized so identical frames are more common (eco-friendly)."""
    period_s = max(1.0, float(period_s))
    steps = max(2, int(steps))
    t = (time.time() % period_s) / period_s
    return round(t * steps) / float(steps)


# Tunables set by DisplaySession from config (eco mode).
_ANIM_PERIOD_S = 4.0
_ANIM_STEPS = 6


def set_anim_tuning(*, period_s: float = 4.0, steps: int = 6) -> None:
    global _ANIM_PERIOD_S, _ANIM_STEPS
    _ANIM_PERIOD_S = max(1.0, float(period_s))
    _ANIM_STEPS = max(2, int(steps))


def _paste_rgba(base: Image.Image, layer: Image.Image, xy: tuple[int, int]) -> None:
    if layer.mode != "RGBA":
        layer = layer.convert("RGBA")
    if base.mode == "RGBA":
        base.paste(layer, xy, layer)
        return
    # Composite onto RGB canvas without flattening the whole frame.
    region = base.crop((xy[0], xy[1], xy[0] + layer.width, xy[1] + layer.height)).convert("RGBA")
    region = Image.alpha_composite(region, layer)
    base.paste(region.convert("RGB"), xy)


def _glow_color(color: tuple[int, int, int]) -> tuple[int, int, int]:
    """Push accent toward TRON cyan-white hot core."""
    return _blend(color, (220, 245, 255), 0.35)


def _draw_tron_segments(
    base: Image.Image,
    x: int,
    y: int,
    width: int,
    height: int,
    pct: float,
    *,
    color: tuple[int, int, int],
    back: tuple[int, int, int],
    segments: int = 10,
    phase: float,
) -> None:
    """Circuit-block meter: hollow dark cells, lit cells with neon core + cascade pulse."""
    segments = max(3, min(20, int(segments)))
    height = max(6, height)
    gap = max(2, height // 4)
    total_gap = gap * (segments - 1)
    seg_w = max(height, (width - total_gap) // segments)
    filled = int(round(segments * (pct / 100.0)))
    total_w = segments * seg_w + total_gap
    layer = Image.new("RGBA", (total_w, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rail = _blend((8, 12, 18), back, 0.5)
    core = _glow_color(color)
    hot = _blend(core, (255, 255, 255), 0.45)
    cascade = int(phase * (segments + 2)) % (segments + 2)

    for i in range(segments):
        sx = i * (seg_w + gap)
        r = max(1, height // 2)
        if i < filled:
            # Soft glow plate
            d.rounded_rectangle(
                [sx - 1, 0, sx + seg_w, height - 1],
                radius=r,
                fill=_rgba(core, 40 if i != cascade else 70),
            )
            d.rounded_rectangle(
                [sx, 1, sx + seg_w - 1, height - 2],
                radius=max(1, r - 1),
                fill=_rgba(color if i != cascade else hot, 255),
            )
            # Inner hot slit
            mid = height // 2
            d.line([(sx + 2, mid), (sx + seg_w - 3, mid)], fill=_rgba(hot, 180), width=max(1, height // 5))
        else:
            d.rounded_rectangle(
                [sx, 0, sx + seg_w - 1, height - 1],
                radius=r,
                fill=_rgba(rail, 200),
                outline=_rgba(_blend(color, (0, 0, 0), 0.65), 120),
                width=1,
            )

    _paste_rgba(base, layer, (x, y))


def _fit_image(
    src: Image.Image,
    box_w: int,
    box_h: int,
    fit: str,
    *,
    pan: tuple[float, float] = (0.5, 0.5),
) -> Image.Image:
    """Return an RGBA image exactly box_w x box_h according to wallpaper-like fit mode.

    pan is (fx, fy) in 0..1 for cover mode: 0 = flush start (left/top), 1 = flush end (right/bottom),
    0.5 = centered. Ignored for stretch/tile/contain/center.
    """
    fit = (fit or "cover").lower()
    if fit in ("expand", "fill"):
        fit = "cover"
    src = src.convert("RGBA")
    sw, sh = src.size
    box_w = max(1, box_w)
    box_h = max(1, box_h)
    out = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    fx = max(0.0, min(1.0, float(pan[0] if pan else 0.5)))
    fy = max(0.0, min(1.0, float(pan[1] if pan else 0.5)))

    if fit == "stretch":
        return src.resize((box_w, box_h), Image.Resampling.LANCZOS)

    if fit == "tile":
        for ty in range(0, box_h, sh):
            for tx in range(0, box_w, sw):
                out.paste(src, (tx, ty), src)
        return out

    if fit == "center":
        if sw > box_w or sh > box_h:
            scale = min(box_w / sw, box_h / sh)
            nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
            src = src.resize((nw, nh), Image.Resampling.LANCZOS)
            sw, sh = src.size
        px = (box_w - sw) // 2
        py = (box_h - sh) // 2
        out.paste(src, (px, py), src)
        return out

    if fit == "contain":
        scale = min(box_w / sw, box_h / sh)
        nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
        resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
        px = (box_w - nw) // 2
        py = (box_h - nh) // 2
        out.paste(resized, (px, py), resized)
        return out

    # cover — fill box, crop overflow; pan chooses which part stays visible
    scale = max(box_w / sw, box_h / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    left = int(round((nw - box_w) * fx)) if nw > box_w else 0
    top = int(round((nh - box_h) * fy)) if nh > box_h else 0
    left = max(0, min(max(0, nw - box_w), left))
    top = max(0, min(max(0, nh - box_h), top))
    return resized.crop((left, top, left + box_w, top + box_h))


_BG_CACHE: dict[tuple[Any, ...], Image.Image] = {}
_BG_CACHE_MAX = 8


def _theme_background_image(theme: dict[str, Any], theme_dir: Path, w: int, h: int) -> Image.Image:
    bg_rel = str(theme.get("background") or "").strip()
    src_candidates: list[Path] = []
    if bg_rel:
        p = Path(bg_rel)
        src_candidates.append(p if p.is_file() else theme_dir / bg_rel)
    for name in (
        "background_src.png",
        "background_src.jpg",
        "background_src.jpeg",
        "background_src.webp",
        "background_src.bmp",
        "background.png",
    ):
        src_candidates.append(theme_dir / name)
    bg_src = next((p for p in src_candidates if p.is_file()), None)
    if bg_src is None:
        return Image.new("RGB", (w, h), (16, 20, 28))
    fit = str(theme.get("background_fit") or "cover")
    pan_raw = theme.get("background_pan") or [0.5, 0.5]
    try:
        pan = (float(pan_raw[0]), float(pan_raw[1]))
    except (TypeError, ValueError, IndexError):
        pan = (0.5, 0.5)
    try:
        mtime = bg_src.stat().st_mtime_ns
    except OSError:
        mtime = 0
    key = (str(bg_src.resolve()), mtime, w, h, fit, round(pan[0], 4), round(pan[1], 4))
    cached = _BG_CACHE.get(key)
    if cached is not None and cached.size == (w, h):
        return cached.copy()
    try:
        raw = Image.open(bg_src)
    except OSError:
        return Image.new("RGB", (w, h), (16, 20, 28))
    fitted = _fit_image(raw, w, h, fit, pan=pan).convert("RGB")
    if len(_BG_CACHE) >= _BG_CACHE_MAX:
        # Drop an arbitrary old entry (insertion order in 3.7+)
        _BG_CACHE.pop(next(iter(_BG_CACHE)))
    _BG_CACHE[key] = fitted
    return fitted.copy()


def _paste_widget_image(base: Image.Image, theme_dir: Path, widget: dict[str, Any]) -> None:
    rel = str(widget.get("path") or widget.get("image") or "").strip()
    if not rel:
        return
    path = Path(rel)
    if not path.is_file():
        path = theme_dir / rel
    if not path.is_file():
        return
    try:
        src = Image.open(path)
    except OSError:
        return
    x = int(widget.get("x", 0))
    y = int(widget.get("y", 0))
    tw = int(widget.get("width", 320))
    th = int(widget.get("height", 480))
    fit = str(widget.get("fit", "cover"))
    placed = _fit_image(src, tw, th, fit)
    # Composite onto RGB base
    if base.mode != "RGBA":
        layer = base.convert("RGBA")
        layer.paste(placed, (x, y), placed)
        base.paste(layer.convert("RGB"))
    else:
        base.paste(placed, (x, y), placed)


def render_theme(theme: dict[str, Any], metrics: Metrics) -> Image.Image:
    theme = migrate_static_text_to_widgets(theme)
    w, h = orientation_size(theme)
    theme_dir = Path(theme.get("_dir") or ".")
    img = _theme_background_image(theme, theme_dir, w, h)

    draw = ImageDraw.Draw(img)
    saw_top = False
    phase = _anim_phase(period_s=_ANIM_PERIOD_S, steps=_ANIM_STEPS)

    for widget in theme.get("widgets") or []:
        if not isinstance(widget, dict):
            continue
        kind = widget.get("type", "text")
        x = int(widget.get("x", 0))
        y = int(widget.get("y", 0))
        font_rel = str(widget.get("font", DEFAULT_FONT))
        font_size = int(widget.get("font_size", 18))
        font = _font(font_rel, font_size)
        color = _parse_color(widget.get("color"), (240, 245, 250))
        accent = _parse_color(widget.get("bar_color") or widget.get("accent"), color)
        back = _parse_color(widget.get("back_color"), (20, 28, 40))

        if kind == "image":
            _paste_widget_image(img, theme_dir, widget)
            draw = ImageDraw.Draw(img)
            continue
        if kind == "label":
            draw.text((x, y), str(widget.get("text", "")), font=font, fill=color)
        elif kind == "text":
            bind = str(widget.get("bind", "cpu_percent"))
            label = widget.get("label")
            value = _metric_value(metrics, bind) if bind else str(widget.get("text", ""))
            text = f"{label} {value}".strip() if label else value
            draw.text((x, y), text, font=font, fill=color)
        elif kind == "bar":
            bind = str(widget.get("bind", "cpu_percent"))
            bw = int(widget.get("width", 200))
            bh = int(widget.get("height", 14))
            pct = _metric_pct(metrics, bind)
            styles.draw_bar(
                img,
                x,
                y,
                bw,
                bh,
                pct,
                style=str(widget.get("style") or styles.DEFAULT_BAR_STYLE),
                color=accent,
                phase=phase,
            )
            draw = ImageDraw.Draw(img)
        elif kind == "gauge":
            bind = str(widget.get("bind", "cpu_percent"))
            size = int(widget.get("width", widget.get("size", 100)))
            pct = _metric_pct(metrics, bind)
            show_pct = bool(widget.get("show_percent", False))
            label_size = max(8, int(round(font_size * 0.55)))
            styles.draw_gauge(
                img,
                x,
                y,
                size,
                pct,
                style=str(widget.get("style") or styles.DEFAULT_GAUGE_STYLE),
                color=accent,
                value=_metric_display(metrics, bind, as_percent=show_pct),
                font=font,
                label=str(widget.get("label") or ""),
                label_font=_font(font_rel, label_size),
                phase=phase,
            )
            draw = ImageDraw.Draw(img)
        elif kind == "ring":
            bind = str(widget.get("bind", "cpu_percent"))
            size = int(widget.get("width", widget.get("size", 80)))
            pct = _metric_pct(metrics, bind)
            styles.draw_ring(
                img,
                x,
                y,
                size,
                pct,
                style=str(widget.get("style") or styles.DEFAULT_RING_STYLE),
                color=accent,
                value=_metric_value(metrics, bind),
                font=font,
                phase=phase,
            )
            draw = ImageDraw.Draw(img)
        elif kind == "segments":
            bind = str(widget.get("bind", "cpu_percent"))
            bw = int(widget.get("width", 200))
            bh = int(widget.get("height", 16))
            pct = _metric_pct(metrics, bind)
            _draw_tron_segments(
                img,
                x,
                y,
                bw,
                bh,
                pct,
                color=accent,
                back=back,
                segments=int(widget.get("segments", 10)),
                phase=phase,
            )
            draw = ImageDraw.Draw(img)
        elif kind == "top_processes":
            if saw_top:
                continue
            saw_top = True
            by = str(widget.get("by", "cpu")).lower()
            attr = TOP_BY_ATTR.get(by, "top_by_cpu")
            names = getattr(metrics, attr, []) or []
            line_h = int(widget.get("line_height", max(18, font_size + 4)))
            for i, name in enumerate(names[:3]):
                draw.text((x, y + i * line_h), str(name), font=font, fill=color)

    if not theme.get("widgets"):
        font = _font(DEFAULT_FONT, 22)
        lines = [
            f"CPU {metrics.cpu_percent:.0f}%",
            f"GPU {metrics.gpu_percent:.0f}%" if metrics.gpu_percent is not None else "GPU --",
            f"RAM {metrics.ram_percent:.0f}%",
            metrics.time_str,
        ]
        yy = 40
        for line in lines:
            draw.text((20, yy), line, font=font, fill=(240, 245, 250))
            yy += 36

    return img


def default_studio_theme(name: str = "custom") -> dict[str, Any]:
    return {
        "author": "@omar",
        "display": {"DISPLAY_SIZE": '3.5"', "DISPLAY_ORIENTATION": "portrait"},
        "static_images": {
            "BACKGROUND": {"PATH": "background.png", "X": 0, "Y": 0, "WIDTH": 320, "HEIGHT": 480}
        },
        "static_text": {},
        "widgets": [
            {"type": "label", "text": name.upper(), "x": 16, "y": 12, "font_size": 28, "font": DEFAULT_FONT, "color": [230, 236, 245]},
            {"type": "label", "text": "system monitor", "x": 16, "y": 44, "font_size": 14, "font": DEFAULT_FONT, "color": [120, 150, 180]},
            {"type": "text", "x": 16, "y": 88, "bind": "cpu_percent", "label": "CPU", "font_size": 20, "font": DEFAULT_FONT, "color": [240, 245, 250]},
            {"type": "bar", "x": 16, "y": 118, "width": 288, "height": 16, "bind": "cpu_percent", "bar_color": [90, 180, 255], "style": "ribbon"},
            {"type": "text", "x": 16, "y": 160, "bind": "gpu_percent", "label": "GPU", "font_size": 20, "font": DEFAULT_FONT, "color": [240, 245, 250]},
            {"type": "bar", "x": 16, "y": 190, "width": 288, "height": 16, "bind": "gpu_percent", "bar_color": [90, 220, 160], "style": "stripes"},
            {"type": "text", "x": 16, "y": 232, "bind": "ram_percent", "label": "RAM", "font_size": 20, "font": DEFAULT_FONT, "color": [240, 245, 250]},
            {"type": "bar", "x": 16, "y": 262, "width": 288, "height": 16, "bind": "ram_percent", "bar_color": [220, 170, 90], "style": "hud"},
            {"type": "text", "x": 16, "y": 320, "bind": "net_down", "label": "DL", "font_size": 16, "font": DEFAULT_FONT, "color": [240, 245, 250]},
            {"type": "text", "x": 16, "y": 350, "bind": "net_up", "label": "UL", "font_size": 16, "font": DEFAULT_FONT, "color": [240, 245, 250]},
            {"type": "text", "x": 16, "y": 400, "bind": "time", "font_size": 22, "font": DEFAULT_FONT, "color": [240, 245, 250]},
            {"type": "text", "x": 16, "y": 440, "bind": "date", "font_size": 16, "font": DEFAULT_FONT, "color": [240, 245, 250]},
        ],
    }
