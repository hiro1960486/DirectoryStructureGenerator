"""Non-destructive file organization by copying to a chosen destination.

Version: 2.4.0
Updated: 2026-09-22
Author: hiro1960
"""

from __future__ import annotations

import csv
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .file_inspector import FileDetail


WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class CopyCancelled(RuntimeError):
    """Raised when an organization copy is cancelled."""


@dataclass(slots=True)
class CopyPlan:
    source: Path
    destination: Path
    relative_path: str
    status: str = "コピー予定"
    error: str = ""


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(". ")
    if not name:
        name = "unnamed"
    stem = Path(name).stem.upper()
    if stem in WINDOWS_RESERVED:
        name = "_" + name
    return name[:240]


def rendered_name(detail: FileDetail, template: str, index: int) -> str:
    original = Path(detail.name)
    values = {
        "name": detail.name,
        "stem": original.stem,
        "ext": original.suffix,
        "index": index,
        "date": datetime.now().strftime("%Y%m%d"),
        "created": detail.created[:10].replace("-", "") if detail.created else "",
        "type": "images" if detail.is_image else "videos" if detail.is_video else "files",
    }
    try:
        name = template.format(**values)
    except (KeyError, ValueError, IndexError) as exc:
        raise ValueError(f"命名ルールを確認してください: {exc}") from exc
    name = sanitize_filename(name)
    if not Path(name).suffix and original.suffix:
        name += original.suffix
    return name


def _numbered(path: Path, reserved: set[str]) -> Path:
    candidate = path
    number = 1
    while candidate.exists() or os.path.normcase(str(candidate)) in reserved:
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        number += 1
    return candidate


def build_copy_plans(
    details: list[FileDetail],
    destination_root: Path,
    template: str,
    keep_subfolders: bool,
    collision: str,
    name_overrides: dict[str, str] | None = None,
) -> list[CopyPlan]:
    root = destination_root.expanduser().resolve()
    plans: list[CopyPlan] = []
    reserved: set[str] = set()
    name_overrides = name_overrides or {}
    for index, detail in enumerate(details, start=1):
        source = Path(detail.full_path).resolve()
        relative_parent = Path(detail.relative_path).parent if keep_subfolders else Path()
        override = name_overrides.get(detail.full_path, "").strip()
        filename = sanitize_filename(override) if override else rendered_name(detail, template, index)
        if override and not Path(filename).suffix and Path(detail.name).suffix:
            filename += Path(detail.name).suffix
        destination = root / relative_parent / filename
        normalized = os.path.normcase(str(destination))
        if source == destination:
            plans.append(CopyPlan(source, destination, detail.relative_path, "元ファイルと同じためスキップ"))
            continue
        if destination.exists() or normalized in reserved:
            if collision == "skip":
                plans.append(CopyPlan(source, destination, detail.relative_path, "既存のためスキップ"))
                continue
            destination = _numbered(destination, reserved)
            normalized = os.path.normcase(str(destination))
        reserved.add(normalized)
        plans.append(CopyPlan(source, destination, detail.relative_path))
    return plans


def append_copy_log(destination_root: Path, plans: list[CopyPlan]) -> Path:
    log_path = destination_root / "_DirectoryStructureGenerator_copy_log.csv"
    new_file = not log_path.exists()
    with log_path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(["日時", "元ファイル", "コピー先", "結果", "エラー"])
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for plan in plans:
            writer.writerow([timestamp, str(plan.source), str(plan.destination), plan.status, plan.error])
    return log_path


def execute_copy_plans(
    plans: list[CopyPlan],
    destination_root: Path,
    cancel_requested: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[CopyPlan]:
    cancel_requested = cancel_requested or (lambda: False)
    progress = progress or (lambda _current, _total, _path: None)
    total = len(plans)
    for index, plan in enumerate(plans, start=1):
        if cancel_requested():
            for remaining in plans[index - 1:]:
                if remaining.status == "コピー予定":
                    remaining.status = "中止により未実行"
            destination_root.mkdir(parents=True, exist_ok=True)
            append_copy_log(destination_root, plans)
            raise CopyCancelled("整理コピーを中止しました。")
        progress(index, total, str(plan.source))
        if plan.status != "コピー予定":
            continue
        try:
            plan.destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plan.source, plan.destination)
            plan.status = "コピー完了"
        except OSError as exc:
            plan.status = "コピー失敗"
            plan.error = str(exc)
    destination_root.mkdir(parents=True, exist_ok=True)
    append_copy_log(destination_root, plans)
    return plans
