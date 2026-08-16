"""Install vs userdata path resolution (dev + frozen PyInstaller)."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "lcd-monitor-mini"
LEGACY_APP_NAME = "turing-lcd"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def install_dir() -> Path:
    """Directory containing the executable (or repo root in dev)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_dir() -> Path:
    """Read-only bundled resources (PyInstaller extract dir or repo root)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    """Writable per-user data: config + themes."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    path = base / APP_NAME
    legacy = base / LEGACY_APP_NAME
    if not path.exists() and legacy.is_dir():
        try:
            shutil.copytree(legacy, path)
        except OSError:
            path.mkdir(parents=True, exist_ok=True)
    else:
        path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.yaml"


def themes_dir() -> Path:
    path = data_dir() / "themes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def fonts_dir() -> Path:
    """JetBrains fonts: packaged bundle, packaging/fonts (dev), or vendor snapshot."""
    candidates = (
        resource_dir() / "fonts",
        resource_dir() / "packaging" / "fonts",
        resource_dir() / "vendor" / "turing-smart-screen-python" / "res" / "fonts",
    )
    for path in candidates:
        if path.is_dir() and any(path.rglob("*.ttf")):
            return path
    return candidates[0]


def seed_dir() -> Path:
    """Default config + themes shipped with the build."""
    seeded = resource_dir() / "seed"
    if seeded.is_dir():
        return seeded
    return resource_dir()


def ensure_user_data() -> Path:
    """Copy default config/themes into LocalAppData on first run."""
    dest = data_dir()
    seed = seed_dir()

    cfg = config_path()
    seed_cfg = seed / "config.yaml"
    if not cfg.is_file() and seed_cfg.is_file():
        shutil.copy2(seed_cfg, cfg)
    elif not cfg.is_file():
        # Fallback: repo root config during early packaging tests
        repo_cfg = resource_dir() / "config.yaml"
        if repo_cfg.is_file():
            shutil.copy2(repo_cfg, cfg)

    themes_dest = themes_dir()
    seed_themes = seed / "themes"
    if seed_themes.is_dir():
        for child in seed_themes.iterdir():
            if not child.is_dir():
                continue
            target = themes_dest / child.name
            if not target.exists():
                shutil.copytree(child, target)
    else:
        # Dev: copy product themes/omar if missing
        repo_omar = resource_dir() / "themes" / "omar"
        target = themes_dest / "omar"
        if repo_omar.is_dir() and not target.exists():
            shutil.copytree(repo_omar, target)

    return dest


def exe_path() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve()
    return install_dir() / ".venv" / "Scripts" / "pythonw.exe"
