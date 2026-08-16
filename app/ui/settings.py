"""Settings window + system tray (Fluent / Windows 11-inspired)."""
from __future__ import annotations

import threading

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from app.autostart import is_autostart_enabled, set_autostart
from app.display_session import DisplaySession
from app.metrics import list_nics
from app.theme_service import list_themes
from app.ui.chrome import FluentWindow, app_icon

APP_STYLE = """
QWidget {
    font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
    font-size: 13px;
    color: #1a1a1a;
}
QWidget#windowShell {
    background: #f3f3f3;
    border: 1px solid #d4d4d4;
    border-radius: 8px;
}
QWidget#windowBody {
    background: #f3f3f3;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
}
QWidget#titleBar {
    background: #ffffff;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    border-bottom: 1px solid #ebebeb;
}
QLabel#titleBarLabel {
    font-size: 13px;
    font-weight: 600;
    color: #1a1a1a;
}
QPushButton#titleBtn, QPushButton#titleBtnClose {
    background: transparent;
    border: none;
    border-radius: 4px;
    color: #1a1a1a;
    font-size: 14px;
    padding: 0;
    min-height: 0;
}
QPushButton#titleBtn:hover {
    background: #f0f0f0;
}
QPushButton#titleBtnClose:hover {
    background: #c42b1c;
    color: #ffffff;
}
QFrame#card {
    background: #ffffff;
    border: 1px solid #e8e8e8;
    border-radius: 8px;
}
QLabel#subtitle {
    font-size: 12px;
    color: #5c5c5c;
}
QLabel#section {
    font-size: 11px;
    font-weight: 600;
    color: #5c5c5c;
    letter-spacing: 0.4px;
}
QLabel#fieldLabel {
    color: #5c5c5c;
    font-size: 12px;
}
QLabel#status {
    color: #5c5c5c;
    font-size: 12px;
}
QLabel#statusError {
    color: #c42b1c;
    font-size: 12px;
}
QComboBox, QLineEdit, QSpinBox {
    background: #f9f9f9;
    border: 1px solid #d1d1d1;
    border-radius: 4px;
    padding: 6px 10px;
    min-height: 18px;
}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {
    border-color: #a0a0a0;
}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {
    border-color: #005fb8;
    background: #ffffff;
}
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #8a8a8a;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: #005fb8;
    border-color: #005fb8;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #d1d1d1;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
    background: #005fb8;
}
QSlider::sub-page:horizontal {
    background: #005fb8;
    border-radius: 2px;
}
QProgressBar {
    background: #e8e8e8;
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    max-height: 6px;
}
QProgressBar::chunk {
    background: #005fb8;
    border-radius: 3px;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #d1d1d1;
    border-radius: 4px;
    padding: 8px 16px;
    min-height: 20px;
}
QPushButton:hover {
    background: #f5f5f5;
    border-color: #a0a0a0;
}
QPushButton:pressed {
    background: #ebebeb;
}
QPushButton#primary {
    background: #005fb8;
    border: 1px solid #005fb8;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#primary:hover {
    background: #0067c0;
    border-color: #0067c0;
}
QPushButton#primary:pressed {
    background: #004e99;
}
QPushButton#danger {
    color: #c42b1c;
    border-color: #e0b4ae;
}
QPushButton#danger:hover {
    background: #fdf3f2;
}
QListWidget {
    background: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    padding: 4px;
}
QListWidget::item {
    padding: 6px 8px;
    border-radius: 4px;
}
QListWidget::item:selected {
    background: #e8f3ff;
    color: #1a1a1a;
}
QMenu {
    background: #ffffff;
    border: 1px solid #e0e0e0;
    padding: 4px;
}
QMenu::item {
    padding: 8px 24px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: #f0f0f0;
}
"""


def _card_shadow(widget: QWidget) -> None:
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(18)
    shadow.setOffset(0, 2)
    shadow.setColor(QColor(0, 0, 0, 28))
    widget.setGraphicsEffect(shadow)


class SettingsWindow(FluentWindow):
    _job_finished = Signal(object)  # None ok, str error

    def __init__(self, session: DisplaySession, open_studio_cb) -> None:
        super().__init__(title="lcd-monitor-mini")
        self.session = session
        self.open_studio_cb = open_studio_cb
        self.resize(440, 520)
        self.setMinimumWidth(400)
        self._job_busy = False
        self._job_finished.connect(self._on_job_finished)

        outer = self.body_layout

        card = QFrame()
        card.setObjectName("card")
        _card_shadow(card)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(14)

        card_layout.addWidget(self._section("Display"))

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list_themes(product_only=True) or list_themes())
        idx = self.theme_combo.findText(session.theme_name)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        card_layout.addLayout(self._field("Theme", self.theme_combo))

        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(5, 100)
        self.brightness.setValue(session.brightness)
        self.brightness_value = QLabel(f"{session.brightness}%")
        self.brightness_value.setObjectName("fieldLabel")
        self.brightness.valueChanged.connect(lambda v: self.brightness_value.setText(f"{v}%"))
        bright_row = QHBoxLayout()
        bright_row.addWidget(self.brightness, 1)
        bright_row.addWidget(self.brightness_value)
        bright_wrap = QWidget()
        bright_wrap.setLayout(bright_row)
        card_layout.addLayout(self._field("Brightness", bright_wrap))

        self.orient_combo = QComboBox()
        self.orient_combo.addItem("Vertical", "portrait")
        self.orient_combo.addItem("Horizontal", "landscape")
        ori_idx = self.orient_combo.findData(session.orientation)
        if ori_idx >= 0:
            self.orient_combo.setCurrentIndex(ori_idx)
        card_layout.addLayout(self._field("Orientation", self.orient_combo))
        orient_hint = QLabel("Horizontal rotates any theme to fill the panel.")
        orient_hint.setObjectName("subtitle")
        orient_hint.setWordWrap(True)
        card_layout.addWidget(orient_hint)

        self.flip = QCheckBox("Flip 180°")
        self.flip.setChecked(session.flip)
        card_layout.addWidget(self.flip)

        self.blank_idle = QCheckBox("Turn off LCD when PC is locked or sleeping")
        self.blank_idle.setChecked(bool(getattr(session, "blank_when_idle", True)))
        card_layout.addWidget(self.blank_idle)

        self.eco_mode = QCheckBox("Eco mode (lower CPU / USB — recommended)")
        self.eco_mode.setChecked(bool(getattr(session, "eco_mode", True)))
        self.eco_mode.setToolTip(
            "Slower refresh (~1s), quieter TRON animation, skip unchanged frames. "
            "Uncheck for smoother ~0.55s updates."
        )
        card_layout.addWidget(self.eco_mode)

        card_layout.addWidget(self._section("System"))

        self.nic_combo = QComboBox()
        nics = list_nics() or ["Ethernet"]
        self.nic_combo.addItems(nics)
        eth = session.metrics.eth_name
        if eth in nics:
            self.nic_combo.setCurrentText(eth)
        card_layout.addLayout(self._field("Network", self.nic_combo))

        weather_hint = QLabel("Weather uses Windows location (or IP if unavailable).")
        weather_hint.setObjectName("subtitle")
        weather_hint.setWordWrap(True)
        card_layout.addWidget(weather_hint)

        self.autostart = QCheckBox("Start with Windows")
        self.autostart.setChecked(is_autostart_enabled())
        card_layout.addWidget(self.autostart)

        outer.addWidget(card)

        status_row = QVBoxLayout()
        status_row.setSpacing(6)
        self.status = QLabel("Stopped")
        self.status.setObjectName("status")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        status_row.addWidget(self.status)
        status_row.addWidget(self.progress)
        outer.addLayout(status_row)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.setObjectName("primary")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("danger")
        self.btn_reconnect = QPushButton("Reconnect")
        self.btn_studio = QPushButton("Theme Studio")
        actions.addWidget(self.btn_apply)
        actions.addWidget(self.btn_stop)
        actions.addWidget(self.btn_reconnect)
        outer.addLayout(actions)
        outer.addWidget(self.btn_studio)
        outer.addStretch(1)

        self.btn_apply.clicked.connect(self.on_apply)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_reconnect.clicked.connect(self.on_reconnect)
        self.btn_studio.clicked.connect(self.open_studio)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(250)

    def open_studio(self) -> None:
        self.open_studio_cb(on_applied=self.sync_from_session)

    def sync_from_session(self) -> None:
        """Keep Settings controls in sync after Theme Studio Save+Apply."""
        themes = list_themes(product_only=True) or list_themes()
        current = self.session.theme_name
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        self.theme_combo.addItems(themes)
        idx = self.theme_combo.findText(current)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        elif current:
            self.theme_combo.addItem(current)
            self.theme_combo.setCurrentText(current)
        self.theme_combo.blockSignals(False)

        self.orient_combo.blockSignals(True)
        oi = self.orient_combo.findData(self.session.orientation)
        if oi >= 0:
            self.orient_combo.setCurrentIndex(oi)
        self.orient_combo.blockSignals(False)

        self.flip.blockSignals(True)
        self.flip.setChecked(self.session.flip)
        self.flip.blockSignals(False)

        self.blank_idle.blockSignals(True)
        self.blank_idle.setChecked(bool(self.session.blank_when_idle))
        self.blank_idle.blockSignals(False)

        self.eco_mode.blockSignals(True)
        self.eco_mode.setChecked(bool(getattr(self.session, "eco_mode", True)))
        self.eco_mode.blockSignals(False)

        self.brightness.blockSignals(True)
        self.brightness.setValue(self.session.brightness)
        self.brightness.blockSignals(False)
        self.brightness_value.setText(f"{self.session.brightness}%")

    def _section(self, text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setObjectName("section")
        return label

    def _field(self, label: str, widget: QWidget) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(4)
        lab = QLabel(label)
        lab.setObjectName("fieldLabel")
        col.addWidget(lab)
        col.addWidget(widget)
        return col

    def refresh_status(self) -> None:
        phase = self.session.ui_phase
        busy = self.session.ui_busy
        if not self.session.running and not busy and phase != "error":
            self.status.setObjectName("status")
            self.status.setText("Stopped")
            self.progress.setVisible(False)
            self._polish_status()
            return
        if busy and phase == "updating":
            self.status.setObjectName("status")
            self.status.setText("Updating…")
            self.progress.setVisible(True)
            self.progress.setValue(int(self.session.send_progress))
        elif phase == "error":
            self.status.setObjectName("statusError")
            self.status.setText(f"Error: {self.session.last_error or self.session.last_status}")
            self.progress.setVisible(False)
        elif phase == "disconnected":
            self.status.setObjectName("statusError")
            self.status.setText("Disconnected")
            self.progress.setVisible(False)
        else:
            self.status.setObjectName("status")
            self.status.setText("Connected" if self.session.running else "Stopped")
            self.progress.setVisible(False)
            self.progress.setValue(0)
        self._polish_status()

    def _polish_status(self) -> None:
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def on_stop(self) -> None:
        self.session.stop()

    def on_reconnect(self) -> None:
        if self._job_busy:
            return
        self._job_busy = True
        self.session.begin_busy()

        def _work() -> None:
            err = None
            try:
                self.session.reconnect()
            except Exception as exc:
                err = str(exc)
            self._job_finished.emit(err)

        threading.Thread(target=_work, name="settings-reconnect", daemon=True).start()

    def on_apply(self) -> None:
        if self._job_busy:
            return
        self._job_busy = True
        theme = self.theme_combo.currentText()
        brightness = self.brightness.value()
        nic = self.nic_combo.currentText()
        orient = str(self.orient_combo.currentData() or "portrait")
        flip = self.flip.isChecked()
        blank = self.blank_idle.isChecked()
        eco = self.eco_mode.isChecked()
        auto = self.autostart.isChecked()
        self.session.metrics.eth_name = nic
        self.session.metrics.weather_city = ""
        self.session.config.setdefault("config", {})["ETH"] = nic
        self.session.config.setdefault("config", {})["WEATHER_CITY"] = ""
        self.session.begin_busy()

        def _work() -> None:
            err = None
            try:
                if theme and theme != self.session.theme_name:
                    self.session.set_theme(theme)
                self.session.set_brightness(brightness)
                self.session.set_display_geometry(orient, flip)
                self.session.set_blank_when_idle(blank)
                self.session.set_eco_mode(eco)
                set_autostart(auto)
                if not self.session.running:
                    self.session.start()
            except Exception as exc:
                err = str(exc)
            self._job_finished.emit(err)

        threading.Thread(target=_work, name="settings-apply", daemon=True).start()

    def _on_job_finished(self, err: object) -> None:
        self._job_busy = False
        self.session.end_busy()
        if err:
            self.session.ui_phase = "error"
            self.session.last_error = str(err)
            QMessageBox.warning(self, "Action failed", str(err))

def install_tray(app, window: SettingsWindow, session: DisplaySession) -> QSystemTrayIcon:
    # Avoid duplicate tray icons if install_tray is called more than once.
    existing = app.property("_turing_tray")
    if existing is not None:
        try:
            existing.hide()
            existing.deleteLater()
        except Exception:
            pass

    tray = QSystemTrayIcon(window)
    icon = app_icon()
    tray.setIcon(icon if not icon.isNull() else window.windowIcon())
    tray.setToolTip("lcd-monitor-mini")
    tray.setObjectName("lcdMonitorMiniTray")

    from PySide6.QtWidgets import QMenu

    menu = QMenu()
    act_show = QAction("Settings", window)
    act_show.triggered.connect(window.showNormal)
    act_stop = QAction("Stop", window)
    act_stop.triggered.connect(window.on_stop)
    act_quit = QAction("Exit", window)

    def do_quit() -> None:
        tray.hide()
        session.stop()
        app.quit()

    act_quit.triggered.connect(do_quit)
    menu.addAction(act_show)
    menu.addAction(act_stop)
    menu.addSeparator()
    menu.addAction(act_quit)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: window.showNormal()
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    app.aboutToQuit.connect(tray.hide)
    tray.show()
    app.setProperty("_turing_tray", tray)
    return tray
