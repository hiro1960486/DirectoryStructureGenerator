"""File organization with safe copy and Excel-friendly result reporting.

Version: 2.9.0
Updated: 2026-09-24
Author: hiro1960
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath
from urllib.parse import quote

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from .file_inspector import FileDetail


WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
RESULT_LOG_NAME = "_DirectoryStructureGenerator_copy_log.csv"
RESULT_XLSX_NAME = "_DirectoryStructureGenerator_copy_log.xlsx"
RESULT_COLUMNS = [
    "実行ID", "実行日時", "処理結果", "エラー分類", "エラー詳細",
    "元ファイル名", "新ファイル名", "元フォルダー", "保存先フォルダー",
    "元フルパス", "保存後フルパス", "元サイズ", "保存後サイズ",
    "元ファイルを削除", "保存先を開く", "保存後ファイルを開く",
    "保存先URI", "保存後ファイルURI",
]


class CopyCancelled(RuntimeError):
    """Raised when an organization copy is cancelled."""


@dataclass(slots=True)
class CopyPlan:
    source: Path
    destination: Path
    relative_path: str
    status: str = "コピー予定"
    error: str = ""
    error_code: str = ""
    run_id: str = ""
    executed_at: str = ""
    source_size: int | None = None
    destination_size: int | None = None
    delete_source_requested: bool = False


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


def extension_was_changed(plan: CopyPlan) -> bool:
    """Return True when a copy plan changes only the filename extension label."""
    return plan.source.suffix.casefold() != plan.destination.suffix.casefold()


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


def _looks_windows_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or value.startswith(("\\\\", "//"))


def windows_file_uri(path: str | os.PathLike[str]) -> str:
    """Return a percent-encoded file URI for local, drive-letter, or UNC paths."""
    raw = os.fspath(path).strip()
    if _looks_windows_path(raw):
        windows_path = PureWindowsPath(raw)
        if windows_path.drive.startswith("\\\\"):
            server_share = windows_path.drive.lstrip("\\").replace("\\", "/")
            tail = "/".join(quote(part, safe="") for part in windows_path.parts[1:])
            return f"file://{server_share}" + (f"/{tail}" if tail else "")
        drive = windows_path.drive.rstrip(":").upper()
        tail = "/".join(quote(part, safe="") for part in windows_path.parts[1:])
        return f"file:///{drive}:" + (f"/{tail}" if tail else "/")
    return Path(raw).expanduser().resolve().as_uri()


def _excel_formula_escape(value: str) -> str:
    return value.replace('"', '""')


def excel_hyperlink(path: str | os.PathLike[str], label: str) -> str:
    """Create a hyperlink formula; only this application-generated value is executable."""
    raw = os.fspath(path)
    target = str(PureWindowsPath(raw)) if _looks_windows_path(raw) else windows_file_uri(raw)
    return f'=HYPERLINK("{_excel_formula_escape(target)}","{_excel_formula_escape(label)}")'


def classify_copy_error(exc: BaseException) -> str:
    if isinstance(exc, FileNotFoundError):
        return "FILE_NOT_FOUND"
    if isinstance(exc, PermissionError):
        return "ACCESS_DENIED"
    if isinstance(exc, IsADirectoryError):
        return "IS_DIRECTORY"
    if isinstance(exc, OSError):
        if getattr(exc, "winerror", None) == 112 or getattr(exc, "errno", None) == 28:
            return "DISK_FULL"
        if getattr(exc, "winerror", None) in {32, 33}:
            return "FILE_IN_USE"
        return "COPY_FAILED"
    return "UNKNOWN_ERROR"


def _safe_stat_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _csv_text(value: object) -> object:
    """Prevent formulas in cells derived from paths, names, and error text."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _prepare_log_file(log_path: Path) -> bool:
    """Return whether a header is needed, preserving an incompatible legacy log."""
    if not log_path.exists() or log_path.stat().st_size == 0:
        return True
    try:
        with log_path.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), [])
    except (OSError, UnicodeError, csv.Error):
        header = []
    if header == RESULT_COLUMNS:
        return False
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    legacy_path = log_path.with_name(f"{log_path.stem}_legacy_{stamp}{log_path.suffix}")
    counter = 1
    while legacy_path.exists():
        legacy_path = log_path.with_name(
            f"{log_path.stem}_legacy_{stamp}_{counter}{log_path.suffix}"
        )
        counter += 1
    log_path.replace(legacy_path)
    return True


def copy_log_path(destination_root: Path, output_format: str = "csv") -> Path:
    return destination_root / (RESULT_XLSX_NAME if output_format == "xlsx" else RESULT_LOG_NAME)


def _archive_existing_log(path: Path) -> Path | None:
    """Move a previous active log to a timestamped archive before initialization."""
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = path.with_name(f"{path.stem}_history_{stamp}{path.suffix}")
    counter = 1
    while archive.exists():
        archive = path.with_name(f"{path.stem}_history_{stamp}_{counter}{path.suffix}")
        counter += 1
    path.replace(archive)
    return archive


def _copy_log_row(plan: CopyPlan, fallback_time: str) -> list[object]:
    return [
        plan.run_id, plan.executed_at or fallback_time, plan.status,
        plan.error_code, plan.error, plan.source.name, plan.destination.name,
        str(plan.source.parent), str(plan.destination.parent),
        str(plan.source), str(plan.destination), plan.source_size,
        plan.destination_size,
        "はい" if plan.delete_source_requested else "いいえ",
        excel_hyperlink(plan.destination.parent, "保存先を開く"),
        excel_hyperlink(plan.destination, "保存後ファイルを開く"),
        windows_file_uri(plan.destination.parent), windows_file_uri(plan.destination),
    ]


def append_copy_log(
    destination_root: Path, plans: list[CopyPlan], output_format: str = "csv",
    history_mode: str = "append",
) -> Path:
    """Append an Excel-compatible UTF-8 BOM/CRLF result log."""
    if output_format == "xlsx":
        return append_copy_log_xlsx(destination_root, plans, history_mode)
    log_path = destination_root / RESULT_LOG_NAME
    if history_mode == "reset":
        _archive_existing_log(log_path)
    new_file = _prepare_log_file(log_path)
    # Write the BOM only on first creation. Opening an existing file in append
    # mode with utf-8-sig would insert another BOM at every later run.
    encoding = "utf-8-sig" if new_file else "utf-8"
    with log_path.open("a", encoding=encoding, newline="") as handle:
        writer = csv.writer(handle, dialect="excel", lineterminator="\r\n")
        if new_file:
            writer.writerow(RESULT_COLUMNS)
        fallback_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for plan in plans:
            row = _copy_log_row(plan, fallback_time)
            writer.writerow([
                value if index in {14, 15} else _csv_text(value)
                for index, value in enumerate(row)
            ])
    return log_path


def append_copy_log_xlsx(
    destination_root: Path, plans: list[CopyPlan], history_mode: str = "append",
) -> Path:
    """Append copy results to a native Excel workbook with working path links."""
    destination_root.mkdir(parents=True, exist_ok=True)
    path = copy_log_path(destination_root, "xlsx")
    if history_mode == "reset":
        _archive_existing_log(path)
    if path.exists():
        workbook = load_workbook(path)
        worksheet = workbook.active
    else:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "コピー結果"
        worksheet.append(RESULT_COLUMNS)
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = f"A1:R1"
    fallback_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for plan in plans:
        row = _copy_log_row(plan, fallback_time)
        row[14] = "保存先を開く"
        row[15] = "保存後ファイルを開く"
        worksheet.append([_csv_text(value) for value in row])
        excel_row = worksheet.max_row
        for column, target in ((15, plan.destination.parent), (16, plan.destination)):
            cell = worksheet.cell(excel_row, column)
            cell.hyperlink = str(PureWindowsPath(target)) if _looks_windows_path(str(target)) else str(target.resolve())
            cell.font = Font(color="0563C1", underline="single")
    widths = [34, 20, 18, 18, 40, 28, 28, 36, 36, 60, 60, 16, 16, 18, 22, 28, 70, 70]
    for index, width in enumerate(widths, start=1):
        worksheet.column_dimensions[chr(64 + index)].width = width
    worksheet.auto_filter.ref = worksheet.dimensions
    workbook.save(path)
    return path


def create_destination_shortcut(destination_root: Path) -> Path:
    """Create a Unicode-safe Windows shortcut beside the result CSV."""
    destination_root.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        shortcut = destination_root / "保存先を開く.lnk"
        script = (
            "$shell = New-Object -ComObject WScript.Shell; "
            "$link = $shell.CreateShortcut($env:DSG_SHORTCUT_PATH); "
            "$link.TargetPath = $env:DSG_SHORTCUT_TARGET; "
            "$link.WorkingDirectory = $env:DSG_SHORTCUT_TARGET; "
            "$link.Save()"
        )
        environment = os.environ.copy()
        environment["DSG_SHORTCUT_PATH"] = str(shortcut)
        environment["DSG_SHORTCUT_TARGET"] = str(destination_root)
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
            check=True, capture_output=True, text=True, env=environment,
        )
        old_url = destination_root / "保存先を開く.url"
        if old_url.exists():
            old_url.unlink()
    else:
        # Keep the portable test/development artifact available on non-Windows hosts.
        shortcut = destination_root / "保存先を開く.url"
        shortcut.write_text(
            "[InternetShortcut]\r\n" f"URL={windows_file_uri(destination_root)}\r\n",
            encoding="utf-8-sig", newline="",
        )
    return shortcut


def execute_copy_plans(
    plans: list[CopyPlan],
    destination_root: Path,
    delete_sources: bool = False,
    cancel_requested: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    output_format: str = "csv",
    history_mode: str = "append",
    result_directory: Path | None = None,
) -> list[CopyPlan]:
    cancel_requested = cancel_requested or (lambda: False)
    progress = progress or (lambda _current, _total, _path: None)
    destination_root = destination_root.expanduser().resolve()
    log_root = result_directory.expanduser().resolve() if result_directory else destination_root
    run_id = uuid.uuid4().hex
    executed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(plans)
    for index, plan in enumerate(plans, start=1):
        plan.run_id = run_id
        plan.executed_at = executed_at
        plan.delete_source_requested = delete_sources
        plan.source_size = _safe_stat_size(plan.source)
        if cancel_requested():
            for remaining in plans[index - 1:]:
                if remaining.status == "コピー予定":
                    remaining.status = "中止により未実行"
                    remaining.error_code = "CANCELLED"
                    remaining.run_id = run_id
                    remaining.executed_at = executed_at
                    remaining.delete_source_requested = delete_sources
                    remaining.source_size = _safe_stat_size(remaining.source)
            destination_root.mkdir(parents=True, exist_ok=True)
            log_root.mkdir(parents=True, exist_ok=True)
            append_copy_log(log_root, plans, output_format, history_mode)
            create_destination_shortcut(destination_root)
            raise CopyCancelled("整理コピーを中止しました。")
        progress(index, total, str(plan.source))
        if plan.status != "コピー予定":
            plan.destination_size = _safe_stat_size(plan.destination)
            continue
        copied = False
        try:
            plan.destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plan.source, plan.destination)
            copied = True
            plan.destination_size = _safe_stat_size(plan.destination)
            if delete_sources:
                if plan.source_size != plan.destination_size:
                    raise OSError(
                        "コピー元とコピー先のサイズが一致しないため、元ファイルを削除しませんでした。"
                    )
                try:
                    plan.source.unlink()
                    plan.status = "コピー完了・元ファイル削除"
                except OSError as exc:
                    plan.status = "コピー完了・元ファイル削除失敗"
                    plan.error_code = classify_copy_error(exc)
                    plan.error = str(exc)
            else:
                plan.status = "コピー完了"
        except OSError as exc:
            if delete_sources and copied:
                plan.status = "コピー完了・安全確認失敗"
            else:
                plan.status = "コピー失敗"
            plan.error_code = classify_copy_error(exc)
            plan.error = str(exc)
            plan.destination_size = _safe_stat_size(plan.destination)
    destination_root.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)
    append_copy_log(log_root, plans, output_format, history_mode)
    create_destination_shortcut(destination_root)
    return plans
