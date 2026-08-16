"""Product config load/save (user data config.yaml)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.paths import config_path, ensure_user_data


def load_config() -> dict[str, Any]:
    ensure_user_data()
    path = config_path()
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(data: dict[str, Any]) -> None:
    ensure_user_data()
    path = config_path()
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def get_nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur
