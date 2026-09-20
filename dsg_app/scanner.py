"""Fast, cancellable directory scanner with configurable filters."""

from __future__ import annotations

import fnmatch
import os
import time
from collections.abc import Callable
from pathlib import Path

from .models import FilterSettings, ScanNode, ScanResult, ScanStats


class ScanCancelled(RuntimeError):
    """Raised when the user cancels a scan."""


class DirectoryScanner:
    def __init__(
        self,
        settings: FilterSettings,
        cancel_requested: Callable[[], bool] | None = None,
        progress: Callable[[str, ScanStats], None] | None = None,
        excluded_absolute_paths: list[Path] | None = None,
    ) -> None:
        self.settings = settings
        self.cancel_requested = cancel_requested or (lambda: False)
        self.progress = progress or (lambda _path, _stats: None)
        self.stats = ScanStats()
        self._visited = 0
        self._excluded_absolute = {
            os.path.normcase(os.path.abspath(path)) for path in (excluded_absolute_paths or [])
        }
        self._excluded_dirs = {item.casefold() for item in settings.excluded_dirs if item.strip()}
        self._excluded_exts = {self._normalize_ext(item) for item in settings.excluded_extensions if item.strip()}
        self._included_exts = {self._normalize_ext(item) for item in settings.included_extensions if item.strip()}
        self._patterns = [item.strip() for item in settings.patterns if item.strip()]
        self._visited_directories: set[str] = set()

    @staticmethod
    def _directory_identity(path: Path) -> str:
        """Return a stable identity for cycle detection when following links.

        Some Windows drives return zero or repeated inode numbers.  Using
        ``(st_dev, st_ino)`` there can make unrelated folders look identical.
        The resolved path is stable for the link-cycle check and avoids that
        false deduplication.
        """
        return os.path.normcase(os.path.abspath(os.path.realpath(path)))

    @staticmethod
    def _normalize_ext(value: str) -> str:
        value = value.strip().casefold()
        return value if value.startswith(".") else f".{value}"

    @staticmethod
    def _is_hidden(path: Path, name: str) -> bool:
        if name.startswith("."):
            return True
        try:
            return bool(path.stat().st_file_attributes & 2)  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return False

    def _matches_pattern(self, relative: Path, name: str) -> bool:
        posix = relative.as_posix()
        return any(fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(posix, pattern) for pattern in self._patterns)

    def _excluded_common(self, path: Path, relative: Path, name: str) -> bool:
        if os.path.normcase(os.path.abspath(path)) in self._excluded_absolute:
            return True
        if not self.settings.include_hidden and self._is_hidden(path, name):
            return True
        return self._matches_pattern(relative, name)

    def _skip_directory(self, path: Path, relative: Path, name: str) -> bool:
        return name.casefold() in self._excluded_dirs or self._excluded_common(path, relative, name)

    def _skip_file(self, path: Path, relative: Path, name: str) -> bool:
        if self._excluded_common(path, relative, name):
            return True
        suffix = path.suffix.casefold()
        if suffix in self._excluded_exts:
            return True
        return bool(self._included_exts and suffix not in self._included_exts)

    @staticmethod
    def _sort_key(entry: os.DirEntry[str]) -> tuple[int, str]:
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            is_dir = False
        return (0 if is_dir else 1, entry.name.casefold())

    def scan(self, source: Path) -> ScanResult:
        source = source.expanduser().resolve()
        if not source.is_dir():
            raise NotADirectoryError(f"対象フォルダーが見つかりません: {source}")
        started = time.perf_counter()
        try:
            stat = source.stat()
            root = ScanNode(source.name or str(source), source, Path("."), True, 0, modified=stat.st_mtime)
            if self.settings.follow_symlinks:
                self._visited_directories.add(self._directory_identity(source))
            self.stats.folders = 1
            root.children = self._walk(source, Path("."), 0)
        finally:
            self.stats.elapsed_seconds = time.perf_counter() - started
        return ScanResult(source, root, self.stats, self.settings)

    def _walk(self, folder: Path, relative_folder: Path, depth: int) -> list[ScanNode]:
        if self.cancel_requested():
            raise ScanCancelled("走査を中止しました。")
        if self.settings.max_depth >= 0 and depth >= self.settings.max_depth:
            return []
        try:
            entries = sorted(os.scandir(folder), key=self._sort_key)
        except OSError as exc:
            self.stats.errors.append(f"{folder}: {exc}")
            return []

        nodes: list[ScanNode] = []
        for entry in entries:
            if self.cancel_requested():
                raise ScanCancelled("走査を中止しました。")
            path = Path(entry.path)
            relative = relative_folder / entry.name if relative_folder != Path(".") else Path(entry.name)
            self._visited += 1
            if self._visited % 200 == 0:
                self.progress(str(relative), self.stats)
            try:
                is_symlink = entry.is_symlink()
                is_junction = bool(getattr(path, "is_junction", lambda: False)())
                is_link = is_symlink or is_junction
                is_dir = entry.is_dir(follow_symlinks=self.settings.follow_symlinks)
                if is_link and not self.settings.follow_symlinks:
                    self.stats.excluded += 1
                    continue
                if is_dir:
                    if self._skip_directory(path, relative, entry.name):
                        self.stats.excluded += 1
                        continue
                    stat = entry.stat(follow_symlinks=self.settings.follow_symlinks)
                    if self.settings.follow_symlinks:
                        identity = self._directory_identity(path)
                        if identity in self._visited_directories:
                            self.stats.excluded += 1
                            continue
                        self._visited_directories.add(identity)
                    node = ScanNode(
                        entry.name, path, relative, True, depth + 1,
                        modified=stat.st_mtime, is_symlink=is_link,
                    )
                    self.stats.folders += 1
                    node.children = self._walk(path, relative, depth + 1)
                    if self.settings.include_empty_dirs or node.children:
                        nodes.append(node)
                    else:
                        self.stats.folders -= 1
                        self.stats.excluded += 1
                else:
                    if self._skip_file(path, relative, entry.name):
                        self.stats.excluded += 1
                        continue
                    stat = entry.stat(follow_symlinks=self.settings.follow_symlinks)
                    node = ScanNode(
                        entry.name, path, relative, False, depth + 1,
                        size=stat.st_size, modified=stat.st_mtime, is_symlink=is_link,
                    )
                    nodes.append(node)
                    self.stats.files += 1
                    self.stats.total_size += stat.st_size
            except OSError as exc:
                self.stats.errors.append(f"{path}: {exc}")
        return nodes
