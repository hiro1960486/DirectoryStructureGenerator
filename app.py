"""Directory Structure Generator entry point with visible crash reporting.

Version: 2.4.0
Updated: 2026-09-22
Author: hiro1960
"""

from __future__ import annotations

import ctypes
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def log_path() -> Path:
    base = Path(os.getenv("LOCALAPPDATA") or Path.home())
    folder = base / "DirectoryStructureGenerator"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "app_error.log"


def report_fatal_error(title: str, details: str) -> None:
    """Write a diagnostic log and show a native Windows dialog when possible."""
    message = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {title}\n{details}\n\n"
    try:
        with log_path().open("a", encoding="utf-8") as handle:
            handle.write(message)
    except OSError:
        pass
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(0, details, title, 0x10)  # type: ignore[attr-defined]
        except Exception:
            pass
    print(message, file=sys.stderr)


def main() -> int:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QMessageBox
        from dsg_app.main_window import MainWindow
        from dsg_app.version import APP_NAME, APP_VERSION
    except Exception:
        report_fatal_error(
            "起動準備エラー",
            "PySide6またはアプリ部品を読み込めませんでした。\n"
            "START_APP.batから起動してください。\n\n" + traceback.format_exc(),
        )
        return 1

    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        application = QApplication(sys.argv)
        application.setApplicationName(APP_NAME)
        application.setApplicationVersion(APP_VERSION)
        application.setOrganizationName("hiro1960")
        window = MainWindow()
        window.show()
        return application.exec()
    except Exception:
        details = traceback.format_exc()
        report_fatal_error("アプリ起動エラー", details)
        try:
            QMessageBox.critical(None, "アプリ起動エラー", details)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
