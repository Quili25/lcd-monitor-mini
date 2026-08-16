"""Windows lock / sleep detection → blank the LCD."""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from typing import Optional

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, Signal, Qt
from PySide6.QtWidgets import QApplication, QWidget

log = logging.getLogger("lcd.power")

WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_POWERSETTINGCHANGE = 0x8013
NOTIFY_FOR_THIS_SESSION = 0
DEVICE_NOTIFY_WINDOW_HANDLE = 0
DESKTOP_SWITCHDESKTOP = 0x0100


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


GUID_CONSOLE_DISPLAY_STATE = GUID(
    0x6FE69556,
    0x704A,
    0x47A0,
    (wintypes.BYTE * 8)(0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47),
)


class POWERBROADCAST_SETTING(ctypes.Structure):
    _fields_ = [
        ("PowerSetting", GUID),
        ("DataLength", wintypes.DWORD),
        ("Data", wintypes.BYTE * 1),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt_x", wintypes.LONG),
        ("pt_y", wintypes.LONG),
    ]


def workstation_is_locked() -> bool:
    """True when the Win+L secure desktop is active.

    OpenInputDesktop(DESKTOP_SWITCHDESKTOP) fails on the lock screen.
    """
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    handle = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if handle:
        user32.CloseDesktop(handle)
        return False
    return True


def _msg_from_message(message) -> Optional[MSG]:
    try:
        if isinstance(message, MSG):
            return message
        addr = int(message)
        if addr == 0:
            return None
        return ctypes.cast(addr, ctypes.POINTER(MSG)).contents
    except (TypeError, ValueError, OverflowError, ctypes.ArgumentError):
        return None


def _is_windows_msg(eventType) -> bool:
    if eventType is None:
        return False
    if isinstance(eventType, (bytes, bytearray)):
        et = bytes(eventType)
    else:
        try:
            et = bytes(eventType)
        except Exception:
            et = str(eventType).encode("utf-8", errors="ignore")
    return et in (b"windows_generic_MSG", b"windows_dispatcher_MSG")


class _IdleSink(QWidget):
    """Hidden Qt HWND that owns WTS / power notifications (survives Settings close)."""

    def __init__(self, watch: "WindowsIdleWatch") -> None:
        super().__init__(None)
        self._watch = watch
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.resize(1, 1)
        # Force a real HWND without showing the window.
        self.createWinId()

    def nativeEvent(self, eventType, message):  # noqa: N802
        self._watch._handle_native(eventType, message)
        return super().nativeEvent(eventType, message)


class WindowsIdleWatch(QObject, QAbstractNativeEventFilter):
    """Emits suspended/resumed when the PC locks, unlocks, sleeps, or wakes."""

    suspended = Signal(str)  # reason
    resumed = Signal(str)

    def __init__(self, parent=None) -> None:
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self._sink: Optional[_IdleSink] = None
        self._hpower = None
        self._registered = False
        self._idle = False
        self._poll = QTimer(self)
        self._poll.setInterval(750)
        self._poll.timeout.connect(self._poll_lock_state)

    @property
    def idle(self) -> bool:
        return self._idle

    def start(self, host: QWidget | None = None) -> None:
        """Start watching. ``host`` is ignored; a dedicated sink HWND is used."""
        del host  # kept for call-site compatibility
        if sys.platform != "win32" or self._registered:
            return

        self._sink = _IdleSink(self)
        hwnd = int(self._sink.winId())
        ok = bool(ctypes.windll.wtsapi32.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION))
        if not ok:
            err = ctypes.GetLastError()
            log.warning("WTSRegisterSessionNotification failed hwnd=%s err=%s", hwnd, err)
        else:
            log.info("WTS session notify registered hwnd=%s", hwnd)

        try:
            self._hpower = ctypes.windll.user32.RegisterPowerSettingNotification(
                wintypes.HANDLE(hwnd),
                ctypes.byref(GUID_CONSOLE_DISPLAY_STATE),
                DEVICE_NOTIFY_WINDOW_HANDLE,
            )
            if not self._hpower:
                log.warning(
                    "RegisterPowerSettingNotification failed err=%s",
                    ctypes.GetLastError(),
                )
        except Exception as exc:
            log.warning("RegisterPowerSettingNotification failed: %s", exc)
            self._hpower = None

        qapp = QApplication.instance()
        if qapp is not None:
            qapp.installNativeEventFilter(self)

        self._registered = True
        self._poll.start()
        # Sync immediately in case we started already locked (rare).
        self._poll_lock_state()
        log.info("idle watch started hwnd=%s (WTS + poll)", hwnd)

    def stop(self) -> None:
        self._poll.stop()
        if not self._registered:
            return
        hwnd = int(self._sink.winId()) if self._sink is not None else 0
        if hwnd:
            try:
                ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification(hwnd)
            except Exception:
                pass
        if self._hpower:
            try:
                ctypes.windll.user32.UnregisterPowerSettingNotification(self._hpower)
            except Exception:
                pass
            self._hpower = None
        qapp = QApplication.instance()
        if qapp is not None:
            qapp.removeNativeEventFilter(self)
        if self._sink is not None:
            self._sink.deleteLater()
            self._sink = None
        self._registered = False

    def _poll_lock_state(self) -> None:
        try:
            locked = workstation_is_locked()
        except Exception as exc:
            log.debug("lock poll failed: %s", exc)
            return
        if locked and not self._idle:
            self._go_idle("lock-poll")
        elif not locked and self._idle:
            # Only auto-resume from lock via poll; sleep/display-off resume
            # still comes from power / WTS unlock messages.
            # If we blanked for sleep, workstation may look "unlocked" while
            # suspended — avoid false resume: only clear lock-originated idle
            # when last reason was lock*, tracked below.
            if getattr(self, "_idle_reason", "").startswith("lock"):
                self._go_active("unlock-poll")

    def _go_idle(self, reason: str) -> None:
        if self._idle:
            return
        self._idle = True
        self._idle_reason = reason
        log.info("system idle: %s", reason)
        self.suspended.emit(reason)

    def _go_active(self, reason: str) -> None:
        if not self._idle:
            return
        self._idle = False
        self._idle_reason = ""
        log.info("system active: %s", reason)
        self.resumed.emit(reason)

    def _handle_native(self, eventType, message) -> None:
        if not _is_windows_msg(eventType):
            return
        msg = _msg_from_message(message)
        if msg is None:
            return

        if msg.message == WM_WTSSESSION_CHANGE:
            if msg.wParam == WTS_SESSION_LOCK:
                self._go_idle("lock")
            elif msg.wParam == WTS_SESSION_UNLOCK:
                self._go_active("unlock")
            return

        if msg.message == WM_POWERBROADCAST:
            if msg.wParam == PBT_APMSUSPEND:
                self._go_idle("sleep")
            elif msg.wParam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                if workstation_is_locked():
                    self._idle_reason = "lock"
                    log.info("wake while locked — keeping LCD blank")
                else:
                    self._go_active("wake")
            elif msg.wParam == PBT_POWERSETTINGCHANGE and msg.lParam:
                try:
                    pbs = POWERBROADCAST_SETTING.from_address(int(msg.lParam))
                    if (
                        pbs.PowerSetting.Data1 == GUID_CONSOLE_DISPLAY_STATE.Data1
                        and pbs.DataLength >= 1
                    ):
                        state = int(pbs.Data[0])
                        if state == 0:
                            self._go_idle("display-off")
                        elif state == 1:
                            # Don't wake from display-on if still Win+L locked.
                            if not workstation_is_locked():
                                self._go_active("display-on")
                except Exception:
                    pass

    def nativeEventFilter(self, eventType, message):  # noqa: N802
        self._handle_native(eventType, message)
        return False
