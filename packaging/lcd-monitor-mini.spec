# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for lcd-monitor-mini (UsbMonitor replacement).
# Build from repo root: pyinstaller packaging/lcd-monitor-mini.spec

import sys
from pathlib import Path

SPECDIR = Path(SPECPATH)
ROOT = SPECDIR.parent

block_cipher = None

datas = [
    (str(SPECDIR / "seed"), "seed"),
    (str(SPECDIR / "fonts"), "fonts"),
    (str(SPECDIR / "scripts"), "scripts"),
    (str(SPECDIR / "icon.ico"), "."),
    (str(SPECDIR / "icon.png"), "."),
    (str(ROOT / "app" / "assets"), "app/assets"),
]

hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "serial",
    "serial.tools.list_ports",
    "yaml",
    "psutil",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "numpy",
    "GPUtil",
    "app",
    "app.main",
    "app.connection",
    "app.display_session",
    "app.metrics",
    "app.renderer",
    "app.theme_service",
    "app.config_store",
    "app.paths",
    "app.protocol",
    "app.recovery",
    "app.autostart",
    "app.ui",
    "app.ui.settings",
    "app.ui.theme_studio",
]

a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "pandas"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="lcd-monitor-mini",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(SPECDIR / "icon.ico"),
    version=str(SPECDIR / "version_info.txt"),
    contents_directory=".",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="lcd-monitor-mini",
)
