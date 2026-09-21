"""Image and media metadata analysis helpers.

Version: 2.1.0
Updated: 2026-09-21
Author: hiro1960
"""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image, UnidentifiedImageError

from .models import ScanNode, ScanResult


IMAGE_EXTENSIONS = {
    ".bmp", ".gif", ".jfif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp",
}

SAFE_EXIF_TAGS = {
    "DateTime",
    "DateTimeOriginal",
    "Make",
    "Model",
    "Orientation",
    "Software",
}


class MediaAnalysisCancelled(RuntimeError):
    """Raised when media analysis is cancelled by the user."""


@dataclass(slots=True)
class MediaRecord:
    name: str
    relative_path: str
    full_path: str
    format: str
    width: int | None
    height: int | None
    aspect_ratio: str
    file_size: int
    modified: str
    exif: str = ""
    error: str = ""

    @property
    def resolution(self) -> str:
        if self.width is None or self.height is None:
            return ""
        return f"{self.width} × {self.height}"

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["resolution"] = self.resolution
        return value


def is_supported_image(path: Path) -> bool:
    return path.suffix.casefold() in IMAGE_EXTENSIONS


def _ratio(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return ""
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _safe_exif(image: Image.Image) -> str:
    """Return a privacy-conscious EXIF summary.

    GPS and free-form comment fields are deliberately not exported.
    """
    try:
        exif = image.getexif()
    except (AttributeError, OSError, ValueError):
        return ""
    values: list[str] = []
    for tag_id, raw_value in exif.items():
        tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
        if tag_name not in SAFE_EXIF_TAGS:
            continue
        value = str(raw_value).replace("\r", " ").replace("\n", " ").strip()
        if value:
            values.append(f"{tag_name}={value}")
    return "; ".join(values)


def analyze_image(path: Path, relative_path: Path, include_exif: bool = False) -> MediaRecord:
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with Image.open(path) as image:
            width, height = image.size
            image_format = image.format or path.suffix.lstrip(".").upper()
            exif = _safe_exif(image) if include_exif else ""
        return MediaRecord(
            name=path.name,
            relative_path=relative_path.as_posix(),
            full_path=str(path),
            format=image_format,
            width=width,
            height=height,
            aspect_ratio=_ratio(width, height),
            file_size=stat.st_size,
            modified=modified,
            exif=exif,
        )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        return MediaRecord(
            name=path.name,
            relative_path=relative_path.as_posix(),
            full_path=str(path),
            format=path.suffix.lstrip(".").upper(),
            width=None,
            height=None,
            aspect_ratio="",
            file_size=stat.st_size,
            modified=modified,
            error=str(exc),
        )


def _file_nodes(node: ScanNode) -> Iterable[ScanNode]:
    if not node.is_dir:
        yield node
    for child in node.children:
        yield from _file_nodes(child)


def analyze_scan_result(
    result: ScanResult,
    include_exif: bool = False,
    cancel_requested: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[MediaRecord]:
    cancel_requested = cancel_requested or (lambda: False)
    progress = progress or (lambda _current, _total, _path: None)
    nodes = [node for node in _file_nodes(result.root) if is_supported_image(node.path)]
    records: list[MediaRecord] = []
    total = len(nodes)
    for index, node in enumerate(nodes, start=1):
        if cancel_requested():
            raise MediaAnalysisCancelled("画像解析を中止しました。")
        progress(index, total, node.relative_path.as_posix())
        try:
            records.append(analyze_image(node.path, node.relative_path, include_exif))
        except OSError as exc:
            records.append(
                MediaRecord(
                    name=node.name,
                    relative_path=node.relative_path.as_posix(),
                    full_path=str(node.path),
                    format=node.path.suffix.lstrip(".").upper(),
                    width=None,
                    height=None,
                    aspect_ratio="",
                    file_size=node.size,
                    modified=datetime.fromtimestamp(node.modified).strftime("%Y-%m-%d %H:%M:%S"),
                    error=str(exc),
                )
            )
    return records


def _excel_safe(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_media_csv(records: list[MediaRecord], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "name", "relative_path", "full_path", "format", "resolution", "width", "height",
        "aspect_ratio", "file_size", "modified", "exif", "error",
    ]
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = record.to_dict()
            writer.writerow({key: _excel_safe(row[key]) for key in fields})


def export_media_json(records: list[MediaRecord], source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(source),
        "image_count": len(records),
        "gps_exported": False,
        "images": [record.to_dict() for record in records],
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
