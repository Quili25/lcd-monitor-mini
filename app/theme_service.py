"""Theme YAML load/save and listing."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from app.paths import ensure_user_data, themes_dir


def product_themes_dir() -> Path:
    ensure_user_data()
    return themes_dir()


def theme_dirs() -> list[Path]:
    return [product_themes_dir()]


def list_themes(*, product_only: bool = False) -> list[str]:
    names: set[str] = set()
    _ = product_only  # themes always live under user/product dir
    for base in theme_dirs():
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if child.is_dir() and (child / "theme.yaml").is_file():
                names.add(child.name)
    return sorted(names)


def resolve_theme_dir(name: str) -> Path:
    for base in theme_dirs():
        candidate = base / name
        if (candidate / "theme.yaml").is_file():
            return candidate
    raise FileNotFoundError(f"theme not found: {name}")


def load_theme(name: str) -> dict[str, Any]:
    path = resolve_theme_dir(name) / "theme.yaml"
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data["_dir"] = str(resolve_theme_dir(name))
    data["_name"] = name
    from app.renderer import migrate_static_text_to_widgets

    return migrate_static_text_to_widgets(data)


def save_theme(name: str, data: dict[str, Any], *, product_only: bool = True) -> Path:
    """Save theme under user themes/."""
    clean = {k: v for k, v in data.items() if not str(k).startswith("_")}
    dest = product_themes_dir() / name
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "theme.yaml"
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(clean, f, sort_keys=False, allow_unicode=True)
    return dest


def ensure_background(theme_dir: Path, size: tuple[int, int] = (320, 480)) -> Path:
    bg = theme_dir / "background.png"
    if not bg.is_file():
        from PIL import Image

        Image.new("RGB", size, (16, 20, 28)).save(bg)
    return bg


def clone_theme(src_name: str, dest_name: str) -> Path:
    src = resolve_theme_dir(src_name)
    dest = product_themes_dir() / dest_name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return dest


def orientation_size(theme: dict[str, Any]) -> tuple[int, int]:
    display = theme.get("display") or {}
    orient = str(display.get("DISPLAY_ORIENTATION", "portrait")).lower()
    if orient == "landscape":
        return 480, 320
    return 320, 480


# Back-compat alias used by Theme Studio
PRODUCT_THEMES = None  # type: ignore

def __getattr__(name: str):
    if name == "PRODUCT_THEMES":
        return product_themes_dir()
    raise AttributeError(name)
