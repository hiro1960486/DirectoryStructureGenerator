"""Data models shared by scanner, exporters and GUI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEVELOPMENT_DIRS = [
    ".git", ".hg", ".svn", ".vs", ".idea", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".nox", "__pycache__", "node_modules", ".venv",
    "venv", "env", "bin", "obj", "dist", "build", "coverage", ".coverage",
    ".next", ".nuxt", ".parcel-cache", ".cache", "target", "packages",
]

PRESETS: dict[str, dict[str, Any]] = {
    "開発用おすすめ": {
        "excluded_dirs": DEVELOPMENT_DIRS,
        "excluded_extensions": [".pyc", ".pyo", ".class", ".o", ".obj", ".tmp", ".log"],
        "patterns": ["*.egg-info", "*.user", "*.suo"],
        "include_hidden": False,
    },
    "Git関連のみ除外": {
        "excluded_dirs": [".git"],
        "excluded_extensions": [],
        "patterns": [".gitignore", ".gitattributes", ".gitmodules"],
        "include_hidden": True,
    },
    "除外なし": {
        "excluded_dirs": [],
        "excluded_extensions": [],
        "patterns": [],
        "include_hidden": True,
    },
}


@dataclass(slots=True)
class FilterSettings:
    excluded_dirs: list[str] = field(default_factory=lambda: DEVELOPMENT_DIRS.copy())
    excluded_extensions: list[str] = field(
        default_factory=lambda: [".pyc", ".pyo", ".class", ".o", ".obj", ".tmp", ".log"]
    )
    included_extensions: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=lambda: ["*.egg-info", "*.user", "*.suo"])
    include_hidden: bool = False
    include_empty_dirs: bool = True
    follow_symlinks: bool = False
    max_depth: int = -1

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "FilterSettings":
        value = value or {}
        valid = {key: value[key] for key in cls.__dataclass_fields__ if key in value}
        return cls(**valid)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScanNode:
    name: str
    path: Path
    relative_path: Path
    is_dir: bool
    depth: int
    size: int = 0
    modified: float = 0.0
    is_symlink: bool = False
    children: list["ScanNode"] = field(default_factory=list)


@dataclass(slots=True)
class ScanStats:
    folders: int = 0
    files: int = 0
    total_size: int = 0
    excluded: int = 0
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def error_count(self) -> int:
        return len(self.errors)


@dataclass(slots=True)
class ScanResult:
    source: Path
    root: ScanNode
    stats: ScanStats
    filters: FilterSettings
