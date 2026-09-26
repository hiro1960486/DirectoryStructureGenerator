"""Named application setting presets with safe CSV interchange.

Version: 2.9.5
Updated: 2026-09-26
Author: hiro1960
"""

from __future__ import annotations

import csv
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable


MAX_FAVORITES = 5
CSV_FIELDS = (
    "default", "quick", "order", "favorite", "name", "memo", "source", "output",
    "filters_json", "formats_json", "organizer_json",
)


def _csv_safe(value: object) -> str:
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def _csv_restore(value: object) -> str:
    text = str(value or "")
    return text[1:] if len(text) > 1 and text[0] == "'" and text[1] in "=+-@\t\r" else text


def _deduplicate_filter_lists(filters: dict[str, Any]) -> dict[str, Any]:
    cleaned = deepcopy(filters)
    for key in ("excluded_dirs", "excluded_extensions", "included_extensions", "patterns"):
        values = cleaned.get(key, [])
        if not isinstance(values, list):
            continue
        seen: set[str] = set()
        unique: list[str] = []
        for raw in values:
            value = str(raw).strip()
            folded = value.casefold()
            if value and folded not in seen:
                seen.add(folded)
                unique.append(value)
        cleaned[key] = unique
    return cleaned


def builtin_presets() -> list[dict[str, Any]]:
    common = {
        "source": "", "output": "",
        "formats": {"txt": True, "html": True, "csv": True, "json": False},
        "organizer": {
            "default_destination": "", "naming_template": "{name}",
            "custom_template": "{name}", "keep_subfolders": True,
            "collision": "number",
        },
        "builtin": True,
    }
    definitions = [
        ("開発フォルダー", "生成物や仮想環境を除外して、ソース構成を確認します。", {
            "excluded_dirs": [".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist", ".pytest_cache"],
            "excluded_extensions": [".pyc", ".pyo", ".class", ".obj", ".tmp", ".log"],
            "included_extensions": [], "patterns": ["*.egg-info", "*.user", "*.suo"],
            "include_hidden": False, "include_empty_dirs": True, "follow_symlinks": False, "max_depth": -1,
        }),
        ("写真・画像", "一般的な画像ファイルだけを調査・整理します。", {
            "excluded_dirs": [".git", "__pycache__", "$RECYCLE.BIN"], "excluded_extensions": [],
            "included_extensions": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".svg", ".ico"],
            "patterns": [], "include_hidden": False, "include_empty_dirs": False, "follow_symlinks": False, "max_depth": -1,
        }),
        ("動画・音声", "動画と音声ファイルを中心に確認します。", {
            "excluded_dirs": [".git", "$RECYCLE.BIN"], "excluded_extensions": [],
            "included_extensions": [".mp4", ".mov", ".avi", ".mkv", ".webm", ".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg"],
            "patterns": [], "include_hidden": False, "include_empty_dirs": False, "follow_symlinks": False, "max_depth": -1,
        }),
        ("文書・資料", "文書、表計算、PDF、テキストを確認します。", {
            "excluded_dirs": [".git", "$RECYCLE.BIN"], "excluded_extensions": [".tmp", ".log"],
            "included_extensions": [".pdf", ".txt", ".md", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv"],
            "patterns": ["~$*"], "include_hidden": False, "include_empty_dirs": False, "follow_symlinks": False, "max_depth": -1,
        }),
        ("全ファイル確認", "除外を最小限にして、隠し項目も含めて確認します。", {
            "excluded_dirs": [], "excluded_extensions": [], "included_extensions": [], "patterns": [],
            "include_hidden": True, "include_empty_dirs": True, "follow_symlinks": False, "max_depth": -1,
        }),
        ("軽量・高速走査", "隠し項目と空フォルダーを除き、5階層まで高速に確認します。", {
            "excluded_dirs": [".git", ".venv", "node_modules", "__pycache__", "build", "dist", "$RECYCLE.BIN"],
            "excluded_extensions": [".tmp", ".log", ".cache"], "included_extensions": [], "patterns": [],
            "include_hidden": False, "include_empty_dirs": False, "follow_symlinks": False, "max_depth": 5,
        }),
    ]
    result = []
    for index, (name, memo, filters) in enumerate(definitions):
        item = deepcopy(common)
        item.update({
            "name": name, "memo": memo, "favorite": index < MAX_FAVORITES,
            "quick": index < MAX_FAVORITES, "default": index == 0,
            "order": index + 1, "filters": filters,
        })
        result.append(item)
    return result


def normalize_preset(value: dict[str, Any]) -> dict[str, Any]:
    name = str(value.get("name", "")).strip()
    if not name:
        raise ValueError("プリセット名が空です。")
    filters = value.get("filters", {})
    formats = value.get("formats", {})
    organizer = value.get("organizer", {})
    if not isinstance(filters, dict) or not isinstance(formats, dict) or not isinstance(organizer, dict):
        raise ValueError(f"「{name}」の設定形式が正しくありません。")
    # Include every organizer option so settings survive config normalization.
    safe_organizer = {
        "default_destination": "", "naming_template": "{name}",
        "custom_template": "{name}", "keep_subfolders": True,
        "collision": "number", "result_log_directory": "",
        "result_format": "csv", "result_history_mode": "append",
    }
    safe_organizer.update({
        key: organizer[key] for key in safe_organizer if key in organizer
    })
    return {
        "name": name,
        "memo": str(value.get("memo", "")).strip()[:500],
        # favorite is retained as a compatibility alias for Ver.2.7 CSV/config files.
        "favorite": bool(value.get("quick", value.get("favorite", False))),
        "quick": bool(value.get("quick", value.get("favorite", False))),
        "default": bool(value.get("default", False)),
        "order": max(1, int(value.get("order", 999) or 999)),
        "builtin": bool(value.get("builtin", False)),
        "source": str(value.get("source", "")).strip(),
        "output": str(value.get("output", "")).strip(),
        "filters": _deduplicate_filter_lists(filters),
        "formats": {str(k): bool(v) for k, v in formats.items()},
        "organizer": safe_organizer,
    }


def normalize_presets(
    values: Iterable[dict[str, Any]], max_favorites: int = MAX_FAVORITES,
) -> list[dict[str, Any]]:
    max_favorites = max(1, int(max_favorites))
    result: list[dict[str, Any]] = []
    names: set[str] = set()
    for raw in values:
        item = normalize_preset(raw)
        folded = item["name"].casefold()
        if folded in names:
            continue
        names.add(folded)
        result.append(item)
    result.sort(key=lambda item: (int(item.get("order", 999)), item["name"].casefold()))
    default_index = next((i for i, item in enumerate(result) if item["default"]), 0)
    for i, item in enumerate(result):
        item["default"] = bool(result) and i == default_index
    if result:
        result[default_index]["quick"] = True
    allowed_quick = {default_index}
    for i, item in enumerate(result):
        if i != default_index and item["quick"] and len(allowed_quick) < max_favorites:
            allowed_quick.add(i)
    for i, item in enumerate(result):
        item["quick"] = i in allowed_quick
        item["favorite"] = item["quick"]
    return result


def export_presets_csv(
    path: Path, presets: Iterable[dict[str, Any]], max_favorites: int = MAX_FAVORITES,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for raw in presets:
            item = normalize_preset(raw)
            writer.writerow({
                "default": "true" if item["default"] else "false",
                "quick": "true" if item["quick"] else "false",
                "order": item["order"],
                "favorite": "true" if item["favorite"] else "false",
                "name": _csv_safe(item["name"]), "memo": _csv_safe(item["memo"]),
                "source": _csv_safe(item["source"]), "output": _csv_safe(item["output"]),
                "filters_json": json.dumps(item["filters"], ensure_ascii=False, separators=(",", ":")),
                "formats_json": json.dumps(item["formats"], ensure_ascii=False, separators=(",", ":")),
                "organizer_json": json.dumps(item["organizer"], ensure_ascii=False, separators=(",", ":")),
            })


def import_presets_csv(path: Path, max_favorites: int = MAX_FAVORITES) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = ("favorite", "name", "memo", "source", "output", "filters_json", "formats_json", "organizer_json")
        missing = [field for field in required if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError("CSVに必要な列がありません: " + ", ".join(missing))
        for line_number, row in enumerate(reader, start=2):
            try:
                favorite = str(row.get("favorite", "")).strip().lower() in {"1", "true", "yes", "on", "✓"}
                quick = str(row.get("quick", row.get("favorite", ""))).strip().lower() in {"1", "true", "yes", "on", "✓"}
                default = str(row.get("default", "")).strip().lower() in {"1", "true", "yes", "on", "✓"}
                item = normalize_preset({
                    "name": _csv_restore(row.get("name", "")),
                    "memo": _csv_restore(row.get("memo", "")),
                    "favorite": favorite, "quick": quick, "default": default,
                    "order": row.get("order", 999), "builtin": False,
                    "source": _csv_restore(row.get("source", "")),
                    "output": _csv_restore(row.get("output", "")),
                    "filters": json.loads(row.get("filters_json", "{}") or "{}"),
                    "formats": json.loads(row.get("formats_json", "{}") or "{}"),
                    "organizer": json.loads(row.get("organizer_json", "{}") or "{}"),
                })
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError(f"CSV {line_number}行目: {exc}") from exc
            result.append(item)
    return normalize_presets(result, max_favorites)


def merge_presets(
    existing: Iterable[dict[str, Any]], incoming: Iterable[dict[str, Any]],
    max_favorites: int = MAX_FAVORITES,
) -> list[dict[str, Any]]:
    merged = normalize_presets(existing, max_favorites)
    positions = {item["name"].casefold(): index for index, item in enumerate(merged)}
    for raw in incoming:
        item = normalize_preset(raw)
        key = item["name"].casefold()
        if key in positions:
            item["builtin"] = merged[positions[key]].get("builtin", False)
            merged[positions[key]] = item
        else:
            positions[key] = len(merged)
            merged.append(item)
    return normalize_presets(merged, max_favorites)


def set_preset_organizer_settings(
    presets: Iterable[dict[str, Any]], name: str, organizer: dict[str, Any],
) -> bool:
    """Store organizer defaults on the explicitly selected preset."""
    for item in presets:
        if str(item.get("name", "")) == name:
            item["organizer"] = deepcopy(organizer)
            return True
    return False



def startup_preset_name(presets: Iterable[dict[str, Any]], active_name: str = "") -> str:
    """Restore the last selected preset, falling back to the marked default."""
    values = list(presets)
    if active_name and any(item.get("name") == active_name for item in values):
        return active_name
    default = next((item for item in values if item.get("default")), None)
    return str(default.get("name", "")) if default else ""
