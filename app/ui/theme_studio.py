"""In-app Theme Studio: create/edit themes with live LCD preview."""
from __future__ import annotations

import copy
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import Qt, QTimer, Signal, QSize
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from PIL import Image

from app.display_session import DisplaySession
from app.renderer import (
    DEFAULT_FONT,
    _fit_image,
    default_studio_theme,
    list_available_fonts,
    migrate_static_text_to_widgets,
    render_theme,
)
from app.theme_service import (
    ensure_background,
    list_themes,
    load_theme,
    product_themes_dir,
    resolve_theme_dir,
    save_theme,
)
from app.ui.bg_fit import BackgroundFitDialog
from app.ui.chrome import FluentWindow
from app.tron_styles import (
    BAR_STYLES,
    DEFAULT_BAR_STYLE,
    DEFAULT_GAUGE_STYLE,
    DEFAULT_RING_STYLE,
    GAUGE_STYLES,
    RING_STYLES,
    normalize_style,
)

BINDINGS = [
    "cpu_percent",
    "cpu_temp",
    "cpu_freq",
    "gpu_percent",
    "gpu_temp",
    "gpu_mem",
    "ram_percent",
    "disk_percent",
    "net_up",
    "net_down",
    "volume",
    "time",
    "date",
    "weather",
]

TOP_BY = ["cpu", "memory", "disk", "network", "gpu"]
WIDGET_TYPES = ["label", "text", "bar", "gauge", "ring", "segments", "top_processes"]
METRIC_TYPES = ("text", "bar", "gauge", "ring", "segments")
ACCENT_TYPES = ("bar", "gauge", "ring", "segments")
STYLE_TYPES = ("bar", "gauge", "ring")
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;All files (*.*)"
HANDLE = 10


def _styles_for_kind(kind: str) -> list[tuple[str, str]]:
    if kind == "bar":
        return BAR_STYLES
    if kind == "gauge":
        return GAUGE_STYLES
    if kind == "ring":
        return RING_STYLES
    return []


def _default_style_for_kind(kind: str) -> str:
    if kind == "bar":
        return DEFAULT_BAR_STYLE
    if kind == "gauge":
        return DEFAULT_GAUGE_STYLE
    if kind == "ring":
        return DEFAULT_RING_STYLE
    return ""


def _fill_style_combo(combo: QComboBox, kind: str, current: str | None = None) -> None:
    catalog = _styles_for_kind(kind)
    want = normalize_style(kind, current or _default_style_for_kind(kind))
    combo.blockSignals(True)
    combo.clear()
    for sid, label in catalog:
        combo.addItem(label, sid)
    idx = combo.findData(want)
    combo.setCurrentIndex(idx if idx >= 0 else 0)
    combo.blockSignals(False)


def _widget_size(w: dict[str, Any]) -> tuple[int, int]:
    kind = w.get("type")
    if kind in ("bar", "segments"):
        return max(10, int(w.get("width", 200))), max(4, int(w.get("height", 16)))
    if kind in ("gauge", "ring"):
        s = max(24, int(w.get("width", w.get("size", 100))))
        return s, s
    if kind == "top_processes":
        return max(40, int(w.get("width", 160))), max(24, int(w.get("height", 54)))
    if kind in ("label", "text"):
        return max(20, int(w.get("width", 110))), max(14, int(w.get("height", 22)))
    return max(20, int(w.get("width", 110))), max(14, int(w.get("height", 22)))


def _clamp_widget(w: dict[str, Any], screen_w: int, screen_h: int) -> None:
    bw, bh = _widget_size(w)
    bw = min(bw, screen_w)
    bh = min(bh, screen_h)
    kind = w.get("type")
    if kind in ("gauge", "ring"):
        s = min(bw, bh, screen_w, screen_h)
        w["width"] = s
        w["size"] = s
        bw = bh = s
    else:
        w["width"] = bw
        w["height"] = bh
    x = int(w.get("x", 0))
    y = int(w.get("y", 0))
    w["x"] = max(0, min(max(0, screen_w - bw), x))
    w["y"] = max(0, min(max(0, screen_h - bh), y))



def _color_to_list(c: QColor) -> list[int]:
    return [c.red(), c.green(), c.blue()]


def _list_to_qcolor(value: Any, fallback: tuple[int, int, int] = (240, 245, 250)) -> QColor:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return QColor(int(value[0]), int(value[1]), int(value[2]))
    return QColor(*fallback)


def _swatch_style(rgb: list[int] | tuple[int, int, int]) -> str:
    return (
        f"background: rgb({rgb[0]},{rgb[1]},{rgb[2]});"
        "border: 1px solid #a0a0a0; border-radius: 4px; min-width: 28px; max-width: 36px;"
    )


def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def _strip_image_widgets(widgets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Optional[str]]:
    kept: list[dict[str, Any]] = []
    bg_path: Optional[str] = None
    for w in widgets:
        if w.get("type") == "image":
            if bg_path is None:
                bg_path = str(w.get("path") or w.get("image") or "") or None
            continue
        kept.append(w)
    return kept, bg_path


def _defaults_for_type(kind: str, base: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    x = int((base or {}).get("x", 20))
    y = int((base or {}).get("y", 20))
    font = str((base or {}).get("font", DEFAULT_FONT))
    color = (base or {}).get("color") or [240, 245, 250]
    w: dict[str, Any] = {"type": kind, "x": x, "y": y, "font": font, "font_size": 16, "color": color}
    if kind == "label":
        w.update({"text": str((base or {}).get("text", "Text")), "font_size": 18, "width": 110, "height": 24})
    elif kind == "text":
        w.update({"bind": "cpu_percent", "label": "CPU", "font_size": 18, "width": 140, "height": 24})
    elif kind == "bar":
        w.update(
            {
                "bind": "cpu_percent",
                "width": 280,
                "height": 14,
                "bar_color": [90, 180, 255],
                "style": DEFAULT_BAR_STYLE,
            }
        )
    elif kind == "gauge":
        w.update(
            {
                "bind": "cpu_percent",
                "label": "CPU",
                "width": 110,
                "bar_color": [90, 180, 255],
                "needle_color": [240, 245, 250],
                "font_size": 22,
                "show_percent": False,
                "style": DEFAULT_GAUGE_STYLE,
            }
        )
    elif kind == "ring":
        w.update(
            {
                "bind": "cpu_percent",
                "width": 90,
                "bar_color": [90, 220, 160],
                "font_size": 20,
                "style": DEFAULT_RING_STYLE,
            }
        )
    elif kind == "segments":
        w.update(
            {
                "bind": "cpu_percent",
                "width": 280,
                "height": 16,
                "segments": 10,
                "bar_color": [220, 170, 90],
            }
        )
    elif kind == "top_processes":
        w.update({"by": "cpu", "font_size": 16, "width": 160, "height": 54})
    return w


# Fixed column widths for WidgetRow (Option C · table layout).
_COL_INDEX = 28
_COL_TYPE = 128
_COL_CONTENT_MIN = 140
_COL_ACCENT = 32
_COL_EXTRA = 168
_ROW_H = 40
_ROW_MARGIN_H = 8
_ROW_SPACING = 8


def _empty_slot(width: int, height: int = 28) -> QLabel:
    lab = QLabel("—")
    lab.setFixedSize(width, height)
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lab.setEnabled(False)
    lab.setStyleSheet("color: #888; border: 1px dashed #c0c0c0; border-radius: 4px;")
    return lab


class _SlotHost(QWidget):
    """Fixed/expanding cell that keeps the same size regardless of which page is shown."""

    def __init__(self, *, width: Optional[int] = None, min_width: int = 0, height: int = 28, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        if width is not None:
            self.setFixedWidth(width)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        else:
            self.setMinimumWidth(min_width)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._pages: list[QWidget] = []

    def add_page(self, widget: QWidget) -> int:
        widget.setParent(self)
        widget.hide()
        self._pages.append(widget)
        self._layout_pages()
        return len(self._pages) - 1

    def set_page(self, index: int) -> None:
        for i, page in enumerate(self._pages):
            page.setVisible(i == index)
        self._layout_pages()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_pages()

    def _layout_pages(self) -> None:
        r = self.rect()
        for page in self._pages:
            page.setGeometry(r)


def _add_table_columns(layout: QHBoxLayout) -> None:
    """Shared horizontal metrics for header + rows."""
    layout.setContentsMargins(_ROW_MARGIN_H, 0, _ROW_MARGIN_H, 0)
    layout.setSpacing(_ROW_SPACING)


def widgets_list_header() -> QWidget:
    """Column labels aligned with WidgetRow fixed slots."""
    host = QWidget()
    host.setObjectName("widgetsListHeader")
    host.setFixedHeight(22)
    row = QHBoxLayout(host)
    _add_table_columns(row)
    row.setContentsMargins(_ROW_MARGIN_H, 2, _ROW_MARGIN_H, 2)

    def _h(text: str, width: Optional[int] = None, stretch: int = 0) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("fieldLabel")
        if width is not None:
            lab.setFixedWidth(width)
            lab.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        else:
            lab.setMinimumWidth(_COL_CONTENT_MIN)
            lab.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(lab, stretch)
        return lab

    _h("#", _COL_INDEX)
    _h("Type", _COL_TYPE)
    _h("Content", stretch=1)
    _h("", _COL_ACCENT)
    _h("Style / Extra", _COL_EXTRA)
    return host


class WidgetRow(QWidget):
    """Fixed-column widget row: # | Type | Content | Accent | Extra."""

    changed = Signal()
    accent_clicked = Signal()
    activated = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._data: dict[str, Any] = {}
        self._block = False
        self.setFixedHeight(_ROW_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        _add_table_columns(root)
        root.setContentsMargins(_ROW_MARGIN_H, 6, _ROW_MARGIN_H, 6)

        self.index_lab = QLabel("01")
        self.index_lab.setFixedSize(_COL_INDEX, 28)
        self.index_lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.index_lab.setObjectName("widgetIndex")
        self.index_lab.setStyleSheet(
            "background: rgba(128,128,128,0.18); border-radius: 4px; font-size: 11px; color: #666;"
        )
        root.addWidget(self.index_lab)

        self.type_combo = QComboBox()
        self.type_combo.addItems(WIDGET_TYPES)
        self.type_combo.setFixedSize(_COL_TYPE, 28)
        self.type_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.type_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.type_combo.setMinimumContentsLength(8)
        root.addWidget(self.type_combo)

        self.content_host = _SlotHost(min_width=_COL_CONTENT_MIN, height=28)
        self.bind_combo = QComboBox()
        self.bind_combo.addItems(BINDINGS)
        self.bind_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.bind_combo.setMinimumContentsLength(10)
        self.by_combo = QComboBox()
        self.by_combo.addItems(TOP_BY)
        self.by_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.by_combo.setMinimumContentsLength(8)
        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText("Text")
        self.content_empty = _empty_slot(_COL_CONTENT_MIN)
        self.content_empty.setMinimumWidth(_COL_CONTENT_MIN)
        self.content_empty.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._content_bind = self.content_host.add_page(self.bind_combo)
        self._content_by = self.content_host.add_page(self.by_combo)
        self._content_text = self.content_host.add_page(self.text_edit)
        self._content_empty = self.content_host.add_page(self.content_empty)
        root.addWidget(self.content_host, 1)

        self.accent_host = _SlotHost(width=_COL_ACCENT, height=28)
        self.btn_accent = QPushButton()
        self.btn_accent.setFixedSize(_COL_ACCENT, 28)
        self.btn_accent.setToolTip("Accent / bar color")
        self.btn_accent.clicked.connect(self._accent)
        self.accent_empty = _empty_slot(_COL_ACCENT)
        self._accent_btn = self.accent_host.add_page(self.btn_accent)
        self._accent_empty = self.accent_host.add_page(self.accent_empty)
        root.addWidget(self.accent_host)

        self.extra_host = _SlotHost(width=_COL_EXTRA, height=28)
        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("Label")

        self.style_combo = QComboBox()
        self.style_combo.setToolTip("Visual style")
        self.style_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.style_combo.setMinimumContentsLength(8)

        self.gauge_extra = QWidget()
        gauge_row = QHBoxLayout(self.gauge_extra)
        gauge_row.setContentsMargins(0, 0, 0, 0)
        gauge_row.setSpacing(4)
        self.gauge_style = QComboBox()
        self.gauge_style.setToolTip("Gauge style")
        self.gauge_style.setFixedWidth(78)
        self.gauge_style.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.gauge_style.setMinimumContentsLength(6)
        self.gauge_label = QLineEdit()
        self.gauge_label.setPlaceholderText("Label")
        self.show_percent = QCheckBox("%")
        self.show_percent.setToolTip("Show value as % instead of units (gauge)")
        self.show_percent.setFixedWidth(28)
        gauge_row.addWidget(self.gauge_style)
        gauge_row.addWidget(self.gauge_label, 1)
        gauge_row.addWidget(self.show_percent)

        self.segments_spin = QSpinBox()
        self.segments_spin.setRange(3, 20)
        self.segments_spin.setPrefix("seg ")

        self.extra_empty = _empty_slot(_COL_EXTRA)
        self._extra_empty = self.extra_host.add_page(self.extra_empty)
        self._extra_label = self.extra_host.add_page(self.label_edit)
        self._extra_style = self.extra_host.add_page(self.style_combo)
        self._extra_gauge = self.extra_host.add_page(self.gauge_extra)
        self._extra_segments = self.extra_host.add_page(self.segments_spin)
        root.addWidget(self.extra_host)

        self.type_combo.currentTextChanged.connect(self._on_type)
        self.bind_combo.currentTextChanged.connect(self._emit)
        self.by_combo.currentTextChanged.connect(self._emit)
        self.label_edit.textChanged.connect(self._emit)
        self.gauge_label.textChanged.connect(self._emit)
        self.text_edit.textChanged.connect(self._emit)
        self.segments_spin.valueChanged.connect(self._emit)
        self.show_percent.toggled.connect(self._emit)
        self.style_combo.currentIndexChanged.connect(self._emit)
        self.gauge_style.currentIndexChanged.connect(self._emit)

    def set_index(self, index: int) -> None:
        self.index_lab.setText(f"{max(1, index):02d}")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(420, _ROW_H)

    def mousePressEvent(self, event) -> None:
        self.activated.emit()
        super().mousePressEvent(event)

    def _accent(self) -> None:
        self.activated.emit()
        self.accent_clicked.emit()

    def _emit(self, *_args) -> None:
        if self._block:
            return
        self.activated.emit()
        self.changed.emit()

    def _on_type(self, *_args) -> None:
        if self._block:
            return
        self.activated.emit()
        self._apply_slots(self.type_combo.currentText())
        self.changed.emit()

    def _apply_slots(self, kind: str) -> None:
        if kind in METRIC_TYPES:
            self.content_host.set_page(self._content_bind)
        elif kind == "top_processes":
            self.content_host.set_page(self._content_by)
        elif kind == "label":
            self.content_host.set_page(self._content_text)
        else:
            self.content_host.set_page(self._content_empty)

        if kind in ACCENT_TYPES:
            self.accent_host.set_page(self._accent_btn)
        else:
            self.accent_host.set_page(self._accent_empty)

        if kind == "text":
            self.extra_host.set_page(self._extra_label)
        elif kind == "bar" or kind == "ring":
            _fill_style_combo(self.style_combo, kind, _default_style_for_kind(kind))
            self.extra_host.set_page(self._extra_style)
        elif kind == "gauge":
            _fill_style_combo(self.gauge_style, kind, _default_style_for_kind(kind))
            self.extra_host.set_page(self._extra_gauge)
        elif kind == "segments":
            self.extra_host.set_page(self._extra_segments)
        else:
            self.extra_host.set_page(self._extra_empty)

    def set_data(self, data: dict[str, Any]) -> None:
        self._data = data
        self._block = True
        kind = str(data.get("type", "label"))
        if kind not in WIDGET_TYPES:
            kind = "label"
        ti = self.type_combo.findText(kind)
        if ti >= 0:
            self.type_combo.setCurrentIndex(ti)
        bind = str(data.get("bind", "cpu_percent"))
        bi = self.bind_combo.findText(bind)
        if bi >= 0:
            self.bind_combo.setCurrentIndex(bi)
        by = str(data.get("by", "cpu"))
        yi = self.by_combo.findText(by)
        if yi >= 0:
            self.by_combo.setCurrentIndex(yi)
        label = str(data.get("label", ""))
        self.label_edit.setText(label)
        self.gauge_label.setText(label)
        self.text_edit.setText(str(data.get("text", "")))
        self.segments_spin.setValue(int(data.get("segments", 10)))
        self.show_percent.setChecked(bool(data.get("show_percent", False)))
        if kind in STYLE_TYPES:
            sid = normalize_style(kind, data.get("style"))
            if kind == "gauge":
                _fill_style_combo(self.gauge_style, kind, sid)
            else:
                _fill_style_combo(self.style_combo, kind, sid)
        accent = data.get("bar_color") or data.get("accent") or [90, 180, 255]
        if isinstance(accent, (list, tuple)) and len(accent) >= 3:
            self.btn_accent.setStyleSheet(_swatch_style(accent))
        self._apply_slots(kind)
        self._block = False

    def apply_to(self, data: dict[str, Any]) -> None:
        old = str(data.get("type", "label"))
        kind = self.type_combo.currentText()
        if kind != old:
            fresh = _defaults_for_type(kind, data)
            data.clear()
            data.update(fresh)
        data["type"] = kind
        if kind in METRIC_TYPES:
            data["bind"] = self.bind_combo.currentText()
        if kind == "top_processes":
            data["by"] = self.by_combo.currentText()
        if kind == "text":
            data["label"] = self.label_edit.text()
        if kind == "gauge":
            data["label"] = self.gauge_label.text()
            data["show_percent"] = self.show_percent.isChecked()
            sid = self.gauge_style.currentData()
            data["style"] = str(sid or DEFAULT_GAUGE_STYLE)
        elif "show_percent" in data:
            data.pop("show_percent", None)
        if kind == "bar":
            sid = self.style_combo.currentData()
            data["style"] = str(sid or DEFAULT_BAR_STYLE)
            # Sensible geometry when switching to/from vertical
            if data["style"] == "vertical" and int(data.get("height", 14)) < 40:
                data["width"] = min(48, int(data.get("width", 280)))
                data["height"] = max(100, int(data.get("height", 14)))
            elif data["style"] != "vertical" and int(data.get("width", 40)) < 80 and int(data.get("height", 14)) >= 80:
                data["width"] = 280
                data["height"] = 14
        if kind == "ring":
            sid = self.style_combo.currentData()
            data["style"] = str(sid or DEFAULT_RING_STYLE)
        if kind not in STYLE_TYPES and "style" in data:
            data.pop("style", None)
        if kind == "label":
            data["text"] = self.text_edit.text()
        if kind == "segments":
            data["segments"] = self.segments_spin.value()


class Canvas(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.screen_w = 320
        self.screen_h = 480
        self.setFixedSize(self.screen_w, self.screen_h)
        self.widgets: list[dict[str, Any]] = []
        self.selected = -1
        self._drag_idx = -1
        self._drag_off = (0, 0)
        self._resize_idx = -1
        self._bg_pix: Optional[QPixmap] = None

    def set_screen_size(self, w: int, h: int) -> None:
        self.screen_w = max(1, w)
        self.screen_h = max(1, h)
        self.setFixedSize(self.screen_w, self.screen_h)
        for widget in self.widgets:
            _clamp_widget(widget, self.screen_w, self.screen_h)
        self.update()

    def set_widgets(self, widgets: list[dict[str, Any]]) -> None:
        for widget in widgets:
            _clamp_widget(widget, self.screen_w, self.screen_h)
        self.widgets = widgets
        self.update()

    def set_background(self, img: Optional[Image.Image]) -> None:
        if img is None:
            self._bg_pix = None
        else:
            rgba = img.convert("RGBA")
            if rgba.size != (self.screen_w, self.screen_h):
                rgba = rgba.resize((self.screen_w, self.screen_h), Image.Resampling.LANCZOS)
            overlay = Image.new("RGBA", rgba.size, (16, 20, 28, 90))
            rgba = Image.alpha_composite(rgba, overlay)
            self._bg_pix = _pil_to_qpixmap(rgba)
        self.update()

    def _hit_size(self, w: dict[str, Any]) -> tuple[int, int]:
        return _widget_size(w)

    def _handle_rect(self, w: dict[str, Any]) -> tuple[int, int, int, int]:
        x, y = int(w.get("x", 0)), int(w.get("y", 0))
        bw, bh = self._hit_size(w)
        return x + bw - HANDLE, y + bh - HANDLE, HANDLE, HANDLE

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(16, 20, 28))
        if self._bg_pix is not None:
            p.drawPixmap(0, 0, self._bg_pix)
        p.setPen(QPen(QColor(255, 255, 255, 70), 1, Qt.PenStyle.DotLine))
        for x in range(0, self.screen_w + 1, 40):
            p.drawLine(x, 0, x, self.screen_h)
        for y in range(0, self.screen_h + 1, 40):
            p.drawLine(0, y, self.screen_w, y)
        for i, w in enumerate(self.widgets):
            x, y = int(w.get("x", 0)), int(w.get("y", 0))
            bw, bh = self._hit_size(w)
            selected = i == self.selected
            color = QColor(90, 180, 255) if selected else QColor(200, 210, 220)
            p.setPen(color)
            kind = w.get("type")
            if kind == "label":
                label = w.get("text") or "label"
            elif kind == "top_processes":
                label = f"top/{w.get('by', 'cpu')}"
            elif kind in ("gauge", "ring"):
                label = f"{kind}:{w.get('bind', '')}"
            else:
                label = w.get("label") or w.get("bind") or kind
            p.drawText(x + 2, y + min(14, bh - 2), str(label)[:18])
            p.drawRect(x, y, bw, bh)
            if selected:
                p.setPen(QPen(QColor(255, 220, 0), 2))
                p.drawRect(x - 2, y - 2, bw + 4, bh + 4)
                hx, hy, hw, hh = self._handle_rect(w)
                p.fillRect(hx, hy, hw, hh, QColor(255, 220, 0))

    def mousePressEvent(self, event) -> None:
        pos = event.position().toPoint()
        self._drag_idx = -1
        self._resize_idx = -1
        # Prefer resize handle of selected widget
        if 0 <= self.selected < len(self.widgets):
            w = self.widgets[self.selected]
            hx, hy, hw, hh = self._handle_rect(w)
            if hx <= pos.x() <= hx + hw and hy <= pos.y() <= hy + hh:
                self._resize_idx = self.selected
                self.update()
                self.parent_editor().on_canvas_select()
                return
        self.selected = -1
        for i in range(len(self.widgets) - 1, -1, -1):
            w = self.widgets[i]
            x, y = int(w.get("x", 0)), int(w.get("y", 0))
            bw, bh = self._hit_size(w)
            if x <= pos.x() <= x + bw and y <= pos.y() <= y + bh:
                self.selected = i
                hx, hy, hw, hh = self._handle_rect(w)
                if hx <= pos.x() <= hx + hw and hy <= pos.y() <= hy + hh:
                    self._resize_idx = i
                else:
                    self._drag_idx = i
                    self._drag_off = (pos.x() - x, pos.y() - y)
                break
        self.update()
        self.parent_editor().on_canvas_select()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        if self._resize_idx >= 0:
            w = self.widgets[self._resize_idx]
            x, y = int(w.get("x", 0)), int(w.get("y", 0))
            kind = w.get("type")
            new_w = max(20, pos.x() - x)
            new_h = max(14, pos.y() - y)
            if kind in ("gauge", "ring"):
                s = max(24, min(new_w, new_h))
                s = min(s, self.screen_w - x, self.screen_h - y)
                w["width"] = s
                w["size"] = s
            else:
                w["width"] = min(new_w, self.screen_w - x)
                w["height"] = min(new_h, self.screen_h - y)
            _clamp_widget(w, self.screen_w, self.screen_h)
            self.update()
            self.parent_editor().sync_inspector_geom()
            return
        if self._drag_idx < 0:
            return
        w = self.widgets[self._drag_idx]
        bw, bh = self._hit_size(w)
        w["x"] = max(0, min(self.screen_w - bw, pos.x() - self._drag_off[0]))
        w["y"] = max(0, min(self.screen_h - bh, pos.y() - self._drag_off[1]))
        self.update()
        self.parent_editor().sync_inspector_pos()

    def mouseReleaseEvent(self, _event) -> None:
        self._drag_idx = -1
        self._resize_idx = -1

    def parent_editor(self) -> "ThemeStudioWindow":
        return self.window()  # type: ignore


class ThemeStudioWindow(FluentWindow):
    _preview_finished = Signal(object)  # None on success, error str on failure
    _apply_finished = Signal(object)  # None on success, error str on failure

    def __init__(self, session: DisplaySession, on_applied=None) -> None:
        super().__init__(title="Theme Studio")
        self.session = session
        self.on_applied = on_applied
        self.resize(980, 700)
        self.theme: dict[str, Any] = {}
        self.theme_name = session.theme_name
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._end_preview)
        self._preview_busy = False
        self._preview_finished.connect(self._on_preview_finished)
        self._apply_finished.connect(self._on_apply_finished)
        self._fonts = list_available_fonts()
        self._rows: list[WidgetRow] = []
        self._syncing = False
        # Pending background — only written to disk on Save (+ not pushed to LCD)
        self._pending_src: Optional[Path] = None
        self._pending_fit = "cover"
        self._pending_pan: tuple[float, float] = (0.5, 0.5)
        self._pending_preview: Optional[Image.Image] = None
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="lcd-monitor-mini-bg-"))
        self._orient = "portrait"

        layout = QHBoxLayout()
        layout.setSpacing(16)
        self.body_layout.setContentsMargins(16, 12, 16, 16)
        self.body_layout.addLayout(layout)

        left = QVBoxLayout()
        left.setSpacing(4)
        left.setAlignment(Qt.AlignmentFlag.AlignTop)
        name_lab = QLabel("Theme name")
        name_lab.setObjectName("fieldLabel")
        left.addWidget(name_lab)
        self.name_edit = QLineEdit(self.theme_name)
        self.name_edit.setFixedHeight(28)
        left.addWidget(self.name_edit)

        orient_lab = QLabel("Orientation")
        orient_lab.setObjectName("fieldLabel")
        left.addWidget(orient_lab)
        orient_row = QHBoxLayout()
        orient_row.setSpacing(6)
        self.orient_combo = QComboBox()
        self.orient_combo.addItem("Vertical", "portrait")
        self.orient_combo.addItem("Horizontal", "landscape")
        self.orient_combo.setFixedHeight(28)
        self.orient_combo.setMinimumWidth(140)
        orient_row.addWidget(self.orient_combo)
        self.flip_check = QCheckBox("Flip 180°")
        self.flip_check.setChecked(bool(session.flip))
        orient_row.addWidget(self.flip_check)
        orient_row.addStretch(1)
        left.addLayout(orient_row)

        self.canvas = Canvas()
        left.addWidget(self.canvas, alignment=Qt.AlignmentFlag.AlignLeft)
        left.addStretch(1)
        layout.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(10)

        top = QGridLayout()
        top.setHorizontalSpacing(8)
        top.setVerticalSpacing(4)
        bg_lab = QLabel("Background")
        bg_lab.setObjectName("fieldLabel")
        top.addWidget(bg_lab, 0, 0, 1, 2)
        font_lab = QLabel("Font")
        font_lab.setObjectName("fieldLabel")
        top.addWidget(font_lab, 0, 2, 1, 3)

        self.btn_browse_bg = QPushButton("Choose…")
        self.btn_browse_bg.setFixedWidth(96)
        self.btn_browse_bg.setToolTip("Pick a full-screen wallpaper")
        top.addWidget(self.btn_browse_bg, 1, 0)
        self.btn_adjust_bg = QPushButton("Adjust…")
        self.btn_adjust_bg.setFixedWidth(88)
        self.btn_adjust_bg.setEnabled(False)
        top.addWidget(self.btn_adjust_bg, 1, 1)

        self.insp_font = QComboBox()
        self.insp_font.addItems(self._fonts)
        top.addWidget(self.insp_font, 1, 2)
        self.insp_font_size = QSpinBox()
        self.insp_font_size.setRange(8, 72)
        self.insp_font_size.setValue(18)
        self.insp_font_size.setFixedWidth(64)
        top.addWidget(self.insp_font_size, 1, 3)
        self.btn_color = QPushButton()
        self.btn_color.setFixedSize(32, 28)
        self.btn_color.setToolTip("Font color")
        self.btn_color.setStyleSheet(_swatch_style((240, 245, 250)))
        top.addWidget(self.btn_color, 1, 4)
        top.setColumnStretch(2, 1)
        right.addLayout(top)

        widgets_header = QHBoxLayout()
        widgets_header.addWidget(QLabel("Widgets"))
        widgets_header.addStretch(1)
        self.btn_add = QPushButton("Add")
        self.btn_del = QPushButton("Delete")
        widgets_header.addWidget(self.btn_add)
        widgets_header.addWidget(self.btn_del)
        right.addLayout(widgets_header)

        right.addWidget(widgets_list_header())

        self.list = QListWidget()
        self.list.setObjectName("widgetsList")
        self.list.setSpacing(0)
        self.list.setUniformItemSizes(True)
        self.list.setAlternatingRowColors(True)
        self.list.setStyleSheet(
            """
            QListWidget#widgetsList {
                padding: 0;
                outline: none;
            }
            QListWidget#widgetsList::item {
                padding: 0;
                margin: 0;
                border: none;
            }
            QListWidget#widgetsList::item:selected {
                background: rgba(0, 120, 212, 0.14);
            }
            QListWidget#widgetsList::item:hover {
                background: rgba(0, 0, 0, 0.04);
            }
            """
        )
        right.addWidget(self.list, 1)

        pos_lab = QLabel("Position")
        pos_lab.setObjectName("fieldLabel")
        right.addWidget(pos_lab)
        geom = QGridLayout()
        geom.setHorizontalSpacing(10)
        geom.setVerticalSpacing(6)
        self.insp_x = QSpinBox()
        self.insp_x.setRange(0, 480)
        self.insp_y = QSpinBox()
        self.insp_y.setRange(0, 480)
        self.insp_w = QSpinBox()
        self.insp_w.setRange(10, 480)
        self.insp_h = QSpinBox()
        self.insp_h.setRange(4, 480)
        for spin in (self.insp_x, self.insp_y, self.insp_w, self.insp_h):
            spin.setFixedHeight(28)
        geom.addWidget(QLabel("X"), 0, 0)
        geom.addWidget(self.insp_x, 0, 1)
        geom.addWidget(QLabel("Y"), 0, 2)
        geom.addWidget(self.insp_y, 0, 3)
        geom.addWidget(QLabel("W"), 1, 0)
        geom.addWidget(self.insp_w, 1, 1)
        geom.addWidget(QLabel("H"), 1, 2)
        geom.addWidget(self.insp_h, 1, 3)
        geom.setColumnStretch(1, 1)
        geom.setColumnStretch(3, 1)
        right.addLayout(geom)

        apply_row = QVBoxLayout()
        apply_row.setSpacing(4)
        self.apply_status = QLabel("")
        self.apply_status.setObjectName("fieldLabel")
        self.apply_status.setVisible(False)
        self.apply_progress = QProgressBar()
        self.apply_progress.setRange(0, 100)
        self.apply_progress.setValue(0)
        self.apply_progress.setTextVisible(True)
        self.apply_progress.setFormat("%p%")
        self.apply_progress.setFixedHeight(14)
        self.apply_progress.setVisible(False)
        apply_row.addWidget(self.apply_status)
        apply_row.addWidget(self.apply_progress)
        right.addLayout(apply_row)

        actions = QHBoxLayout()
        self.btn_preview = QPushButton("Preview on LCD")
        self.btn_preview.setObjectName("primary")
        self.btn_apply = QPushButton("Save + Apply")
        self.btn_new = QPushButton("New")
        self.btn_load = QPushButton("Load")
        actions.addWidget(self.btn_preview)
        actions.addWidget(self.btn_apply)
        actions.addWidget(self.btn_new)
        actions.addWidget(self.btn_load)
        right.addLayout(actions)
        layout.addLayout(right, 1)

        self.btn_preview.clicked.connect(self.preview)
        self.btn_apply.clicked.connect(self.save_and_apply)
        self.btn_new.clicked.connect(self.new_theme)
        self.btn_load.clicked.connect(self.load_existing)
        self.btn_add.clicked.connect(lambda: self.add_widget("text"))
        self.btn_del.clicked.connect(self.delete_widget)
        self.list.currentRowChanged.connect(self.on_list_select)
        self.btn_color.clicked.connect(self.pick_font_color)
        self.btn_browse_bg.clicked.connect(self.browse_background)
        self.btn_adjust_bg.clicked.connect(self.adjust_background)
        self.orient_combo.currentIndexChanged.connect(self.on_orientation_changed)
        self.insp_font.currentTextChanged.connect(self.write_font)
        self.insp_font_size.valueChanged.connect(self.write_font)
        for spin in (self.insp_x, self.insp_y, self.insp_w, self.insp_h):
            spin.valueChanged.connect(self.write_geometry)

        self._apply_timer = QTimer(self)
        self._apply_timer.setInterval(50)
        self._apply_timer.timeout.connect(self._refresh_apply_progress)

        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=self._on_delete_key)

        self.load_theme_named(self.theme_name)

    def widgets(self) -> list[dict[str, Any]]:
        return list(self.theme.get("widgets") or [])

    def canvas_size(self) -> tuple[int, int]:
        if self._orient == "landscape":
            return 480, 320
        return 320, 480

    def on_orientation_changed(self) -> None:
        if self._syncing:
            return
        orient = str(self.orient_combo.currentData() or "portrait")
        if orient == self._orient:
            return
        self._orient = orient
        self.theme.setdefault("display", {})["DISPLAY_ORIENTATION"] = orient
        w, h = self.canvas_size()
        self.canvas.set_screen_size(w, h)
        # Keep widgets on-canvas
        for widget in self.widgets():
            _clamp_widget(widget, w, h)
        self.canvas.set_widgets(self.widgets())
        self._rebuild_pending_preview()
        self.load_inspector()

    def _rebuild_pending_preview(self) -> None:
        w, h = self.canvas_size()
        if self._pending_src is not None and self._pending_src.is_file():
            try:
                raw = Image.open(self._pending_src)
                self._pending_preview = _fit_image(
                    raw, w, h, self._pending_fit, pan=self._pending_pan
                ).convert("RGB")
            except OSError:
                self._pending_preview = None
        elif self._pending_preview is not None:
            # Refit existing preview bitmap to new size via re-open path if possible
            self._pending_preview = None
        self._refresh_canvas_bg()

    def _theme_work_dir(self) -> Path:
        name = (self.name_edit.text().strip() or self.theme_name or "custom").strip()
        try:
            return resolve_theme_dir(name)
        except FileNotFoundError:
            dest = product_themes_dir() / name
            dest.mkdir(parents=True, exist_ok=True)
            return dest

    def set_widgets(self, widgets: list[dict[str, Any]], *, select: Optional[int] = None) -> None:
        widgets, _ = _strip_image_widgets(widgets)
        self.theme["widgets"] = widgets
        self.canvas.set_widgets(widgets)
        self._rebuild_rows(select if select is not None else self.canvas.selected)

    def _rebuild_rows(self, select: int = -1) -> None:
        self._syncing = True
        self.list.blockSignals(True)
        self.list.clear()
        self._rows.clear()
        widgets = self.widgets()
        for i, w in enumerate(widgets):
            item = QListWidgetItem()
            row = WidgetRow()
            row.set_index(i + 1)
            row.set_data(w)
            row.changed.connect(lambda idx=i: self.on_row_changed(idx))
            row.accent_clicked.connect(lambda idx=i: self.pick_accent_color(idx))
            row.activated.connect(lambda idx=i: self._select_row(idx))
            item.setSizeHint(row.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            self._rows.append(row)
        self.list.blockSignals(False)
        self._syncing = False
        if 0 <= select < len(widgets):
            self.list.setCurrentRow(select)
            self.canvas.selected = select
        elif widgets:
            self.list.setCurrentRow(0)
            self.canvas.selected = 0
        else:
            self.canvas.selected = -1
        self.canvas.update()
        self.load_inspector()

    def _select_row(self, idx: int) -> None:
        if self.list.currentRow() != idx:
            self.list.setCurrentRow(idx)
        self.canvas.selected = idx
        self.canvas.update()
        self.load_inspector()

    def _refresh_canvas_bg(self) -> None:
        w, h = self.canvas_size()
        if self._pending_preview is not None:
            if self._pending_preview.size != (w, h) and self._pending_src and self._pending_src.is_file():
                try:
                    raw = Image.open(self._pending_src)
                    self._pending_preview = _fit_image(
                        raw, w, h, self._pending_fit, pan=self._pending_pan
                    ).convert("RGB")
                except OSError:
                    pass
            self.canvas.set_background(self._pending_preview)
            self.btn_adjust_bg.setEnabled(self._pending_src is not None and self._pending_src.is_file())
            name = self._pending_src.name if self._pending_src else "background"
            self.btn_browse_bg.setToolTip(f"Wallpaper: {name}")
            return
        theme_dir = self._theme_work_dir()
        fit = str(self.theme.get("background_fit") or "cover")
        pan_raw = self.theme.get("background_pan") or [0.5, 0.5]
        try:
            pan = (float(pan_raw[0]), float(pan_raw[1]))
        except (TypeError, ValueError, IndexError):
            pan = (0.5, 0.5)
        candidates: list[Path] = []
        rel = str(self.theme.get("background") or "").strip()
        if rel:
            candidates.append(theme_dir / rel)
        for name in (
            "background_src.png",
            "background_src.jpg",
            "background_src.jpeg",
            "background_src.webp",
            "background.png",
        ):
            candidates.append(theme_dir / name)
        src = next((p for p in candidates if p.is_file()), None)
        if src is None:
            self.canvas.set_background(None)
            self.btn_adjust_bg.setEnabled(False)
            self.btn_browse_bg.setToolTip("Pick a full-screen wallpaper")
            return
        try:
            raw = Image.open(src)
            preview = _fit_image(raw, w, h, fit, pan=pan).convert("RGB")
            self._pending_src = src
            self._pending_fit = fit
            self._pending_pan = pan
            self._pending_preview = preview
            self.canvas.set_background(preview)
            self.btn_adjust_bg.setEnabled(True)
            self.btn_browse_bg.setToolTip(f"Wallpaper: {src.name}")
        except OSError:
            self.canvas.set_background(None)
            self.btn_adjust_bg.setEnabled(False)

    def load_theme_named(self, name: str) -> None:
        try:
            data = load_theme(name)
        except FileNotFoundError:
            data = default_studio_theme(name)
        data = migrate_static_text_to_widgets(data)
        if not data.get("widgets"):
            data = default_studio_theme(name)
        widgets, img_path = _strip_image_widgets(list(data.get("widgets") or []))
        data["widgets"] = widgets
        self.theme = data
        self.theme_name = name
        self.name_edit.setText(name)
        self._pending_src = None
        self._pending_preview = None
        self._pending_fit = str(data.get("background_fit") or "cover")
        pan_raw = data.get("background_pan") or [0.5, 0.5]
        try:
            self._pending_pan = (float(pan_raw[0]), float(pan_raw[1]))
        except (TypeError, ValueError, IndexError):
            self._pending_pan = (0.5, 0.5)
        orient = str((data.get("display") or {}).get("DISPLAY_ORIENTATION") or "portrait").lower()
        if orient not in ("portrait", "landscape"):
            orient = "portrait"
        self._orient = orient
        self._syncing = True
        oi = self.orient_combo.findData(orient)
        if oi >= 0:
            self.orient_combo.setCurrentIndex(oi)
        self.flip_check.setChecked(bool(self.session.flip))
        self._syncing = False
        cw, ch = self.canvas_size()
        self.canvas.set_screen_size(cw, ch)
        if img_path and not data.get("background"):
            p = self._theme_work_dir() / img_path
            if p.is_file():
                data["background"] = img_path
        self.set_widgets(widgets, select=0 if widgets else -1)
        self._refresh_canvas_bg()

    def add_widget(self, kind: str = "text") -> None:
        widgets = self.widgets()
        if kind == "top_processes" and any(w.get("type") == "top_processes" for w in widgets):
            QMessageBox.information(self, "Top processes", "Only one Top Processes widget is allowed.")
            return
        w = _defaults_for_type(kind)
        w["y"] = 20 + 24 * len(widgets)
        w["font"] = self.insp_font.currentText() or DEFAULT_FONT
        widgets.append(w)
        self.set_widgets(widgets, select=len(widgets) - 1)

    def delete_widget(self) -> None:
        idx = self.canvas.selected
        widgets = self.widgets()
        if 0 <= idx < len(widgets):
            widgets.pop(idx)
            nxt = min(idx, len(widgets) - 1)
            self.set_widgets(widgets, select=nxt)

    def _on_delete_key(self) -> None:
        focus = self.focusWidget()
        if isinstance(focus, (QLineEdit, QSpinBox)):
            return
        self.delete_widget()

    def on_list_select(self, row: int) -> None:
        if self._syncing:
            return
        self.canvas.selected = row
        self.canvas.update()
        self.load_inspector()

    def on_canvas_select(self) -> None:
        row = self.canvas.selected
        if row != self.list.currentRow():
            self.list.blockSignals(True)
            self.list.setCurrentRow(row)
            self.list.blockSignals(False)
        self.load_inspector()

    def on_row_changed(self, idx: int) -> None:
        if self._syncing:
            return
        widgets = self.widgets()
        if not (0 <= idx < len(widgets)) or idx >= len(self._rows):
            return
        w = widgets[idx]
        new_type = self._rows[idx].type_combo.currentText()
        if new_type == "top_processes" and w.get("type") != "top_processes":
            if any(i != idx and x.get("type") == "top_processes" for i, x in enumerate(widgets)):
                QMessageBox.information(self, "Top processes", "Only one Top Processes widget is allowed.")
                self._rows[idx].set_data(w)
                return
        self._rows[idx].apply_to(w)
        self.theme["widgets"] = widgets
        self.canvas.set_widgets(widgets)
        self.canvas.selected = idx
        self.canvas.update()
        self.load_inspector()
        self._rows[idx].set_data(w)

    def load_inspector(self) -> None:
        idx = self.canvas.selected
        widgets = self.widgets()
        enabled = 0 <= idx < len(widgets)
        for spin in (self.insp_x, self.insp_y, self.insp_w, self.insp_h):
            spin.setEnabled(enabled)
        self.insp_font.setEnabled(enabled)
        self.insp_font_size.setEnabled(enabled)
        self.btn_color.setEnabled(enabled)
        if not enabled:
            return
        w = widgets[idx]
        kind = str(w.get("type"))
        self._syncing = True
        for spin in (self.insp_x, self.insp_y, self.insp_w, self.insp_h, self.insp_font_size):
            spin.blockSignals(True)
        self.insp_font.blockSignals(True)

        self.insp_x.setValue(int(w.get("x", 0)))
        self.insp_y.setValue(int(w.get("y", 0)))
        self.insp_w.setValue(int(w.get("width", w.get("size", 100))))
        self.insp_h.setValue(int(w.get("height", 22 if kind in ("label", "text") else 14)))
        # All widgets are scalable; gauge/ring keep square via write_geometry
        self.insp_w.setEnabled(True)
        self.insp_h.setEnabled(kind not in ("gauge", "ring"))
        max_w = max(10, self.canvas.screen_w - int(w.get("x", 0)))
        max_h = max(4, self.canvas.screen_h - int(w.get("y", 0)))
        self.insp_w.setMaximum(max(10, self.canvas.screen_w))
        self.insp_h.setMaximum(max(4, self.canvas.screen_h))
        self.insp_x.setMaximum(max(0, self.canvas.screen_w - 1))
        self.insp_y.setMaximum(max(0, self.canvas.screen_h - 1))
        _ = max_w, max_h  # limits enforced in write_geometry / clamp

        font = str(w.get("font", DEFAULT_FONT))
        fi = self.insp_font.findText(font)
        if fi < 0 and self._fonts:
            self.insp_font.addItem(font)
            fi = self.insp_font.findText(font)
        if fi >= 0:
            self.insp_font.setCurrentIndex(fi)
        self.insp_font_size.setValue(int(w.get("font_size", 16)))
        uses_font = kind in ("label", "text", "gauge", "ring", "top_processes")
        self.insp_font.setEnabled(uses_font)
        self.insp_font_size.setEnabled(uses_font)
        self.btn_color.setEnabled(uses_font)
        self.btn_color.setStyleSheet(_swatch_style(_list_to_qcolor(w.get("color")).getRgb()[:3]))

        for spin in (self.insp_x, self.insp_y, self.insp_w, self.insp_h, self.insp_font_size):
            spin.blockSignals(False)
        self.insp_font.blockSignals(False)
        self._syncing = False

    def sync_inspector_pos(self) -> None:
        idx = self.canvas.selected
        widgets = self.widgets()
        if not (0 <= idx < len(widgets)):
            return
        w = widgets[idx]
        self.insp_x.blockSignals(True)
        self.insp_y.blockSignals(True)
        self.insp_x.setValue(int(w.get("x", 0)))
        self.insp_y.setValue(int(w.get("y", 0)))
        self.insp_x.blockSignals(False)
        self.insp_y.blockSignals(False)

    def sync_inspector_geom(self) -> None:
        idx = self.canvas.selected
        widgets = self.widgets()
        if not (0 <= idx < len(widgets)):
            return
        w = widgets[idx]
        for spin in (self.insp_x, self.insp_y, self.insp_w, self.insp_h):
            spin.blockSignals(True)
        self.insp_x.setValue(int(w.get("x", 0)))
        self.insp_y.setValue(int(w.get("y", 0)))
        self.insp_w.setValue(int(w.get("width", w.get("size", 100))))
        self.insp_h.setValue(int(w.get("height", w.get("width", w.get("size", 14)))))
        for spin in (self.insp_x, self.insp_y, self.insp_w, self.insp_h):
            spin.blockSignals(False)

    def write_geometry(self) -> None:
        if self._syncing:
            return
        idx = self.canvas.selected
        widgets = self.widgets()
        if not (0 <= idx < len(widgets)):
            return
        w = widgets[idx]
        kind = w.get("type")
        w["x"] = self.insp_x.value()
        w["y"] = self.insp_y.value()
        if kind in ("gauge", "ring"):
            s = self.insp_w.value()
            w["width"] = s
            w["size"] = s
        else:
            w["width"] = self.insp_w.value()
            w["height"] = self.insp_h.value()
        _clamp_widget(w, self.canvas.screen_w, self.canvas.screen_h)
        self.sync_inspector_geom()
        self.canvas.update()

    def write_font(self) -> None:
        if self._syncing:
            return
        idx = self.canvas.selected
        widgets = self.widgets()
        if not (0 <= idx < len(widgets)):
            return
        w = widgets[idx]
        w["font"] = self.insp_font.currentText() or DEFAULT_FONT
        w["font_size"] = self.insp_font_size.value()
        self.canvas.update()

    def browse_background(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose background image", "", IMAGE_FILTER)
        if not path:
            return
        src = Path(path)
        if not src.is_file():
            QMessageBox.warning(self, "Background", "File not found.")
            return
        sw, sh = self.canvas_size()
        dlg = BackgroundFitDialog(
            src, self, fit="cover", pan=(0.5, 0.5), screen_w=sw, screen_h=sh
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        # Keep a studio-local copy so we never overwrite the live theme until Save
        ext = src.suffix.lower() or ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"):
            ext = ".png"
        local = self._tmp_dir / f"pending_src{ext}"
        try:
            shutil.copy2(src, local)
        except OSError as exc:
            QMessageBox.warning(self, "Background", f"Could not copy image:\n{exc}")
            return
        self._pending_src = local
        self._pending_fit = dlg.chosen_fit()
        self._pending_pan = dlg.chosen_pan()
        self._pending_preview = dlg.chosen_image()
        self.canvas.set_background(self._pending_preview)
        self.btn_adjust_bg.setEnabled(True)
        self.btn_browse_bg.setToolTip(f"Wallpaper: {src.name}")

    def adjust_background(self) -> None:
        if self._pending_src is None or not self._pending_src.is_file():
            return
        sw, sh = self.canvas_size()
        dlg = BackgroundFitDialog(
            self._pending_src,
            self,
            fit=self._pending_fit,
            pan=self._pending_pan,
            screen_w=sw,
            screen_h=sh,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._pending_fit = dlg.chosen_fit()
        self._pending_pan = dlg.chosen_pan()
        self._pending_preview = dlg.chosen_image()
        self.canvas.set_background(self._pending_preview)

    def _commit_pending_background(self, theme_dir: Path) -> None:
        if self._pending_src is None or not self._pending_src.is_file():
            return
        theme_dir.mkdir(parents=True, exist_ok=True)
        ext = self._pending_src.suffix.lower() or ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"):
            ext = ".png"
        dest_src = theme_dir / f"background_src{ext}"
        if self._pending_src.resolve() != dest_src.resolve():
            shutil.copy2(self._pending_src, dest_src)
        preview = self._pending_preview
        if preview is None:
            raw = Image.open(dest_src)
            sw, sh = self.canvas_size()
            preview = _fit_image(raw, sw, sh, self._pending_fit, pan=self._pending_pan).convert("RGB")
        # Always keep a portrait-sized background.png for tools that expect 320x480,
        # plus the source + fit/pan metadata for correct landscape rendering.
        if preview.size != (320, 480):
            raw = Image.open(dest_src)
            portrait = _fit_image(raw, 320, 480, self._pending_fit, pan=self._pending_pan).convert("RGB")
            portrait.save(theme_dir / "background.png")
        else:
            preview.save(theme_dir / "background.png")
        self.theme["background"] = dest_src.name
        self.theme["background_fit"] = self._pending_fit
        self.theme["background_pan"] = [self._pending_pan[0], self._pending_pan[1]]
        self._pending_src = dest_src

    def pick_font_color(self) -> None:
        idx = self.canvas.selected
        widgets = self.widgets()
        if not (0 <= idx < len(widgets)):
            return
        w = widgets[idx]
        current = _list_to_qcolor(w.get("color"))
        color = QColorDialog.getColor(current, self, "Font color")
        if color.isValid():
            w["color"] = _color_to_list(color)
            self.btn_color.setStyleSheet(_swatch_style(_color_to_list(color)))
            self.canvas.update()

    def pick_accent_color(self, idx: int) -> None:
        widgets = self.widgets()
        if not (0 <= idx < len(widgets)):
            return
        w = widgets[idx]
        if w.get("type") not in ACCENT_TYPES:
            return
        current = _list_to_qcolor(w.get("bar_color") or w.get("accent"), (90, 180, 255))
        color = QColorDialog.getColor(current, self, "Accent color")
        if color.isValid():
            w["bar_color"] = _color_to_list(color)
            if idx < len(self._rows):
                self._rows[idx].set_data(w)
            self.canvas.update()

    def build_theme_dict(self) -> dict[str, Any]:
        name = self.name_edit.text().strip() or "custom"
        data = copy.deepcopy(self.theme)
        data["widgets"] = _strip_image_widgets(self.widgets())[0]
        data["static_text"] = {}
        if self._pending_src is not None:
            data["background"] = self.theme.get("background") or self._pending_src.name
            data["background_fit"] = self._pending_fit
            data["background_pan"] = [self._pending_pan[0], self._pending_pan[1]]
        data.setdefault("display", {})["DISPLAY_ORIENTATION"] = self._orient
        data.setdefault("display", {})["DISPLAY_SIZE"] = '3.5"'
        data["_name"] = name
        return data

    def preview(self) -> None:
        """Render + push on a worker thread so the UI stays responsive."""
        if self._preview_busy:
            return
        self._preview_busy = True
        self.btn_preview.setEnabled(False)
        self._preview_timer.stop()

        data = self.build_theme_dict()
        metrics = self.session.metrics.snapshot()
        work = self._theme_work_dir()
        if self._pending_src is not None and self._pending_src.is_file():
            data["background"] = str(self._pending_src)
            data["background_fit"] = self._pending_fit
            data["background_pan"] = [self._pending_pan[0], self._pending_pan[1]]
        data["_dir"] = str(work)
        flip = self.flip_check.isChecked()

        def _work() -> None:
            err: Optional[str] = None
            try:
                frame = render_theme(data, metrics)
                saved_flip = self.session.flip
                self.session.flip = flip
                try:
                    self.session.preview_image(frame, hold=True)
                finally:
                    self.session.flip = saved_flip
            except Exception as exc:
                err = str(exc)
                try:
                    self.session.end_preview()
                except Exception:
                    pass
            self._preview_finished.emit(err)

        threading.Thread(target=_work, name="theme-preview", daemon=True).start()

    def _on_preview_finished(self, err: object) -> None:
        self._preview_busy = False
        self.btn_preview.setEnabled(True)
        if err:
            QMessageBox.warning(self, "Preview failed", str(err))
            return
        self._preview_timer.start(6000)

    def _end_preview(self) -> None:
        self.session.end_preview()

    def save(self) -> Optional[str]:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Save", "Theme name required")
            return None
        tops = [w for w in self.widgets() if w.get("type") == "top_processes"]
        if len(tops) > 1:
            QMessageBox.warning(self, "Save", "Only one Top Processes widget is allowed.")
            return None
        dest = product_themes_dir() / name
        dest.mkdir(parents=True, exist_ok=True)
        self._commit_pending_background(dest)
        data = self.build_theme_dict()
        save_theme(name, data)
        ensure_background(dest)
        data["_dir"] = str(dest)
        self.theme = data
        self.theme_name = name
        return name

    def _set_applying(self, active: bool, message: str = "") -> None:
        self.apply_status.setText(message)
        self.apply_status.setVisible(active)
        self.apply_progress.setVisible(active)
        if active:
            self.apply_progress.setValue(0)
            self._apply_timer.start()
        else:
            self._apply_timer.stop()
            self.apply_progress.setValue(0)
        for btn in (
            self.btn_preview,
            self.btn_apply,
            self.btn_new,
            self.btn_load,
            self.btn_add,
            self.btn_del,
            self.btn_browse_bg,
            self.btn_adjust_bg,
        ):
            btn.setEnabled(not active)

    def _refresh_apply_progress(self) -> None:
        if self.session.ui_busy:
            self.apply_progress.setValue(int(self.session.send_progress))

    def save_and_apply(self) -> None:
        self._set_applying(True, "Saving theme…")
        try:
            name = self.save()
        except Exception as exc:
            self._set_applying(False)
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        if not name:
            self._set_applying(False)
            return
        self.apply_status.setText("Applying to LCD…")
        orient = self._orient
        flip = self.flip_check.isChecked()
        self.session.begin_busy()

        def _work() -> None:
            err: Optional[str] = None
            try:
                self.session.orientation = orient
                self.session.flip = flip
                self.session.config.setdefault("display", {})["DISPLAY_ORIENTATION"] = orient
                self.session.config.setdefault("display", {})["DISPLAY_REVERSE"] = flip
                from app.config_store import save_config

                save_config(self.session.config)
                self.session.set_theme(name)
                if not self.session.running:
                    self.session.start()
            except Exception as exc:
                err = str(exc)
            self._apply_finished.emit(err)

        threading.Thread(target=_work, name="theme-apply", daemon=True).start()

    def _on_apply_finished(self, err: object) -> None:
        try:
            if err:
                QMessageBox.warning(self, "Apply failed", str(err))
                return
            if callable(self.on_applied):
                self.on_applied()
            self.apply_progress.setValue(100)
            self.apply_status.setText("Done")
            self.close()
        finally:
            self.session.end_busy()
            self._set_applying(False)

    def new_theme(self) -> None:
        name, ok = QInputDialog.getText(self, "New theme", "Name:")
        if not ok or not name.strip():
            return
        self.theme = default_studio_theme(name.strip())
        self.theme_name = name.strip()
        self.name_edit.setText(self.theme_name)
        self._pending_src = None
        self._pending_preview = None
        self._orient = "portrait"
        self._syncing = True
        oi = self.orient_combo.findData("portrait")
        if oi >= 0:
            self.orient_combo.setCurrentIndex(oi)
        self.flip_check.setChecked(False)
        self._syncing = False
        self.canvas.set_screen_size(320, 480)
        self.canvas.set_background(None)
        self.btn_adjust_bg.setEnabled(False)
        self.btn_browse_bg.setToolTip("Pick a full-screen wallpaper")
        self.set_widgets(list(self.theme.get("widgets") or []), select=0)

    def load_existing(self) -> None:
        themes = list_themes(product_only=True) or list_themes()
        if not themes:
            return
        name, ok = QInputDialog.getItem(self, "Load theme", "Theme:", themes, 0, False)
        if ok and name:
            self.load_theme_named(name)

    def closeEvent(self, event) -> None:
        self._preview_timer.stop()
        self.session.end_preview()
        super().closeEvent(event)
