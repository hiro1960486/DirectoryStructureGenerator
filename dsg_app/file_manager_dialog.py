"""Popup UI for read-only inspection and non-destructive organization copies.

Version: 2.2.0
Updated: 2026-09-21
Author: hiro1960
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import (
    QCloseEvent, QDesktopServices, QDragEnterEvent, QDragMoveEvent, QDropEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .exporters import format_size
from .file_inspector import (
    FileDetail, InspectionCancelled, export_details_csv, export_details_json,
    inspect_scan_result,
)
from .models import FilterSettings
from .organizer import CopyCancelled, CopyPlan, build_copy_plans, execute_copy_plans
from .scanner import DirectoryScanner, ScanCancelled


def first_dropped_directory(urls: list[QUrl]) -> str | None:
    """Return the first existing local directory from a drop operation."""
    for url in urls:
        if not url.isLocalFile():
            continue
        candidate = Path(url.toLocalFile())
        if candidate.is_dir():
            return str(candidate.resolve())
    return None


class FolderDropComboBox(QComboBox):
    """Editable destination field that accepts a dropped local folder."""

    folderDropped = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    @staticmethod
    def _folder(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> str | None:
        mime = event.mimeData()
        return first_dropped_directory(mime.urls()) if mime.hasUrls() else None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._folder(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._folder(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        folder = self._folder(event)
        if not folder:
            event.ignore()
            return
        self.setCurrentText(folder)
        self.folderDropped.emit(folder)
        event.acceptProposedAction()


class FolderDropWidget(QWidget):
    """Organize tab that accepts a dropped local folder anywhere on the tab."""

    folderDropped = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    @staticmethod
    def _folder(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> str | None:
        mime = event.mimeData()
        return first_dropped_directory(mime.urls()) if mime.hasUrls() else None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._folder(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._folder(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        folder = self._folder(event)
        if not folder:
            event.ignore()
            return
        self.folderDropped.emit(folder)
        event.acceptProposedAction()


class InspectionWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(int, int, str)

    def __init__(self, source: Path, output: Path, settings: FilterSettings, options: dict[str, bool]) -> None:
        super().__init__()
        self.source, self.output, self.settings, self.options = source, output, settings, options
        self._cancel = False

    @Slot()
    def run(self) -> None:
        try:
            result = DirectoryScanner(
                self.settings, cancel_requested=lambda: self._cancel,
                excluded_absolute_paths=[self.output],
            ).scan(self.source)
            details = inspect_scan_result(
                result,
                include_lines=self.options["lines"],
                include_exif=self.options["exif"],
                include_gps=self.options["gps"],
                include_sha256=self.options["sha256"],
                cancel_requested=lambda: self._cancel,
                progress=lambda current, total, path: self.progress.emit(current, total, path),
            )
            self.finished.emit(details)
        except (ScanCancelled, InspectionCancelled):
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    @Slot()
    def cancel(self) -> None:
        self._cancel = True


class CopyWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(int, int, str)

    def __init__(self, plans: list[CopyPlan], destination: Path) -> None:
        super().__init__()
        self.plans, self.destination = plans, destination
        self._cancel = False

    @Slot()
    def run(self) -> None:
        try:
            result = execute_copy_plans(
                self.plans, self.destination,
                cancel_requested=lambda: self._cancel,
                progress=lambda current, total, path: self.progress.emit(current, total, path),
            )
            self.finished.emit(result)
        except CopyCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    @Slot()
    def cancel(self) -> None:
        self._cancel = True


class FileManagerDialog(QDialog):
    HEADERS = [
        "ファイル", "区分", "拡張子", "サイズ", "更新日時", "作成日時", "行数",
        "アクセス権", "読取専用", "画像形式", "解像度", "縦横比", "カラー",
        "撮影日時", "カメラ", "GPS", "SHA256", "エラー",
    ]

    def __init__(
        self, source: Path, output: Path, settings: FilterSettings,
        destination_history: list[str] | None = None, parent=None,
    ) -> None:
        super().__init__(parent)
        self.source, self.output, self.settings = source, output, settings
        self.destination_history = list(destination_history or [])
        self.details: list[FileDetail] = []
        self.detail_by_path: dict[str, FileDetail] = {}
        self.copy_plans: list[CopyPlan] = []
        self.copy_ready = False
        self.thread: QThread | None = None
        self.worker: InspectionWorker | CopyWorker | None = None
        self._mode = ""
        self.setWindowTitle("ファイル詳細・整理コピー")
        self.resize(1280, 780)
        self.setMinimumSize(960, 620)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        title = QLabel("ファイル詳細・整理コピー")
        title.setStyleSheet("font-size:18pt;font-weight:700")
        outer.addWidget(title)
        message = QLabel(
            "ファイルを読み取り専用で調査し、選択したものを指定フォルダーへコピーします。"
            "元ファイルの削除・移動・名前変更は行いません。"
        )
        message.setWordWrap(True)
        outer.addWidget(message)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._detail_tab(), "1. ファイル詳細")
        self.tabs.addTab(self._organize_tab(), "2. 整理コピー")
        self.tabs.currentChanged.connect(self._tab_changed)
        outer.addWidget(self.tabs, 1)

        status = QHBoxLayout()
        self.status_label = QLabel("未解析")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.cancel_button = QPushButton("中止")
        self.cancel_button.setObjectName("danger")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_operation)
        self.close_button = QPushButton("閉じる")
        self.close_button.clicked.connect(self.accept)
        status.addWidget(self.status_label, 2)
        status.addWidget(self.progress, 1)
        status.addWidget(self.cancel_button)
        status.addWidget(self.close_button)
        outer.addLayout(status)

    def _detail_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        options = QHBoxLayout()
        self.lines_check = QCheckBox("テキスト・コードの行数")
        self.lines_check.setChecked(True)
        self.exif_check = QCheckBox("Exif情報")
        self.gps_check = QCheckBox("GPSを含める（個人情報に注意）")
        self.gps_check.setEnabled(False)
        self.exif_check.toggled.connect(self.gps_check.setEnabled)
        self.sha_check = QCheckBox("SHA256（重複確認用・時間がかかります）")
        options.addWidget(self.lines_check)
        options.addWidget(self.exif_check)
        options.addWidget(self.gps_check)
        options.addWidget(self.sha_check)
        options.addStretch()
        self.inspect_button = QPushButton("詳細を解析")
        self.inspect_button.setObjectName("primary")
        self.inspect_button.clicked.connect(self.start_inspection)
        options.addWidget(self.inspect_button)
        layout.addLayout(options)

        filters = QHBoxLayout()
        self.type_filter = QComboBox()
        self.type_filter.addItems(["すべて", "一般ファイル", "画像ファイル"])
        self.type_filter.currentTextChanged.connect(self.apply_filter)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("ファイル名・パスを検索")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.apply_filter)
        self.csv_button = QPushButton("CSVレポート")
        self.json_button = QPushButton("JSONレポート")
        self.csv_button.setEnabled(False)
        self.json_button.setEnabled(False)
        self.csv_button.clicked.connect(lambda: self.save_report("csv"))
        self.json_button.clicked.connect(lambda: self.save_report("json"))
        filters.addWidget(self.type_filter)
        filters.addWidget(self.search_edit, 1)
        filters.addWidget(self.csv_button)
        filters.addWidget(self.json_button)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.update_preview)
        splitter.addWidget(self.table)

        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        self.thumbnail = QLabel("画像を選択すると\nプレビューします")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setMinimumSize(240, 200)
        self.thumbnail.setStyleSheet("border:1px solid #6b7280;border-radius:8px")
        self.selected_info = QLabel("未選択")
        self.selected_info.setWordWrap(True)
        self.open_file_button = QPushButton("元ファイルを開く")
        self.open_folder_button = QPushButton("保存場所を開く")
        self.open_file_button.clicked.connect(self.open_selected_file)
        self.open_folder_button.clicked.connect(self.open_selected_folder)
        preview_layout.addWidget(self.thumbnail)
        preview_layout.addWidget(self.selected_info)
        preview_layout.addStretch()
        preview_layout.addWidget(self.open_file_button)
        preview_layout.addWidget(self.open_folder_button)
        splitter.addWidget(preview)
        splitter.setSizes([960, 260])
        layout.addWidget(splitter, 1)
        return tab

    def _organize_tab(self) -> QWidget:
        tab = FolderDropWidget()
        tab.folderDropped.connect(self.set_dropped_destination)
        layout = QVBoxLayout(tab)
        self.selection_label = QLabel("詳細画面でコピーしたいファイルを選択してください。")
        self.selection_label.setStyleSheet("font-weight:600")
        layout.addWidget(self.selection_label)
        form = QFormLayout()
        destination_row = QHBoxLayout()
        self.destination_combo = FolderDropComboBox()
        self.destination_combo.setEditable(True)
        self.destination_combo.addItems(self.destination_history)
        if not self.destination_history:
            self.destination_combo.setCurrentText(str(self.output / "Organized_Files"))
        self.destination_combo.currentTextChanged.connect(self.invalidate_copy_plan)
        self.destination_combo.folderDropped.connect(self.set_dropped_destination)
        browse = QPushButton("参照…")
        browse.clicked.connect(self.choose_destination)
        destination_row.addWidget(self.destination_combo, 1)
        destination_row.addWidget(browse)
        form.addRow("コピー先", destination_row)
        drop_help = QLabel(
            "エクスプローラーからコピー先フォルダーを、この画面またはコピー先欄へ"
            "ドラッグ＆ドロップできます。"
        )
        drop_help.setWordWrap(True)
        drop_help.setStyleSheet("color:#2563eb")
        form.addRow("", drop_help)

        self.name_template = QComboBox()
        self.name_template.setEditable(True)
        self.name_template.addItems([
            "{name}", "{stem}_{index:03d}{ext}", "{date}_{stem}{ext}",
            "{created}_{stem}{ext}", "{type}_{index:03d}{ext}",
        ])
        self.name_template.currentTextChanged.connect(self.invalidate_copy_plan)
        form.addRow("新しいファイル名／命名ルール", self.name_template)
        rule_help = QLabel(
            "1件なら新しい名前を直接入力できます。複数件では "
            "{name} {stem} {ext} {index:03d} {date} {created} {type} を使用できます。"
        )
        rule_help.setWordWrap(True)
        form.addRow("", rule_help)
        self.keep_subfolders = QCheckBox("元のサブフォルダー構成を維持する")
        self.keep_subfolders.setChecked(True)
        self.keep_subfolders.toggled.connect(self.invalidate_copy_plan)
        form.addRow("", self.keep_subfolders)
        self.collision_combo = QComboBox()
        self.collision_combo.addItem("自動で連番を付ける（推奨）", "number")
        self.collision_combo.addItem("同名ファイルはスキップ", "skip")
        self.collision_combo.currentIndexChanged.connect(self.invalidate_copy_plan)
        form.addRow("同名ファイルがある場合", self.collision_combo)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.plan_button = QPushButton("コピー内容を事前確認")
        self.plan_button.clicked.connect(self.prepare_copy)
        self.copy_button = QPushButton("確認した内容で整理コピー")
        self.copy_button.setObjectName("primary")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.start_copy)
        buttons.addWidget(self.plan_button)
        buttons.addWidget(self.copy_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.plan_table = QTableWidget(0, 3)
        self.plan_table.setHorizontalHeaderLabels(["元ファイル", "コピー先", "状態"])
        self.plan_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.plan_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.plan_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.plan_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.plan_table, 1)
        warning = QLabel(
            "安全仕様：元ファイルは変更・削除しません。コピー先が対象フォルダー内の場合は実行できません。"
            "コピー結果はコピー先の _DirectoryStructureGenerator_copy_log.csv に記録します。"
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        return tab

    def start_inspection(self) -> None:
        if self.thread and self.thread.isRunning():
            return
        self.details = []
        self.detail_by_path = {}
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.table.setSortingEnabled(True)
        options = {
            "lines": self.lines_check.isChecked(), "exif": self.exif_check.isChecked(),
            "gps": self.exif_check.isChecked() and self.gps_check.isChecked(),
            "sha256": self.sha_check.isChecked(),
        }
        self._start_worker(InspectionWorker(self.source, self.output, self.settings, options), "inspect")
        self.status_label.setText("対象ファイルを確認しています…")

    def _start_worker(self, worker: InspectionWorker | CopyWorker, mode: str) -> None:
        self._mode = mode
        self.thread = QThread(self)
        self.worker = worker
        worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)
        worker.progress.connect(self.on_progress)
        worker.finished.connect(self.on_worker_finished)
        worker.failed.connect(self.on_failed)
        worker.cancelled.connect(self.on_cancelled)
        worker.finished.connect(self.thread.quit)
        worker.failed.connect(self.thread.quit)
        worker.cancelled.connect(self.thread.quit)
        self.thread.finished.connect(worker.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        self._set_running(True)
        self.thread.start()

    @Slot(int, int, str)
    def on_progress(self, current: int, total: int, path: str) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(current)
        action = "コピー中" if self._mode == "copy" else "解析中"
        self.status_label.setText(f"{action} {current:,} / {total:,}: {path}")

    @Slot(object)
    def on_worker_finished(self, result: object) -> None:
        if self._mode == "inspect":
            self.details = list(result)  # type: ignore[arg-type]
            self.detail_by_path = {detail.full_path: detail for detail in self.details}
            self.populate_table()
            errors = sum(bool(detail.error) for detail in self.details)
            images = sum(detail.is_image for detail in self.details)
            self.status_label.setText(
                f"解析完了: 全{len(self.details):,}件 ｜ 画像{images:,}件 ｜ エラー{errors:,}件"
            )
        else:
            self.copy_plans = list(result)  # type: ignore[arg-type]
            self.populate_plan_table()
            copied = sum(plan.status == "コピー完了" for plan in self.copy_plans)
            failed = sum(plan.status == "コピー失敗" for plan in self.copy_plans)
            self.status_label.setText(f"整理コピー完了: {copied:,}件 ｜ 失敗{failed:,}件")
            destination = self.destination_combo.currentText().strip()
            if destination:
                self.destination_history = [destination] + [
                    item for item in self.destination_history if item != destination
                ][:9]

    @Slot(str)
    def on_failed(self, message: str) -> None:
        self.status_label.setText("エラー")
        QMessageBox.critical(self, "処理エラー", message)

    @Slot()
    def on_cancelled(self) -> None:
        self.status_label.setText("処理を中止しました")

    @Slot()
    def _thread_finished(self) -> None:
        finished = self.thread
        self.worker, self.thread = None, None
        if finished:
            finished.deleteLater()
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        self.inspect_button.setEnabled(not running)
        self.plan_button.setEnabled(not running)
        self.copy_button.setEnabled(not running and self.copy_ready)
        self.cancel_button.setEnabled(running)
        self.close_button.setEnabled(not running)
        self.progress.setRange(0, 0 if running else 1)
        if not running:
            self.progress.setValue(1 if self.details else 0)

    def cancel_operation(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.status_label.setText("中止を待っています…")

    def populate_table(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.details))
        for row, detail in enumerate(self.details):
            values = [
                detail.relative_path, "画像" if detail.is_image else "一般", detail.extension,
                format_size(detail.file_size), detail.modified, detail.created,
                "" if detail.line_count is None else f"{detail.line_count:,}",
                detail.permissions, "はい" if detail.readonly else "いいえ", detail.image_format,
                detail.resolution, detail.aspect_ratio, detail.color_mode, detail.exif_datetime,
                detail.camera, detail.gps, detail.sha256, detail.error,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, detail.full_path)
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        self.csv_button.setEnabled(bool(self.details))
        self.json_button.setEnabled(bool(self.details))
        self.apply_filter()

    def apply_filter(self) -> None:
        if not hasattr(self, "table"):
            return
        search = self.search_edit.text().casefold()
        kind = self.type_filter.currentText()
        for row in range(self.table.rowCount()):
            path_item = self.table.item(row, 0)
            type_item = self.table.item(row, 1)
            visible = bool(path_item and search in path_item.text().casefold())
            if kind == "一般ファイル":
                visible = visible and bool(type_item and type_item.text() == "一般")
            elif kind == "画像ファイル":
                visible = visible and bool(type_item and type_item.text() == "画像")
            self.table.setRowHidden(row, not visible)

    def selected_details(self) -> list[FileDetail]:
        selected: list[FileDetail] = []
        for index in self.table.selectionModel().selectedRows():
            item = self.table.item(index.row(), 0)
            if item and (detail := self.detail_by_path.get(str(item.data(Qt.ItemDataRole.UserRole)))):
                selected.append(detail)
        return selected

    def update_preview(self) -> None:
        self.invalidate_copy_plan()
        selected = self.selected_details()
        self.selection_label.setText(f"選択中: {len(selected):,}件")
        if not selected:
            self.thumbnail.clear()
            self.thumbnail.setText("画像を選択すると\nプレビューします")
            self.selected_info.setText("未選択")
            return
        detail = selected[0]
        self.selected_info.setText(
            f"{detail.relative_path}\n{format_size(detail.file_size)}"
            + (f"\n{detail.resolution} / {detail.color_mode}" if detail.is_image else "")
        )
        pixmap = QPixmap(detail.full_path) if detail.is_image else QPixmap()
        if not pixmap.isNull():
            self.thumbnail.setPixmap(
                pixmap.scaled(240, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self.thumbnail.setPixmap(QPixmap())
            self.thumbnail.setText("プレビューなし")

    def _selected_path(self) -> Path | None:
        details = self.selected_details()
        return Path(details[0].full_path) if details else None

    def open_selected_file(self) -> None:
        if path := self._selected_path():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_selected_folder(self) -> None:
        if path := self._selected_path():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def save_report(self, kind: str) -> None:
        default = self.output / f"{self.source.name}_file_details.{kind}"
        label = "CSVファイル (*.csv)" if kind == "csv" else "JSONファイル (*.json)"
        filename, _ = QFileDialog.getSaveFileName(self, "詳細レポートを保存", str(default), label)
        if not filename:
            return
        try:
            if kind == "csv":
                export_details_csv(self.details, Path(filename))
            else:
                export_details_json(self.details, self.source, Path(filename))
        except OSError as exc:
            QMessageBox.critical(self, "保存エラー", str(exc))
            return
        QMessageBox.information(self, "保存完了", f"レポートを保存しました。\n\n{filename}")

    def _tab_changed(self, index: int) -> None:
        if index == 1:
            selected = self.selected_details()
            self.selection_label.setText(f"選択中: {len(selected):,}件")

    def choose_destination(self) -> None:
        initial = self.destination_combo.currentText().strip() or str(self.output)
        selected = QFileDialog.getExistingDirectory(self, "整理コピー先を選択", initial)
        if selected:
            self.destination_combo.setCurrentText(selected)

    @Slot(str)
    def set_dropped_destination(self, folder: str) -> None:
        self.destination_combo.setCurrentText(folder)
        if hasattr(self, "status_label"):
            self.status_label.setText(f"コピー先を設定しました: {folder}")

    def prepare_copy(self) -> None:
        details = self.selected_details()
        if not details:
            QMessageBox.warning(self, "確認", "ファイル詳細画面でコピーするファイルを選択してください。")
            return
        destination_text = self.destination_combo.currentText().strip()
        if not destination_text:
            QMessageBox.warning(self, "確認", "コピー先フォルダーを指定してください。")
            return
        destination = Path(destination_text).expanduser().resolve()
        if destination == self.source.resolve() or destination.is_relative_to(self.source.resolve()):
            QMessageBox.warning(
                self, "安全確認", "コピー先には、対象フォルダーの外側を指定してください。\n元データ側には何も作成しません。"
            )
            return
        template = self.name_template.currentText().strip() or "{name}"
        if len(details) == 1 and "{" not in template:
            template = template
        elif len(details) > 1 and "{" not in template:
            QMessageBox.warning(self, "確認", "複数ファイルでは {index} などを含む命名ルールを指定してください。")
            return
        try:
            self.copy_plans = build_copy_plans(
                details, destination, template, self.keep_subfolders.isChecked(),
                str(self.collision_combo.currentData()),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "命名ルール", str(exc))
            return
        self.populate_plan_table()
        self.copy_ready = bool(self.copy_plans)
        self.copy_button.setEnabled(self.copy_ready)
        self.status_label.setText("コピー内容を確認してください。まだコピーは実行していません。")

    def populate_plan_table(self) -> None:
        self.plan_table.setRowCount(len(self.copy_plans))
        for row, plan in enumerate(self.copy_plans):
            for column, value in enumerate((plan.relative_path, str(plan.destination), plan.status)):
                self.plan_table.setItem(row, column, QTableWidgetItem(value))

    def start_copy(self) -> None:
        if not self.copy_plans or not self.copy_ready:
            return
        answer = QMessageBox.question(
            self, "整理コピーの実行",
            f"{len(self.copy_plans):,}件の計画を実行します。\n元ファイルは変更されません。\n\n実行しますか？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        destination = Path(self.destination_combo.currentText().strip()).expanduser().resolve()
        self.copy_ready = False
        self._start_worker(CopyWorker(self.copy_plans, destination), "copy")

    def invalidate_copy_plan(self, *_args) -> None:  # type: ignore[no-untyped-def]
        self.copy_ready = False
        if hasattr(self, "copy_button"):
            self.copy_button.setEnabled(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, "処理中", "処理を中止してから閉じてください。")
            event.ignore()
            return
        event.accept()
