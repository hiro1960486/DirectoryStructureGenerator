"""Persistent user configuration stored in the Windows user profile."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import FilterSettings
from .version import APP_VERSION


def config_path() -> Path:
    base = Path(os.getenv("APPDATA") or Path.home() / ".config")
    return base / "DirectoryStructureGenerator" / "config.json"


def default_config() -> dict[str, Any]:
    return {
        "config_version": 2, "app_version": APP_VERSION, "theme": "dark",
        "source": "", "output": "", "source_history": [], "output_history": [],
        "organizer_destinations": [],
        "organizer": {
            "default_destination": "", "naming_template": "{name}",
            "custom_template": "{name}", "keep_subfolders": True,
            "collision": "number",
        },
        "formats": {"txt": True, "html": True, "csv": True, "json": False},
        "filters": FilterSettings().to_dict(), "preset": "開発用おすすめ",
        "window": {"width": 1240, "height": 820},
    }


def load_config() -> dict[str, Any]:
    defaults = default_config()
    path = config_path()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            for key, value in loaded.items():
                if key in {"formats", "window", "organizer"} and isinstance(value, dict):
                    defaults[key].update(value)
                else:
                    defaults[key] = value
    except (OSError, ValueError, TypeError):
        pass
    return defaults


def save_config(config: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def add_history(history: list[str], value: str, limit: int = 10) -> list[str]:
    value = value.strip()
    return ([value] + [item for item in history if item != value])[:limit] if value else history[:limit]
