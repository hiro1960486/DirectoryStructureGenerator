"""Popup dialog for optional image and media analysis.

Version: 2.1.0
Updated: 2026-09-21
Author: hiro1960
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .exporters import format_size
from .media_analyzer import (
    MediaAnalysisCancelled,
    MediaRecord,
    analyze_scan_result,
    export_media_csv,
    export_media_json,
)
from .models import FilterSettings
from .scanner import DirectoryScanner, ScanCancelled


class MediaWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(int, int, str)

    def __init__(
        self,
        source: Path,
        output: Path,
        settings: FilterSettings,
        include_exif: bool,
    ) -> None:
        super().__init__()
        self.source = source
        self.output = output
        self.settings = settings
        self.include_exif = include_exif
        self._cancel = False

    @Slot()
    def run(self) -> None:
        try:
            scanner = DirectoryScanner(
                self.settings,
                cancel_requested=lambda: self._cancel,
                excluded_absolute_paths=[self.output],
            )
            result = scanner.scan(self.source)
            records = analyze_scan_result(
                result,
                include_exif=self.include_exif,
                cancel_requested=lambda: self._cancel,
                progress=lambda current, total, path: self.progress.emit(current, total, path),
            )
            self.finished.emit(records)
        except (ScanCancelled, MediaAnalysisCancelled):
            self.cancelled.emit()
        except Exception as exc:  # GUI boundary
            self.failed.emit(str(exc))

    @Slot()
    def cancel(self) -> None:
        self._cancel = True


class MediaAnalysisDialog(QDialog):
    HEADERS = ["ファイル", "形式", "解像度", "縦横比", "サイズ", "更新日時", "EXIF", "エラー"]

    def __init__(
        self,
        source: Path,
        output: Path,
        settings: FilterSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.source = source
        self.output = output
        self.settings = settings
        self.records: list[MediaRecord] = []
        self.thread: QThread | None = None
        self.worker: MediaWorker | None = None

        self.setWindowTitle("画像・メディア解析")
        self.resize(1120, 680)
        self.setMinimumSize(820, 520)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        title = QLabel("画像・メディア解析")
        title.setStyleSheet("font-size:18pt;font-weight:700")
        layout.addWidget(title)
        source_label = QLabel(f"対象フォルダー: {self.source}")
        source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(source_label)

        note = QLabel(
            "通常のツリー走査とは別に、対応画像の解像度などを取得します。"
            "元ファイルの変更・削除は行いません。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        option_row = QHBoxLayout()
        self.exif_check = QCheckBox("安全なEXIF情報も取得する（GPS位置情報は出力しません）")
        self.exif_check.setChecked(False)
        option_row.addWidget(self.exif_check)
        option_row.addStretch()
        layout.addLayout(option_row)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(self.HEADERS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.summary_label = QLabel("未解析")
        layout.addWidget(self.summary_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        buttons = QHBoxLayout()
        self.analyze_button = QPushButton("画像を解析")
        self.analyze_button.setObjectName("primary")
        self.csv_button = QPushButton("CSVを保存")
        self.json_button = QPushButton("JSONを保存")
        self.cancel_button = QPushButton("中止")
        self.cancel_button.setObjectName("danger")
        self.close_button = QPushButton("閉じる")
        self.csv_button.setEnabled(False)
        self.json_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.analyze_button.clicked.connect(self.start_analysis)
        self.csv_button.clicked.connect(self.save_csv)
        self.json_button.clicked.connect(self.save_json)
        self.cancel_button.clicked.connect(self.cancel_analysis)
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.analyze_button)
        buttons.addWidget(self.csv_button)
        buttons.addWidget(self.json_button)
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    def start_analysis(self) -> None:
        if self.thread and self.thread.isRunning():
            return
        self.records = []
        self.table.setRowCount(0)
        self.summary_label.setText("対象ファイルを確認しています…")
        self.progress.setRange(0, 0)
        self.analyze_button.setEnabled(False)
        self.exif_check.setEnabled(False)
        self.csv_button.setEnabled(False)
        self.json_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.close_button.setEnabled(False)

        self.thread = QThread(self)
        self.worker = MediaWorker(
            self.source,
            self.output,
            self.settings,
            self.exif_check.isChecked(),
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.cancelled.connect(self.on_cancelled)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.cancelled.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        self.thread.start()

    @Slot(int, int, str)
    def on_progress(self, current: int, total: int, path: str) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(current)
        self.summary_label.setText(f"解析中 {current:,} / {total:,}: {path}")

    @Slot(object)
    def on_finished(self, records: list[MediaRecord]) -> None:
        self.records = records
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(records))
        error_count = 0
        for row, record in enumerate(records):
            if record.error:
                error_count += 1
            values = [
                record.relative_path,
                record.format,
                record.resolution,
                record.aspect_ratio,
                format_size(record.file_size),
                record.modified,
                record.exif,
                record.error,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.setSortingEnabled(True)
        self.summary_label.setText(f"解析完了: 画像 {len(records):,}件 ｜ エラー {error_count:,}件")
        self.progress.setRange(0, 1)
        self.progress.setValue(1)

    @Slot(str)
    def on_failed(self, message: str) -> None:
        self.summary_label.setText("解析エラー")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        QMessageBox.critical(self, "画像解析エラー", message)

    @Slot()
    def on_cancelled(self) -> None:
        self.summary_label.setText("解析を中止しました")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)

    def _set_idle(self, has_records: bool) -> None:
        self.analyze_button.setEnabled(True)
        self.exif_check.setEnabled(True)
        self.csv_button.setEnabled(has_records)
        self.json_button.setEnabled(has_records)
        self.cancel_button.setEnabled(False)
        self.close_button.setEnabled(True)

    @Slot()
    def _thread_finished(self) -> None:
        finished_thread = self.thread
        self.worker = None
        self.thread = None
        if finished_thread is not None:
            finished_thread.deleteLater()
        self._set_idle(bool(self.records))

    def cancel_analysis(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.summary_label.setText("中止を待っています…")

    def _default_path(self, suffix: str) -> Path:
        safe_name = self.source.name or "images"
        return self.output / f"{safe_name}_image_report.{suffix}"

    def save_csv(self) -> None:
        default = self._default_path("csv")
        filename, _ = QFileDialog.getSaveFileName(
            self, "画像レポートCSVを保存", str(default), "CSVファイル (*.csv)"
        )
        if not filename:
            return
        try:
            export_media_csv(self.records, Path(filename))
        except OSError as exc:
            QMessageBox.critical(self, "保存エラー", str(exc))
            return
        QMessageBox.information(self, "保存完了", f"CSVを保存しました。\n\n{filename}")

    def save_json(self) -> None:
        default = self._default_path("json")
        filename, _ = QFileDialog.getSaveFileName(
            self, "画像レポートJSONを保存", str(default), "JSONファイル (*.json)"
        )
        if not filename:
            return
        try:
            export_media_json(self.records, self.source, Path(filename))
        except OSError as exc:
            QMessageBox.critical(self, "保存エラー", str(exc))
            return
        QMessageBox.information(self, "保存完了", f"JSONを保存しました。\n\n{filename}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, "解析中", "解析を中止してから閉じてください。")
            event.ignore()
            return
        event.accept()
