"""Shared Fluent chrome: custom title bar + app icon."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QIcon, QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.paths import install_dir, resource_dir


def app_icon() -> QIcon:
    candidates = [
        resource_dir() / "icon.ico",
        resource_dir() / "icon.png",
        Path(__file__).resolve().parents[1] / "assets" / "icon.ico",
        Path(__file__).resolve().parents[1] / "assets" / "icon.png",
        install_dir() / "icon.ico",
        install_dir() / "icon.png",
    ]
    for path in candidates:
        if path.is_file():
            return QIcon(str(path))
    return QIcon()


class TitleBar(QWidget):
    """Minimal Fluent-style title bar for frameless windows."""

    close_clicked = Signal()
    minimize_clicked = Signal()

    def __init__(self, title: str = "lcd-monitor-mini", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(40)
        self._drag_pos: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 4, 0)
        layout.setSpacing(8)

        icon = QLabel()
        pix = app_icon().pixmap(18, 18)
        if not pix.isNull():
            icon.setPixmap(pix)
        icon.setFixedSize(20, 20)
        layout.addWidget(icon)

        self.title = QLabel(title)
        self.title.setObjectName("titleBarLabel")
        layout.addWidget(self.title, 1)

        self.btn_min = QPushButton("–")
        self.btn_min.setObjectName("titleBtn")
        self.btn_min.setFixedSize(40, 32)
        self.btn_min.clicked.connect(self.minimize_clicked.emit)
        layout.addWidget(self.btn_min)

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("titleBtnClose")
        self.btn_close.setFixedSize(40, 32)
        self.btn_close.clicked.connect(self.close_clicked.emit)
        layout.addWidget(self.btn_close)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None


class FluentWindow(QMainWindow):
    """Frameless main window with Fluent title bar."""

    def __init__(self, title: str = "lcd-monitor-mini", parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        icon = app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        shell = QWidget()
        shell.setObjectName("windowShell")
        self.setCentralWidget(shell)
        self._shell_layout = QVBoxLayout(shell)
        self._shell_layout.setContentsMargins(1, 1, 1, 1)
        self._shell_layout.setSpacing(0)

        self.title_bar = TitleBar(title)
        self.title_bar.close_clicked.connect(self.close)
        self.title_bar.minimize_clicked.connect(self.showMinimized)
        self._shell_layout.addWidget(self.title_bar)

        self.body = QWidget()
        self.body.setObjectName("windowBody")
        self.body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._shell_layout.addWidget(self.body, 1)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(20, 16, 20, 20)
        self.body_layout.setSpacing(16)
