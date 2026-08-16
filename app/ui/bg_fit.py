"""Android-style background fit / pan dialog for Theme Studio."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PIL import Image

from app.renderer import _fit_image


def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


class FitPreview(QWidget):
    """Draggable cover preview of the wallpaper inside the LCD viewport."""

    def __init__(self, screen_w: int = 320, screen_h: int = 480, parent=None) -> None:
        super().__init__(parent)
        self.screen_w = max(1, screen_w)
        self.screen_h = max(1, screen_h)
        self.setFixedSize(self.screen_w, self.screen_h)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._src: Optional[Image.Image] = None
        self.fit = "cover"
        self.pan_x = 0.5
        self.pan_y = 0.5
        self._drag = False
        self._last = QPoint()

    def set_source(self, img: Image.Image) -> None:
        self._src = img.convert("RGBA")
        self.update()

    def result_image(self) -> Image.Image:
        if self._src is None:
            return Image.new("RGB", (self.screen_w, self.screen_h), (16, 20, 28))
        return _fit_image(
            self._src, self.screen_w, self.screen_h, self.fit, pan=(self.pan_x, self.pan_y)
        ).convert("RGB")

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(16, 20, 28))
        if self._src is not None:
            fitted = _fit_image(
                self._src, self.screen_w, self.screen_h, self.fit, pan=(self.pan_x, self.pan_y)
            )
            p.drawPixmap(0, 0, _pil_to_qpixmap(fitted))
        p.setPen(QPen(QColor(255, 255, 255, 40), 1, Qt.PenStyle.DotLine))
        for x in range(0, self.width() + 1, 40):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height() + 1, 40):
            p.drawLine(0, y, self.width(), y)
        p.setPen(QPen(QColor(90, 180, 255), 2))
        p.drawRect(1, 1, self.width() - 2, self.height() - 2)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.fit == "cover":
            self._drag = True
            self._last = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if not self._drag or self._src is None or self.fit != "cover":
            return
        pos = event.position().toPoint()
        dx = pos.x() - self._last.x()
        dy = pos.y() - self._last.y()
        self._last = pos
        sw, sh = self._src.size
        scale = max(self.screen_w / sw, self.screen_h / sh)
        nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
        max_x = max(1, nw - self.screen_w)
        max_y = max(1, nh - self.screen_h)
        self.pan_x = max(0.0, min(1.0, self.pan_x - dx / max_x))
        self.pan_y = max(0.0, min(1.0, self.pan_y - dy / max_y))
        self.update()

    def mouseReleaseEvent(self, _event) -> None:
        self._drag = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)


class BackgroundFitDialog(QDialog):
    """Choose how a wallpaper fills the LCD: cover+pan, contain, stretch, center."""

    def __init__(
        self,
        src_path: Path,
        parent=None,
        *,
        fit: str = "cover",
        pan: tuple[float, float] = (0.5, 0.5),
        screen_w: int = 320,
        screen_h: int = 480,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Adjust background")
        self.setModal(True)
        self.src_path = Path(src_path)
        self._src = Image.open(self.src_path)

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Drag to pan (cover). Or pick a preset / fit mode."))

        self.preview = FitPreview(screen_w, screen_h)
        self.preview.fit = fit if fit in ("cover", "contain", "stretch", "center") else "cover"
        self.preview.pan_x, self.preview.pan_y = pan
        self.preview.set_source(self._src)
        root.addWidget(self.preview, alignment=Qt.AlignmentFlag.AlignHCenter)

        row = QHBoxLayout()
        row.addWidget(QLabel("Fit"))
        self.fit_combo = QComboBox()
        for key, title in (
            ("cover", "Fill / crop"),
            ("contain", "Fit (letterbox)"),
            ("stretch", "Stretch"),
            ("center", "Center"),
        ):
            self.fit_combo.addItem(title, key)
        idx = self.fit_combo.findData(self.preview.fit)
        if idx >= 0:
            self.fit_combo.setCurrentIndex(idx)
        self.fit_combo.currentIndexChanged.connect(self._on_fit)
        row.addWidget(self.fit_combo, 1)
        root.addLayout(row)

        presets = QHBoxLayout()
        for label, fx, fy in (
            ("NW", 0.0, 0.0),
            ("N", 0.5, 0.0),
            ("NE", 1.0, 0.0),
            ("W", 0.0, 0.5),
            ("Center", 0.5, 0.5),
            ("E", 1.0, 0.5),
            ("SW", 0.0, 1.0),
            ("S", 0.5, 1.0),
            ("SE", 1.0, 1.0),
        ):
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            if label == "Center":
                btn.setMinimumWidth(64)
            else:
                btn.setFixedWidth(40)
            btn.clicked.connect(lambda _=False, x=fx, y=fy: self._snap(x, y))
            presets.addWidget(btn)
        root.addLayout(presets)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_fit(self) -> None:
        self.preview.fit = str(self.fit_combo.currentData() or "cover")
        self.preview.update()

    def _snap(self, fx: float, fy: float) -> None:
        self.preview.fit = "cover"
        fi = self.fit_combo.findData("cover")
        if fi >= 0:
            self.fit_combo.blockSignals(True)
            self.fit_combo.setCurrentIndex(fi)
            self.fit_combo.blockSignals(False)
        self.preview.pan_x = fx
        self.preview.pan_y = fy
        self.preview.update()

    def chosen_fit(self) -> str:
        return self.preview.fit

    def chosen_pan(self) -> tuple[float, float]:
        return self.preview.pan_x, self.preview.pan_y

    def chosen_image(self) -> Image.Image:
        return self.preview.result_image()
