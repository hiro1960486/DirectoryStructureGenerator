"""Read-only metadata inspection for general files and images.

Version: 2.2.0
Updated: 2026-09-21
Author: hiro1960
"""

from __future__ import annotations

import hashlib
import csv
import json
import math
import re
import stat
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image, UnidentifiedImageError

from .models import ScanNode, ScanResult


RASTER_EXTENSIONS = {
    ".bmp", ".gif", ".jfif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp",
}
IMAGE_EXTENSIONS = RASTER_EXTENSIONS | {".svg"}
TEXT_EXTENSIONS = {
    ".bat", ".c", ".cc", ".cfg", ".conf", ".cpp", ".cs", ".css", ".csv",
    ".h", ".hpp", ".htm", ".html", ".ini", ".java", ".js", ".json", ".jsx",
    ".log", ".md", ".ps1", ".py", ".pyw", ".rst", ".sh", ".sql", ".svg",
    ".toml", ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml",
}
MAX_LINE_COUNT_SIZE = 20 * 1024 * 1024


class InspectionCancelled(RuntimeError):
    """Raised when the user cancels file inspection."""


@dataclass(slots=True)
class FileDetail:
    name: str
    relative_path: str
    full_path: str
    category: str
    extension: str
    file_size: int
    modified: str
    created: str
    permissions: str
    readonly: bool
    line_count: int | None = None
    sha256: str = ""
    image_format: str = ""
    width: int | None = None
    height: int | None = None
    aspect_ratio: str = ""
    color_mode: str = ""
    exif_datetime: str = ""
    camera: str = ""
    gps: str = ""
    error: str = ""

    @property
    def resolution(self) -> str:
        if self.width is None or self.height is None:
            return ""
        return f"{self.width} × {self.height}"

    @property
    def is_image(self) -> bool:
        return self.category == "image"


def _files(node: ScanNode) -> Iterable[ScanNode]:
    if not node.is_dir:
        yield node
    for child in node.children:
        yield from _files(child)


def _ratio(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return ""
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _count_lines(path: Path) -> int:
    count = 0
    last = b""
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            count += chunk.count(b"\n")
            last = chunk[-1:]
    return count + (1 if last and last != b"\n" else 0)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
    return int(round(float(match.group()))) if match else None


def _svg_size(path: Path) -> tuple[int | None, int | None]:
    root = ET.parse(path).getroot()
    width, height = _number(root.get("width")), _number(root.get("height"))
    if width and height:
        return width, height
    view_box = root.get("viewBox", "").replace(",", " ").split()
    if len(view_box) == 4:
        try:
            return int(round(float(view_box[2]))), int(round(float(view_box[3])))
        except ValueError:
            pass
    return width, height


def _rational(value) -> float:  # type: ignore[no-untyped-def]
    try:
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _coordinate(values, reference: str) -> float | None:  # type: ignore[no-untyped-def]
    try:
        degrees, minutes, seconds = (_rational(item) for item in values)
    except (TypeError, ValueError):
        return None
    coordinate = degrees + minutes / 60 + seconds / 3600
    return -coordinate if reference.upper() in {"S", "W"} else coordinate


def _gps_text(exif) -> str:  # type: ignore[no-untyped-def]
    try:
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    except (AttributeError, KeyError, TypeError, ValueError):
        return ""
    latitude = _coordinate(gps.get(2), str(gps.get(1, ""))) if gps.get(2) else None
    longitude = _coordinate(gps.get(4), str(gps.get(3, ""))) if gps.get(4) else None
    if latitude is None or longitude is None:
        return ""
    return f"{latitude:.6f}, {longitude:.6f}"


def _image_metadata(
    path: Path,
    include_exif: bool,
    include_gps: bool,
) -> dict[str, object]:
    if path.suffix.casefold() == ".svg":
        width, height = _svg_size(path)
        return {
            "image_format": "SVG", "width": width, "height": height,
            "aspect_ratio": _ratio(width, height) if width and height else "",
            "color_mode": "Vector",
        }
    with Image.open(path) as image:
        width, height = image.size
        values: dict[str, object] = {
            "image_format": image.format or path.suffix.lstrip(".").upper(),
            "width": width,
            "height": height,
            "aspect_ratio": _ratio(width, height),
            "color_mode": image.mode,
        }
        if include_exif:
            exif = image.getexif()
            values["exif_datetime"] = str(
                exif.get(36867) or exif.get(306) or ""
            ).strip()
            make = str(exif.get(271) or "").strip()
            model = str(exif.get(272) or "").strip()
            values["camera"] = " ".join(part for part in (make, model) if part)
            values["gps"] = _gps_text(exif) if include_gps else ""
        return values


def inspect_file(
    node: ScanNode,
    include_lines: bool,
    include_exif: bool,
    include_gps: bool,
    include_sha256: bool,
) -> FileDetail:
    path = node.path
    file_stat = path.stat()
    suffix = path.suffix.casefold()
    is_image = suffix in IMAGE_EXTENSIONS
    detail = FileDetail(
        name=path.name,
        relative_path=node.relative_path.as_posix(),
        full_path=str(path),
        category="image" if is_image else "general",
        extension=suffix,
        file_size=file_stat.st_size,
        modified=datetime.fromtimestamp(file_stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        created=datetime.fromtimestamp(file_stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
        permissions=stat.filemode(file_stat.st_mode),
        readonly=not bool(file_stat.st_mode & stat.S_IWUSR),
    )
    errors: list[str] = []
    if include_lines and suffix in TEXT_EXTENSIONS and file_stat.st_size <= MAX_LINE_COUNT_SIZE:
        try:
            detail.line_count = _count_lines(path)
        except OSError as exc:
            errors.append(f"行数: {exc}")
    if include_sha256:
        try:
            detail.sha256 = _sha256(path)
        except OSError as exc:
            errors.append(f"SHA256: {exc}")
    if is_image:
        try:
            values = _image_metadata(path, include_exif, include_gps)
            for key, value in values.items():
                setattr(detail, key, value)
        except (ET.ParseError, UnidentifiedImageError, OSError, ValueError) as exc:
            errors.append(f"画像: {exc}")
    detail.error = "; ".join(errors)
    return detail


def inspect_scan_result(
    result: ScanResult,
    include_lines: bool = True,
    include_exif: bool = False,
    include_gps: bool = False,
    include_sha256: bool = False,
    cancel_requested: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[FileDetail]:
    cancel_requested = cancel_requested or (lambda: False)
    progress = progress or (lambda _current, _total, _path: None)
    nodes = list(_files(result.root))
    details: list[FileDetail] = []
    total = len(nodes)
    for index, node in enumerate(nodes, start=1):
        if cancel_requested():
            raise InspectionCancelled("ファイル解析を中止しました。")
        progress(index, total, node.relative_path.as_posix())
        try:
            details.append(
                inspect_file(node, include_lines, include_exif, include_gps, include_sha256)
            )
        except OSError as exc:
            details.append(
                FileDetail(
                    name=node.name,
                    relative_path=node.relative_path.as_posix(),
                    full_path=str(node.path),
                    category="image" if node.path.suffix.casefold() in IMAGE_EXTENSIONS else "general",
                    extension=node.path.suffix.casefold(),
                    file_size=node.size,
                    modified="",
                    created="",
                    permissions="",
                    readonly=False,
                    error=str(exc),
                )
            )
    return details


def _excel_safe(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_details_csv(details: list[FileDetail], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = list(FileDetail.__dataclass_fields__) + ["resolution"]
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for detail in details:
            row = asdict(detail)
            row["resolution"] = detail.resolution
            writer.writerow({key: _excel_safe(row[key]) for key in fields})


def export_details_json(details: list[FileDetail], source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for detail in details:
        row = asdict(detail)
        row["resolution"] = detail.resolution
        rows.append(row)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(source),
        "file_count": len(details),
        "files": rows,
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
