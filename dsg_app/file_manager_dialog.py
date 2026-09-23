"""Popup UI for read-only inspection and safety-checked file organization.

Version: 2.8.1
Updated: 2026-09-23
Author: hiro1960
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QEvent, QItemSelectionModel, QObject, QRect, QThread, Qt, QUrl, Signal, Slot,
)
from PySide6.QtGui import (
    QCloseEvent, QDesktopServices, QDragEnterEvent, QDragMoveEvent, QDropEvent,
    QImage, QKeySequence, QMouseEvent, QPainter, QPixmap, QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMenu, QMessageBox, QProgressBar, QPushButton, QSlider, QSplitter, QStackedWidget,
    QStyle, QStyleOptionButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from PIL import Image, ImageOps, UnidentifiedImageError

from .exporters import format_size
from .file_inspector import (
    FileDetail, InspectionCancelled, export_details_csv, export_details_json,
    inspect_scan_result,
)
from .models import FilterSettings
from .organizer import (
    CopyCancelled, CopyPlan, build_copy_plans, execute_copy_plans,
    extension_was_changed, rendered_name, sanitize_filename,
)
from .scanner import DirectoryScanner, ScanCancelled


SORT_ROLE = Qt.ItemDataRole.UserRole.value + 1


class SortableTableWidgetItem(QTableWidgetItem):
    """Table item that sorts with a raw numeric/text key instead of display text."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(SORT_ROLE)
        right = other.data(SORT_ROLE)
        if left is None or right is None:
            return super().__lt__(other)
        try:
            return left < right
        except TypeError:
            return str(left).casefold() < str(right).casefold()


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


class CheckableHeaderView(QHeaderView):
    """Header with a tri-state checkbox in the first column."""

    checkStateClicked = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._check_state = Qt.CheckState.Unchecked

    def setCheckState(self, state: Qt.CheckState) -> None:
        if state == self._check_state:
            return
        self._check_state = state
        self.viewport().update()

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:
        super().paintSection(painter, rect, logical_index)
        if logical_index != 0:
            return
        option = QStyleOptionButton()
        option.state = QStyle.StateFlag.State_Enabled
        if self._check_state == Qt.CheckState.Checked:
            option.state |= QStyle.StateFlag.State_On
        elif self._check_state == Qt.CheckState.PartiallyChecked:
            option.state |= QStyle.StateFlag.State_NoChange
        else:
            option.state |= QStyle.StateFlag.State_Off
        indicator = QApplication.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, option, self
        )
        option.rect = QRect(
            rect.left() + (rect.width() - indicator.width()) // 2,
            rect.top() + (rect.height() - indicator.height()) // 2,
            indicator.width(), indicator.height(),
        )
        QApplication.style().drawControl(
            QStyle.ControlElement.CE_CheckBox, option, painter, self
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.logicalIndexAt(event.position().toPoint()) == 0:
            next_state = (
                Qt.CheckState.Unchecked
                if self._check_state == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
            self.checkStateClicked.emit(next_state.value)
            return
        super().mousePressEvent(event)


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

    def __init__(
        self, plans: list[CopyPlan], destination: Path, delete_sources: bool = False,
    ) -> None:
        super().__init__()
        self.plans, self.destination = plans, destination
        self.delete_sources = delete_sources
        self._cancel = False

    @Slot()
    def run(self) -> None:
        try:
            result = execute_copy_plans(
                self.plans, self.destination, delete_sources=self.delete_sources,
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
        "選択", "ファイル名", "保存場所", "区分", "拡張子", "サイズ", "更新日時",
        "作成日時", "行数", "アクセス権", "読取専用", "形式", "解像度",
        "再生時間", "FPS", "映像", "音声", "ビットレート", "チャンネル",
        "縦横比", "カラー", "撮影日時", "カメラ", "GPS", "SHA256", "エラー",
    ]
    CHECK_COLUMN = 0
    NAME_COLUMN = 1
    PATH_COLUMN = 2
    CATEGORY_COLUMN = 3
    SIZE_COLUMN = 5
    MODIFIED_COLUMN = 6
    CREATED_COLUMN = 7
    LINE_COUNT_COLUMN = 8
    RESOLUTION_COLUMN = 12
    DURATION_COLUMN = 13
    FPS_COLUMN = 14
    FILTER_CATEGORIES = [
        ("image", "画像"), ("video", "動画"), ("audio", "音声"),
        ("document", "文書"), ("other", "その他"),
    ]
    NAMING_PRESETS = [
        ("元の名前のまま（おすすめ）", "{name}"),
        ("1件ずつ新しい名前を設定", "__individual__"),
        ("元の名前＋3桁の連番", "{stem}_{index:03d}{ext}"),
        ("今日の日付＋元の名前", "{date}_{stem}{ext}"),
        ("作成日＋元の名前", "{created}_{stem}{ext}"),
        ("画像・動画・一般別＋連番", "{type}_{index:03d}{ext}"),
        ("高度な命名ルール", "__custom__"),
    ]
    COMMON_EXTENSIONS = [
        ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",
        ".svg", ".pdf", ".txt", ".csv", ".json", ".docx", ".xlsx", ".pptx",
        ".mp4", ".mov", ".mp3", ".wav",
    ]

    def __init__(
        self, source: Path, output: Path, settings: FilterSettings,
        destination_history: list[str] | None = None,
        organizer_settings: dict[str, object] | None = None, parent=None,
    ) -> None:
        super().__init__(parent)
        self.source, self.output, self.settings = source, output, settings
        self.destination_history = list(destination_history or [])
        self.organizer_settings = dict(organizer_settings or {})
        saved_extensions = self.organizer_settings.get("custom_extensions", [])
        self.custom_extensions = [
            self.normalized_extension(str(value))
            for value in saved_extensions if str(value).strip()
        ] if isinstance(saved_extensions, list) else []
        self.details: list[FileDetail] = []
        self.detail_by_path: dict[str, FileDetail] = {}
        self.copy_plans: list[CopyPlan] = []
        self.copy_ready = False
        self.thread: QThread | None = None
        self.worker: InspectionWorker | CopyWorker | None = None
        self._mode = ""
        self._table_populating = False
        self._applied_categories: set[str] = set()
        self._last_filter_signature: tuple[str, int, tuple[str, ...]] | None = None
        self._last_check_row: int | None = None
        self._preview_from_plan = False
        self.media_duration = 0
        self.setWindowTitle("ファイル詳細・整理コピー")
        self.resize(1480, 860)
        self.setMinimumSize(1080, 680)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 12)
        outer.setSpacing(10)
        hero = QFrame(objectName="hero")
        hero_layout = QVBoxLayout(hero)
        title = QLabel("ファイル詳細・整理コピー")
        title.setStyleSheet("font-size:18pt;font-weight:700;background:transparent")
        hero_layout.addWidget(title)
        message = QLabel(
            "ファイルを確認・選択し、コピー側の名前を整えて保存します。"
            "既定では元ファイルを保持します。削除を選ぶ場合は実行前に必ず再確認します。"
        )
        message.setWordWrap(True)
        message.setStyleSheet("background:transparent")
        hero_layout.addWidget(message)
        outer.addWidget(hero)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._detail_tab(), "1. ファイル詳細")
        self.tabs.addTab(self._organize_tab(), "2. 整理コピー")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.addWidget(self.tabs)
        self.content_splitter.addWidget(self._preview_panel())
        self.content_splitter.setSizes([1080, 360])
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)
        self.content_splitter.splitterMoved.connect(lambda *_args: self.update_preview(False))
        outer.addWidget(self.content_splitter, 1)

        status = QHBoxLayout()
        self.status_label = QLabel("未解析")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setMinimumWidth(260)
        self.progress.setMaximumWidth(440)
        self.cancel_button = QPushButton("中止")
        self.cancel_button.setObjectName("danger")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_operation)
        self.close_button = QPushButton("閉じる")
        self.close_button.clicked.connect(self.close)
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

        filters = QVBoxLayout()
        chip_row = QHBoxLayout()
        chip_label = QLabel("種別")
        chip_label.setStyleSheet("font-weight:700")
        chip_row.addWidget(chip_label)
        self.filter_buttons: dict[str, QPushButton] = {}
        self.all_filter_button = QPushButton("すべて 0")
        self.all_filter_button.setObjectName("filterChip")
        self.all_filter_button.setCheckable(True)
        self.all_filter_button.setChecked(True)
        self.all_filter_button.clicked.connect(self.select_all_filter_categories)
        chip_row.addWidget(self.all_filter_button)
        for key, label in self.FILTER_CATEGORIES:
            button = QPushButton(f"{label} 0")
            button.setObjectName("filterChip")
            button.setCheckable(True)
            button.toggled.connect(self.on_filter_chip_toggled)
            self.filter_buttons[key] = button
            chip_row.addWidget(button)
        chip_row.addStretch()
        self.clear_filter_button = QPushButton("条件をクリア")
        self.clear_filter_button.clicked.connect(self.clear_filters)
        self.apply_filter_button = QPushButton("適用")
        self.apply_filter_button.setObjectName("primary")
        self.apply_filter_button.clicked.connect(self.commit_category_filter)
        chip_row.addWidget(self.clear_filter_button)
        chip_row.addWidget(self.apply_filter_button)
        filters.addLayout(chip_row)

        action_row = QHBoxLayout()
        self.column_filter_combo = QComboBox()
        self.column_filter_combo.setToolTip("絞り込みの対象列を選びます")
        self.column_filter_combo.addItem("すべての列", -1)
        for column, label in enumerate(self.HEADERS[1:], start=1):
            self.column_filter_combo.addItem(label, column)
        self.column_filter_combo.currentIndexChanged.connect(self.apply_filter)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("選択した列を絞り込み（部分一致）")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.apply_filter)
        self.csv_button = QPushButton("CSVレポート")
        self.json_button = QPushButton("JSONレポート")
        self.csv_button.setEnabled(False)
        self.json_button.setEnabled(False)
        self.csv_button.clicked.connect(lambda: self.save_report("csv"))
        self.json_button.clicked.connect(lambda: self.save_report("json"))
        action_row.addWidget(self.column_filter_combo)
        action_row.addWidget(self.search_edit, 1)
        self.select_all_button = QPushButton("表示中を選択")
        self.clear_selection_button = QPushButton("選択解除")
        self.invert_selection_button = QPushButton("選択反転")
        self.select_all_button.clicked.connect(lambda: self.set_visible_checks("all"))
        self.clear_selection_button.clicked.connect(lambda: self.set_visible_checks("none"))
        self.invert_selection_button.clicked.connect(lambda: self.set_visible_checks("invert"))
        action_row.addWidget(self.select_all_button)
        action_row.addWidget(self.clear_selection_button)
        action_row.addWidget(self.invert_selection_button)
        action_row.addWidget(self.csv_button)
        action_row.addWidget(self.json_button)
        filters.addLayout(action_row)
        self.selection_count_label = QLabel("選択中 0件 ／ 表示中 0件")
        self.selection_count_label.setStyleSheet("font-weight:700;color:#2563eb")
        filters.addWidget(self.selection_count_label)
        self.table_help_label = QLabel(
            "列見出しをクリック：昇順／降順　｜　列見出し・一覧を右クリック：追加操作"
        )
        self.table_help_label.setStyleSheet("color:#64748b")
        filters.addWidget(self.table_help_label)
        layout.addLayout(filters)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        header = CheckableHeaderView(self.table)
        self.table.setHorizontalHeader(header)
        header.checkStateClicked.connect(self.set_header_check_state)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setMinimumSectionSize(42)
        header.setStretchLastSection(False)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(self.NAME_COLUMN, Qt.SortOrder.AscendingOrder)
        header.setSectionsClickable(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.show_header_context_menu)
        self.table.setColumnWidth(self.CHECK_COLUMN, 54)
        self.table.setColumnWidth(self.NAME_COLUMN, 280)
        self.table.setColumnWidth(self.PATH_COLUMN, 360)
        for column in range(3, len(self.HEADERS)):
            self.table.setColumnWidth(column, 120)
        self.table.itemSelectionChanged.connect(self.update_preview)
        self.table.itemChanged.connect(self.on_table_item_changed)
        self.table.currentCellChanged.connect(lambda *_args: self.update_preview())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_context_menu)
        self.table.viewport().installEventFilter(self)
        self.select_all_shortcut = QShortcut(QKeySequence.StandardKey.SelectAll, self.table)
        self.select_all_shortcut.activated.connect(lambda: self.set_visible_checks("all"))
        layout.addWidget(self.table, 1)
        return tab

    def _preview_panel(self) -> QWidget:
        preview = QFrame(objectName="previewCard")
        preview.setMinimumWidth(280)
        preview_layout = QVBoxLayout(preview)
        preview_title = QLabel("プレビュー")
        preview_title.setStyleSheet("font-size:12pt;font-weight:700")
        preview_layout.addWidget(preview_title)
        self.preview_stack = QStackedWidget()
        self.preview_stack.setObjectName("previewCanvas")
        self.preview_placeholder = QLabel("画像・動画・音声を選択すると\nここにプレビューします")
        self.preview_placeholder.setObjectName("previewPlaceholder")
        self.preview_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_placeholder.setMinimumHeight(260)
        self.thumbnail = QLabel()
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setMinimumHeight(260)
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(260)
        self.preview_stack.addWidget(self.preview_placeholder)
        self.preview_stack.addWidget(self.thumbnail)
        self.preview_stack.addWidget(self.video_widget)
        preview_layout.addWidget(self.preview_stack, 1)

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.5)
        self.media_player = QMediaPlayer(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.positionChanged.connect(self.on_media_position)
        self.media_player.durationChanged.connect(self.on_media_duration)
        self.media_player.playbackStateChanged.connect(self.on_playback_state)
        self.media_player.errorOccurred.connect(self.on_media_error)
        self.media_player.metaDataChanged.connect(self.on_media_metadata_changed)
        media_controls = QHBoxLayout()
        self.play_button = QPushButton("▶ 再生")
        self.play_button.clicked.connect(self.toggle_video)
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderMoved.connect(self.media_player.setPosition)
        self.media_time = QLabel("00:00 / 00:00")
        media_controls.addWidget(self.play_button)
        media_controls.addWidget(self.seek_slider, 1)
        media_controls.addWidget(self.media_time)
        self.media_controls_widget = QWidget()
        self.media_controls_widget.setLayout(media_controls)
        self.media_controls_widget.setVisible(False)
        preview_layout.addWidget(self.media_controls_widget)
        self.selected_info = QLabel("未選択")
        self.selected_info.setWordWrap(True)
        self.open_file_button = QPushButton("元ファイルを開く")
        self.open_folder_button = QPushButton("保存場所を開く")
        self.open_file_button.clicked.connect(self.open_selected_file)
        self.open_folder_button.clicked.connect(self.open_selected_folder)
        preview_layout.addWidget(self.selected_info)
        preview_layout.addWidget(self.open_file_button)
        preview_layout.addWidget(self.open_folder_button)
        return preview

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
        default_destination = str(self.organizer_settings.get("default_destination", "")).strip()
        if default_destination:
            self.destination_combo.setCurrentText(default_destination)
        elif not self.destination_history:
            self.destination_combo.setCurrentText(str(self.output / "Organized_Files"))
        self.destination_combo.currentTextChanged.connect(self.invalidate_copy_plan)
        self.destination_combo.folderDropped.connect(self.set_dropped_destination)
        browse = QPushButton("参照…")
        browse.clicked.connect(self.choose_destination)
        create_folder = QPushButton("新しい保存フォルダー…")
        create_folder.clicked.connect(self.create_destination_folder)
        destination_row.addWidget(self.destination_combo, 1)
        destination_row.addWidget(browse)
        destination_row.addWidget(create_folder)
        form.addRow("コピー先", destination_row)
        drop_help = QLabel(
            "エクスプローラーからコピー先フォルダーを、この画面またはコピー先欄へ"
            "ドラッグ＆ドロップできます。"
        )
        drop_help.setWordWrap(True)
        drop_help.setStyleSheet("color:#2563eb")
        form.addRow("", drop_help)

        self.naming_combo = QComboBox()
        for label, template in self.NAMING_PRESETS:
            self.naming_combo.addItem(label, template)
        saved_template = str(self.organizer_settings.get("naming_template", "{name}"))
        saved_index = self.naming_combo.findData(saved_template)
        self.naming_combo.setCurrentIndex(max(saved_index, 0))
        self.naming_combo.currentIndexChanged.connect(self.on_naming_mode_changed)
        form.addRow("新しい名前の付け方", self.naming_combo)
        self.custom_template = QLineEdit()
        self.custom_template.setPlaceholderText("例：{date}_{stem}_{index:03d}{ext}")
        self.custom_template.setText(str(self.organizer_settings.get("custom_template", "{name}")))
        self.custom_template.textChanged.connect(self.invalidate_copy_plan)
        self.custom_template.setVisible(self.naming_combo.currentData() == "__custom__")
        form.addRow("高度な命名ルール", self.custom_template)
        rule_help = QLabel(
            "まず選択肢から方法を選びます。下の「新しいファイル名」は1件ずつ変更できます。"
            "変更されるのはコピー側だけです。"
        )
        rule_help.setWordWrap(True)
        form.addRow("", rule_help)
        self.keep_subfolders = QCheckBox("元のサブフォルダー構成を維持する")
        self.keep_subfolders.setChecked(bool(self.organizer_settings.get("keep_subfolders", True)))
        self.keep_subfolders.toggled.connect(self.invalidate_copy_plan)
        form.addRow("", self.keep_subfolders)
        self.collision_combo = QComboBox()
        self.collision_combo.addItem("自動で連番を付ける（推奨）", "number")
        self.collision_combo.addItem("同名ファイルはスキップ", "skip")
        collision = str(self.organizer_settings.get("collision", "number"))
        self.collision_combo.setCurrentIndex(max(self.collision_combo.findData(collision), 0))
        self.collision_combo.currentIndexChanged.connect(self.invalidate_copy_plan)
        form.addRow("同名ファイルがある場合", self.collision_combo)
        self.source_action_combo = QComboBox()
        self.source_action_combo.addItem("元ファイルを保持する（推奨）", False)
        self.source_action_combo.addItem("コピー成功後に元ファイルを削除する", True)
        self.source_action_combo.currentIndexChanged.connect(self.on_source_action_changed)
        form.addRow("元ファイルの扱い", self.source_action_combo)
        self.source_action_warning = QLabel(
            "元ファイルは保持されます。コピー側だけを整理・リネームします。"
        )
        self.source_action_warning.setWordWrap(True)
        form.addRow("", self.source_action_warning)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.plan_button = QPushButton("コピー内容を事前確認")
        self.plan_button.clicked.connect(self.prepare_copy)
        self.copy_button = QPushButton("確認した内容で整理コピー")
        self.copy_button.setObjectName("primary")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.start_copy)
        defaults_button = QPushButton("現在の設定を既定値に保存")
        defaults_button.clicked.connect(self.save_organizer_defaults)
        buttons.addWidget(self.plan_button)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(defaults_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.plan_table = QTableWidget(0, 5)
        self.plan_table.setHorizontalHeaderLabels(
            ["元ファイル名（変更しません）", "新しいファイル名（編集可）", "拡張子", "コピー先", "状態"]
        )
        self.plan_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.plan_table.setAlternatingRowColors(True)
        self.plan_table.setShowGrid(False)
        plan_header = self.plan_table.horizontalHeader()
        plan_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.plan_table.setColumnWidth(0, 310)
        self.plan_table.setColumnWidth(1, 280)
        self.plan_table.setColumnWidth(2, 120)
        self.plan_table.setColumnWidth(3, 520)
        self.plan_table.setColumnWidth(4, 160)
        self.plan_table.itemChanged.connect(self.on_plan_item_changed)
        self.plan_table.currentCellChanged.connect(self.update_preview_from_plan)
        layout.addWidget(self.plan_table, 1)
        self.organize_warning = QLabel(
            "安全仕様：既定では元ファイルを保持します。コピー先が対象フォルダー内の場合は実行できません。"
            "コピー結果はコピー先の _DirectoryStructureGenerator_copy_log.csv に記録します。"
        )
        self.organize_warning.setWordWrap(True)
        layout.addWidget(self.organize_warning)
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
        self.status_label.setText(f"{action} {current:,} / {total:,}: {Path(path).name}")
        self.status_label.setToolTip(path)

    @Slot(object)
    def on_worker_finished(self, result: object) -> None:
        if self._mode == "inspect":
            self.details = list(result)  # type: ignore[arg-type]
            self.detail_by_path = {detail.full_path: detail for detail in self.details}
            self.populate_table()
            errors = sum(bool(detail.error) for detail in self.details)
            images = sum(detail.is_image for detail in self.details)
            videos = sum(detail.is_video for detail in self.details)
            audios = sum(detail.is_audio for detail in self.details)
            self.status_label.setText(
                f"解析完了: 全{len(self.details):,}件 ｜ 画像{images:,}件 ｜ "
                f"動画{videos:,}件 ｜ 音声{audios:,}件 ｜ エラー{errors:,}件"
            )
        else:
            self.copy_plans = list(result)  # type: ignore[arg-type]
            self.populate_plan_table()
            copied = sum(plan.status.startswith("コピー完了") for plan in self.copy_plans)
            deleted = sum(plan.status == "コピー完了・元ファイル削除" for plan in self.copy_plans)
            failed = sum(
                plan.status in {"コピー失敗", "コピー完了・安全確認失敗"}
                for plan in self.copy_plans
            )
            delete_failed = sum(
                plan.status == "コピー完了・元ファイル削除失敗" for plan in self.copy_plans
            )
            self.status_label.setText(
                f"処理完了: コピー{copied:,}件 ｜ 元ファイル削除{deleted:,}件 ｜ "
                f"削除失敗{delete_failed:,}件 ｜ 失敗{failed:,}件"
            )
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
        self._table_populating = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.details))
        for row, detail in enumerate(self.details):
            check_item = SortableTableWidgetItem()
            check_item.setCheckState(Qt.CheckState.Unchecked)
            check_item.setData(Qt.ItemDataRole.UserRole, detail.full_path)
            check_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            self.table.setItem(row, self.CHECK_COLUMN, check_item)
            location = Path(detail.relative_path).parent.as_posix()
            if location == ".":
                location = "（対象フォルダー直下）"
            values = [
                detail.name, location,
                self.category_label(detail.category),
                detail.extension,
                format_size(detail.file_size), detail.modified, detail.created,
                "" if detail.line_count is None else f"{detail.line_count:,}",
                detail.permissions, "はい" if detail.readonly else "いいえ", detail.media_format,
                detail.resolution, detail.duration, detail.frame_rate, detail.video_codec,
                detail.audio_codec, detail.bit_rate, detail.audio_channels, detail.aspect_ratio,
                detail.color_mode, detail.exif_datetime, detail.camera, detail.gps,
                detail.sha256, detail.error,
            ]
            for column, value in enumerate(values, start=1):
                item = SortableTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, detail.full_path)
                item.setData(SORT_ROLE, self.sort_value_for_column(detail, column, str(value)))
                item.setToolTip(detail.relative_path if column in {1, 2} else str(value))
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        self._table_populating = False
        self.csv_button.setEnabled(bool(self.details))
        self.json_button.setEnabled(bool(self.details))
        self.apply_filter()

    @staticmethod
    def category_label(category: str) -> str:
        return {
            "image": "画像", "video": "動画", "audio": "音声",
            "document": "文書", "other": "その他",
        }.get(category, "その他")

    def select_all_filter_categories(self) -> None:
        self.all_filter_button.setChecked(True)
        for button in self.filter_buttons.values():
            button.blockSignals(True)
            button.setChecked(False)
            button.blockSignals(False)
        self.commit_category_filter()

    def on_filter_chip_toggled(self, checked: bool) -> None:
        if checked:
            self.all_filter_button.blockSignals(True)
            self.all_filter_button.setChecked(False)
            self.all_filter_button.blockSignals(False)
        elif not any(button.isChecked() for button in self.filter_buttons.values()):
            self.all_filter_button.blockSignals(True)
            self.all_filter_button.setChecked(True)
            self.all_filter_button.blockSignals(False)

    def commit_category_filter(self) -> None:
        self._applied_categories = {
            key for key, button in self.filter_buttons.items() if button.isChecked()
        }
        self.apply_filter()

    def clear_filters(self) -> None:
        self.column_filter_combo.blockSignals(True)
        self.column_filter_combo.setCurrentIndex(0)
        self.column_filter_combo.blockSignals(False)
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self.select_all_filter_categories()

    def _matches_search(self, row: int, search: str) -> bool:
        if not search:
            return True
        selected_column = int(self.column_filter_combo.currentData())
        columns = (
            range(1, self.table.columnCount())
            if selected_column < 0 else (selected_column,)
        )
        return any(
            search in item.text().casefold()
            for column in columns
            if (item := self.table.item(row, column)) is not None
        )

    def update_filter_counts(self, search: str) -> None:
        counts = {key: 0 for key, _label in self.FILTER_CATEGORIES}
        total = 0
        for row in range(self.table.rowCount()):
            if not self._matches_search(row, search):
                continue
            total += 1
            item = self.table.item(row, self.CHECK_COLUMN)
            detail = self.detail_by_path.get(str(item.data(Qt.ItemDataRole.UserRole))) if item else None
            if detail and detail.category in counts:
                counts[detail.category] += 1
        self.all_filter_button.setText(f"すべて {total:,}")
        for key, label in self.FILTER_CATEGORIES:
            button = self.filter_buttons[key]
            button.setText(f"{label} {counts[key]:,}")
            button.setEnabled(counts[key] > 0)

    def apply_filter(self, *_args) -> None:  # type: ignore[no-untyped-def]
        if not hasattr(self, "table"):
            return
        search = self.search_edit.text().casefold()
        selected_column = int(self.column_filter_combo.currentData())
        signature = (search, selected_column, tuple(sorted(self._applied_categories)))
        if self._last_filter_signature is not None and signature != self._last_filter_signature:
            self.reset_checked_selection()
        self._last_filter_signature = signature
        self.update_filter_counts(search)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.CHECK_COLUMN)
            detail = self.detail_by_path.get(str(item.data(Qt.ItemDataRole.UserRole))) if item else None
            visible = self._matches_search(row, search)
            if self._applied_categories:
                visible = visible and bool(detail and detail.category in self._applied_categories)
            self.table.setRowHidden(row, not visible)
        self.update_selection_state()

    @staticmethod
    def sort_value_for_column(detail: FileDetail, column: int, display: str) -> int | float | str:
        """Return a natural sort key for numeric/date/text table columns."""
        numeric_values: dict[int, int | float] = {
            FileManagerDialog.SIZE_COLUMN: detail.file_size,
            FileManagerDialog.LINE_COUNT_COLUMN: detail.line_count if detail.line_count is not None else -1,
            FileManagerDialog.RESOLUTION_COLUMN: (detail.width or 0) * (detail.height or 0),
            FileManagerDialog.DURATION_COLUMN: detail.duration_seconds or 0.0,
        }
        if column in numeric_values:
            return numeric_values[column]
        if column == FileManagerDialog.FPS_COLUMN:
            try:
                return float(detail.frame_rate.casefold().replace("fps", "").strip() or 0)
            except ValueError:
                return 0.0
        return display.casefold()

    def show_header_context_menu(self, position) -> None:  # type: ignore[no-untyped-def]
        header = self.table.horizontalHeader()
        column = header.logicalIndexAt(position)
        if column <= self.CHECK_COLUMN:
            return
        menu = QMenu(self)
        ascending = menu.addAction(f"「{self.HEADERS[column]}」を昇順に並べ替え")
        descending = menu.addAction(f"「{self.HEADERS[column]}」を降順に並べ替え")
        menu.addSeparator()
        filter_action = menu.addAction(f"「{self.HEADERS[column]}」を絞り込み…")
        clear_action = menu.addAction("絞り込み条件をクリア")
        menu.addSeparator()
        fit_action = menu.addAction("この列の幅を内容に合わせる")
        fit_all_action = menu.addAction("すべての列幅を内容に合わせる")
        chosen = menu.exec(header.mapToGlobal(position))
        if chosen == ascending:
            self.table.sortItems(column, Qt.SortOrder.AscendingOrder)
        elif chosen == descending:
            self.table.sortItems(column, Qt.SortOrder.DescendingOrder)
        elif chosen == filter_action:
            self.prompt_column_filter(column)
        elif chosen == clear_action:
            self.clear_filters()
        elif chosen == fit_action:
            self.table.resizeColumnToContents(column)
        elif chosen == fit_all_action:
            self.table.resizeColumnsToContents()
            self.table.setColumnWidth(self.CHECK_COLUMN, 54)

    def prompt_column_filter(self, column: int) -> None:
        text, accepted = QInputDialog.getText(
            self,
            "列の絞り込み",
            f"「{self.HEADERS[column]}」に含まれる文字を入力してください。",
            QLineEdit.EchoMode.Normal,
            self.search_edit.text(),
        )
        if not accepted:
            return
        combo_index = self.column_filter_combo.findData(column)
        self.column_filter_combo.setCurrentIndex(max(combo_index, 0))
        self.search_edit.setText(text)
        self.search_edit.setFocus()

    def _context_rows(self) -> list[int]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if rows:
            return rows
        current = self.table.currentRow()
        return [current] if current >= 0 else []

    def show_table_context_menu(self, position) -> None:  # type: ignore[no-untyped-def]
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        selected_rows = {item.row() for item in self.table.selectionModel().selectedRows()}
        if index.row() not in selected_rows:
            self.table.clearSelection()
            self.table.selectRow(index.row())
        current_index = self.table.model().index(
            index.row(), max(index.column(), self.NAME_COLUMN)
        )
        self.table.selectionModel().setCurrentIndex(
            current_index, QItemSelectionModel.SelectionFlag.NoUpdate
        )

        menu = QMenu(self)
        open_action = menu.addAction("ファイルを開く")
        folder_action = menu.addAction("保存場所を開く")
        preview_action = menu.addAction("プレビューを表示")
        menu.addSeparator()
        check_action = menu.addAction("整理コピー対象に追加")
        uncheck_action = menu.addAction("整理コピー対象から外す")
        organize_action = menu.addAction("整理コピーで名前を変更…")
        menu.addSeparator()
        copy_menu = menu.addMenu("クリップボードへコピー")
        copy_path_action = copy_menu.addAction("フルパス")
        copy_name_action = copy_menu.addAction("ファイル名")
        copy_folder_action = copy_menu.addAction("保存場所")
        properties_action = menu.addAction("ファイル情報を表示")

        chosen = menu.exec(self.table.viewport().mapToGlobal(position))
        if chosen == open_action:
            self.open_selected_file()
        elif chosen == folder_action:
            self.open_selected_folder()
        elif chosen == preview_action:
            self.update_preview(False)
        elif chosen == check_action:
            self.set_context_rows_checked(True)
        elif chosen == uncheck_action:
            self.set_context_rows_checked(False)
        elif chosen == organize_action:
            self.set_context_rows_checked(True)
            self.tabs.setCurrentIndex(1)
        elif chosen == copy_path_action:
            self.copy_context_value("path")
        elif chosen == copy_name_action:
            self.copy_context_value("name")
        elif chosen == copy_folder_action:
            self.copy_context_value("folder")
        elif chosen == properties_action:
            self.show_selected_file_info()

    def set_context_rows_checked(self, checked: bool) -> None:
        self._table_populating = True
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in self._context_rows():
            item = self.table.item(row, self.CHECK_COLUMN)
            if item:
                item.setCheckState(state)
        self._table_populating = False
        self.update_selection_state()
        self.update_preview()

    def copy_context_value(self, kind: str) -> None:
        values: list[str] = []
        for row in self._context_rows():
            item = self.table.item(row, self.NAME_COLUMN)
            detail = self.detail_by_path.get(str(item.data(Qt.ItemDataRole.UserRole))) if item else None
            if not detail:
                continue
            path = Path(detail.full_path)
            values.append(
                detail.name if kind == "name" else str(path.parent) if kind == "folder" else str(path)
            )
        if values:
            QApplication.clipboard().setText("\n".join(values))
            self.status_label.setText(f"{len(values):,}件をクリップボードへコピーしました")

    def show_selected_file_info(self) -> None:
        detail = self.focused_detail()
        if not detail:
            return
        lines = [
            f"ファイル名: {detail.name}",
            f"保存場所: {Path(detail.full_path).parent}",
            f"区分: {self.category_label(detail.category)}",
            f"サイズ: {format_size(detail.file_size)} ({detail.file_size:,} bytes)",
            f"更新日時: {detail.modified or '不明'}",
            f"作成日時: {detail.created or '不明'}",
            f"読取専用: {'はい' if detail.readonly else 'いいえ'}",
        ]
        if detail.resolution:
            lines.append(f"解像度: {detail.resolution}")
        QMessageBox.information(self, "ファイル情報", "\n".join(lines))

    def reset_checked_selection(self) -> None:
        if not hasattr(self, "table"):
            return
        self._table_populating = True
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.CHECK_COLUMN)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)
        self._table_populating = False
        self.table.clearSelection()
        self.invalidate_copy_plan()

    def visible_rows(self) -> list[int]:
        return [row for row in range(self.table.rowCount()) if not self.table.isRowHidden(row)]

    def checked_count(self) -> int:
        return sum(
            bool(
                (item := self.table.item(row, self.CHECK_COLUMN))
                and item.checkState() == Qt.CheckState.Checked
            )
            for row in range(self.table.rowCount())
        )

    def update_selection_state(self) -> None:
        visible = self.visible_rows()
        visible_checked = sum(
            bool(
                (item := self.table.item(row, self.CHECK_COLUMN))
                and item.checkState() == Qt.CheckState.Checked
            )
            for row in visible
        )
        if not visible or visible_checked == 0:
            state = Qt.CheckState.Unchecked
        elif visible_checked == len(visible):
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.PartiallyChecked
        header = self.table.horizontalHeader()
        if isinstance(header, CheckableHeaderView):
            header.setCheckState(state)
        total_checked = self.checked_count()
        self.selection_count_label.setText(
            f"選択中 {total_checked:,}件 ／ 表示中 {len(visible):,}件"
        )
        self.selection_label.setText(f"選択中: {total_checked:,}件")

    @Slot(int)
    def set_header_check_state(self, state_value: int) -> None:
        state = Qt.CheckState(state_value)
        self.set_visible_checks("all" if state == Qt.CheckState.Checked else "none")

    def set_visible_checks(self, mode: str) -> None:
        self._table_populating = True
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            item = self.table.item(row, self.CHECK_COLUMN)
            if not item:
                continue
            checked = item.checkState() == Qt.CheckState.Checked
            new_checked = not checked if mode == "invert" else mode == "all"
            item.setCheckState(Qt.CheckState.Checked if new_checked else Qt.CheckState.Unchecked)
        self._table_populating = False
        self.update_selection_state()
        self.update_preview()

    def on_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._table_populating or item.column() != self.CHECK_COLUMN:
            return
        self.update_selection_state()
        self.update_preview()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.table.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            mouse_event = event
            if isinstance(mouse_event, QMouseEvent):
                index = self.table.indexAt(mouse_event.position().toPoint())
                if index.isValid() and index.column() == self.CHECK_COLUMN:
                    if (
                        mouse_event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                        and self._last_check_row is not None
                    ):
                        clicked = self.table.item(index.row(), self.CHECK_COLUMN)
                        target = (
                            Qt.CheckState.Unchecked
                            if clicked and clicked.checkState() == Qt.CheckState.Checked
                            else Qt.CheckState.Checked
                        )
                        first, last = sorted((self._last_check_row, index.row()))
                        self._table_populating = True
                        for row in range(first, last + 1):
                            if self.table.isRowHidden(row):
                                continue
                            item = self.table.item(row, self.CHECK_COLUMN)
                            if item:
                                item.setCheckState(target)
                        self._table_populating = False
                        self.table.setCurrentCell(index.row(), self.NAME_COLUMN)
                        self.update_selection_state()
                        self.update_preview()
                        return True
                    self._last_check_row = index.row()
        return super().eventFilter(watched, event)

    def selected_details(self) -> list[FileDetail]:
        selected: list[FileDetail] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.CHECK_COLUMN)
            if item and item.checkState() == Qt.CheckState.Checked:
                detail = self.detail_by_path.get(str(item.data(Qt.ItemDataRole.UserRole)))
                if detail:
                    selected.append(detail)
        return selected

    def focused_detail(self) -> FileDetail | None:
        row = self.table.currentRow()
        item = self.table.item(row, self.NAME_COLUMN) if row >= 0 else None
        if item:
            detail = self.detail_by_path.get(str(item.data(Qt.ItemDataRole.UserRole)))
            if detail:
                return detail
        selected = self.selected_details()
        return selected[0] if selected else None

    def update_preview(self, invalidate_plan: bool = True) -> None:
        if invalidate_plan and not self._preview_from_plan:
            self.invalidate_copy_plan()
        selected = self.selected_details()
        self.selection_label.setText(f"選択中: {len(selected):,}件")
        detail = self.focused_detail()
        if not detail:
            self.media_player.stop()
            self.preview_stack.setCurrentWidget(self.preview_placeholder)
            self.media_controls_widget.setVisible(False)
            self.selected_info.setText("未選択")
            return
        media_lines = []
        if detail.resolution:
            media_lines.append(detail.resolution)
        if detail.duration:
            media_lines.append(f"再生時間 {detail.duration}")
        if detail.frame_rate:
            media_lines.append(detail.frame_rate)
        if detail.video_codec:
            media_lines.append(f"映像 {detail.video_codec}")
        if detail.audio_codec:
            media_lines.append(f"音声 {detail.audio_codec}")
        self.selected_info.setText(
            f"{detail.name}\n{detail.relative_path}\n{format_size(detail.file_size)}"
            + ("\n" + " / ".join(media_lines) if media_lines else "")
        )
        if detail.is_image:
            self.media_player.stop()
            self.media_controls_widget.setVisible(False)
            pixmap = self.load_image_preview(Path(detail.full_path))
            if pixmap and not pixmap.isNull():
                size = self.preview_stack.contentsRect().size()
                width = max(240, size.width() - 16)
                height = max(200, size.height() - 16)
                self.thumbnail.setPixmap(
                    pixmap.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
                )
                self.preview_stack.setCurrentWidget(self.thumbnail)
            else:
                self.preview_placeholder.setText("画像を表示できません")
                self.preview_stack.setCurrentWidget(self.preview_placeholder)
        elif detail.is_video or detail.is_audio:
            source = QUrl.fromLocalFile(detail.full_path)
            if self.media_player.source() != source:
                self.media_player.stop()
                self.media_player.setSource(source)
            if detail.is_video:
                self.preview_stack.setCurrentWidget(self.video_widget)
            else:
                self.preview_placeholder.setText(
                    f"音声ファイル\n{detail.media_format or detail.extension.upper()}\n"
                    "下の再生ボタンで確認できます"
                )
                self.preview_stack.setCurrentWidget(self.preview_placeholder)
            self.media_controls_widget.setVisible(True)
        else:
            self.media_player.stop()
            self.media_controls_widget.setVisible(False)
            self.preview_placeholder.setText(
                "このファイルはプレビュー対象外です\nサイズ・日時などの情報を確認できます"
            )
            self.preview_stack.setCurrentWidget(self.preview_placeholder)

    @staticmethod
    def load_image_preview(path: Path) -> QPixmap | None:
        if path.suffix.casefold() == ".svg":
            pixmap = QPixmap(str(path))
            return pixmap if not pixmap.isNull() else None
        try:
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image).convert("RGBA")
                image.thumbnail((1200, 900))
                data = image.tobytes("raw", "RGBA")
                qimage = QImage(
                    data, image.width, image.height, image.width * 4,
                    QImage.Format.Format_RGBA8888,
                ).copy()
            return QPixmap.fromImage(qimage)
        except (OSError, ValueError, UnidentifiedImageError):
            return None

    @staticmethod
    def format_media_time(milliseconds: int) -> str:
        total_seconds = max(0, milliseconds // 1000)
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

    def on_media_position(self, position: int) -> None:
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(position)
        self.media_time.setText(
            f"{self.format_media_time(position)} / {self.format_media_time(self.media_duration)}"
        )

    def on_media_duration(self, duration: int) -> None:
        self.media_duration = duration
        self.seek_slider.setRange(0, max(duration, 0))
        self.on_media_position(self.media_player.position())

    def on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play_button.setText(
            "⏸ 一時停止" if state == QMediaPlayer.PlaybackState.PlayingState else "▶ 再生"
        )

    def on_media_error(self, _error, error_text: str) -> None:  # type: ignore[no-untyped-def]
        if error_text:
            self.selected_info.setText(self.selected_info.text() + f"\n再生できません: {error_text}")

    def on_media_metadata_changed(self) -> None:
        detail = self.focused_detail()
        if not detail or not (detail.is_video or detail.is_audio):
            return
        metadata = self.media_player.metaData()

        def text(key_name: str) -> str:
            key = getattr(QMediaMetaData.Key, key_name, None)
            return metadata.stringValue(key) if key is not None else ""

        if detail.is_video:
            frame_rate_key = getattr(QMediaMetaData.Key, "VideoFrameRate", None)
            frame_rate = metadata.value(frame_rate_key) if frame_rate_key is not None else None
            if frame_rate:
                detail.frame_rate = f"{float(frame_rate):.3g} fps"
            detail.video_codec = text("VideoCodec") or detail.video_codec
        detail.audio_codec = text("AudioCodec") or detail.audio_codec
        channels = text("AudioChannelCount")
        detail.audio_channels = channels or detail.audio_channels
        video_bitrate = text("VideoBitRate")
        audio_bitrate = text("AudioBitRate")
        if video_bitrate or audio_bitrate:
            detail.bit_rate = " / ".join(part for part in (video_bitrate, audio_bitrate) if part)
        row = self.table.currentRow()
        if row >= 0:
            updates = {
                14: detail.frame_rate, 15: detail.video_codec, 16: detail.audio_codec,
                17: detail.bit_rate, 18: detail.audio_channels,
            }
            self._table_populating = True
            for column, value in updates.items():
                item = self.table.item(row, column)
                if item:
                    item.setText(value)
                    item.setData(SORT_ROLE, self.sort_value_for_column(detail, column, value))
            self._table_populating = False

    def toggle_video(self) -> None:
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()

    def _selected_path(self) -> Path | None:
        detail = self.focused_detail()
        return Path(detail.full_path) if detail else None

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
            self.refresh_rename_table(preserve=True)

    def update_preview_from_plan(self, *_args) -> None:  # type: ignore[no-untyped-def]
        """Keep the shared preview in sync with the selected organize-plan row."""
        row = self.plan_table.currentRow()
        source_item = self.plan_table.item(row, 0) if row >= 0 else None
        source_path = str(source_item.data(Qt.ItemDataRole.UserRole)) if source_item else ""
        if not source_path:
            return
        for detail_row in range(self.table.rowCount()):
            item = self.table.item(detail_row, self.NAME_COLUMN)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) == source_path:
                self._preview_from_plan = True
                try:
                    self.table.setCurrentCell(detail_row, self.NAME_COLUMN)
                    self.update_preview(False)
                finally:
                    self._preview_from_plan = False
                break

    def choose_destination(self) -> None:
        initial = self.destination_combo.currentText().strip() or str(self.output)
        selected = QFileDialog.getExistingDirectory(self, "整理コピー先を選択", initial)
        if selected:
            self.destination_combo.setCurrentText(selected)

    def create_destination_folder(self) -> None:
        current = Path(self.destination_combo.currentText().strip() or self.output).expanduser()
        initial = current if current.is_dir() else current.parent
        parent = QFileDialog.getExistingDirectory(self, "保存フォルダーを作る場所", str(initial))
        if not parent:
            return
        name, accepted = QInputDialog.getText(self, "新しい保存フォルダー", "フォルダー名")
        if not accepted or not name.strip():
            return
        safe_name = sanitize_filename(name.strip())
        destination = (Path(parent) / safe_name).resolve()
        source = self.source.resolve()
        if destination == source or destination.is_relative_to(source):
            QMessageBox.warning(self, "安全確認", "対象フォルダーの内側には保存フォルダーを作成できません。")
            return
        try:
            destination.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            QMessageBox.information(self, "確認", "同じ名前のフォルダーがすでにあります。")
            return
        except OSError as exc:
            QMessageBox.critical(self, "作成エラー", str(exc))
            return
        self.destination_combo.setCurrentText(str(destination))
        self.status_label.setText(f"保存フォルダーを作成しました: {destination}")

    def current_naming_template(self) -> str:
        value = str(self.naming_combo.currentData())
        if value == "__custom__":
            return self.custom_template.text().strip() or "{name}"
        if value == "__individual__":
            return "{name}"
        return value or "{name}"

    def on_naming_mode_changed(self, *_args) -> None:  # type: ignore[no-untyped-def]
        is_custom = self.naming_combo.currentData() == "__custom__"
        self.custom_template.setVisible(is_custom)
        if hasattr(self, "plan_table"):
            self.refresh_rename_table(preserve=False)

    def suggested_copy_name(self, detail: FileDetail, index: int) -> str:
        return rendered_name(detail, self.current_naming_template(), index)

    def refresh_rename_table(self, preserve: bool) -> None:
        previous: dict[str, str] = {}
        if preserve and hasattr(self, "plan_table"):
            for row in range(self.plan_table.rowCount()):
                source_item = self.plan_table.item(row, 0)
                name_item = self.plan_table.item(row, 1)
                extension = self.plan_table.cellWidget(row, 2)
                if source_item and name_item and isinstance(extension, QComboBox):
                    previous[str(source_item.data(Qt.ItemDataRole.UserRole))] = (
                        name_item.text() + self.normalized_extension(extension.currentText())
                    )
        details = self.selected_details()
        self.selection_label.setText(
            f"選択中: {len(details):,}件　｜　新しいファイル名は表の2列目をダブルクリックして変更できます。"
        )
        self.plan_table.blockSignals(True)
        self.plan_table.setRowCount(len(details))
        for row, detail in enumerate(details):
            original = QTableWidgetItem(detail.name)
            original.setData(Qt.ItemDataRole.UserRole, detail.full_path)
            original.setToolTip(detail.relative_path)
            original.setFlags(original.flags() & ~Qt.ItemFlag.ItemIsEditable)
            new_name = previous.get(detail.full_path) or self.suggested_copy_name(detail, row + 1)
            new_path = Path(new_name)
            extension_text = new_path.suffix
            stem_text = new_name[:-len(extension_text)] if extension_text else new_name
            renamed = QTableWidgetItem(stem_text)
            renamed.setToolTip("拡張子を除いたファイル名を入力します")
            extension = QComboBox()
            extension.setEditable(True)
            extension.setToolTip("候補から選ぶか、先頭に . を付けて入力します")
            extension.addItems(self.extension_candidates(extension_text))
            if not extension_text:
                extension.insertItem(0, "")
            extension.setCurrentText(extension_text)
            self.connect_extension_combo(extension)
            destination = QTableWidgetItem("事前確認後に表示")
            status = QTableWidgetItem("未確認")
            destination.setFlags(destination.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status.setFlags(status.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.plan_table.setItem(row, 0, original)
            self.plan_table.setItem(row, 1, renamed)
            self.plan_table.setCellWidget(row, 2, extension)
            self.plan_table.setItem(row, 3, destination)
            self.plan_table.setItem(row, 4, status)
        self.plan_table.blockSignals(False)
        self.invalidate_copy_plan()

    def on_plan_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 1:
            return
        self.invalidate_copy_plan()
        status = self.plan_table.item(item.row(), 4)
        if status:
            status.setText("再確認が必要")

    @staticmethod
    def normalized_extension(value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        return value if value.startswith(".") else "." + value

    def extension_candidates(self, current: str = "") -> list[str]:
        values = [current, *self.custom_extensions, *self.COMMON_EXTENSIONS]
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = self.normalized_extension(value)
            key = normalized.casefold()
            if normalized and key not in seen:
                seen.add(key)
                result.append(normalized)
        return result

    def connect_extension_combo(self, combo: QComboBox) -> None:
        combo.currentTextChanged.connect(self.invalidate_copy_plan)
        line_edit = combo.lineEdit()
        if line_edit:
            line_edit.editingFinished.connect(lambda combo=combo: self.register_extension(combo))

    def register_extension(self, combo: QComboBox) -> None:
        normalized = self.normalized_extension(combo.currentText())
        if not normalized:
            return
        combo.setCurrentText(normalized)
        if all(value.casefold() != normalized.casefold() for value in self.custom_extensions):
            self.custom_extensions.append(normalized)
            self.organizer_settings["custom_extensions"] = list(self.custom_extensions)
        for row in range(self.plan_table.rowCount()):
            row_combo = self.plan_table.cellWidget(row, 2)
            if isinstance(row_combo, QComboBox) and row_combo.findText(
                normalized, Qt.MatchFlag.MatchFixedString
            ) < 0:
                row_combo.addItem(normalized)
        self.invalidate_copy_plan()

    def on_source_action_changed(self, *_args) -> None:  # type: ignore[no-untyped-def]
        delete_sources = bool(self.source_action_combo.currentData())
        if delete_sources:
            self.source_action_warning.setText(
                "注意：コピーが成功し、コピー元とコピー先のサイズが一致したファイルだけ、"
                "元ファイルを削除します。実行時にもう一度確認します。"
            )
            self.source_action_warning.setStyleSheet("color:#dc2626;font-weight:700")
            self.copy_button.setText("確認した内容でコピー後に元ファイルを削除")
        else:
            self.source_action_warning.setText(
                "元ファイルは保持されます。コピー側だけを整理・リネームします。"
            )
            self.source_action_warning.setStyleSheet("")
            self.copy_button.setText("確認した内容で整理コピー")
        self.invalidate_copy_plan()

    def save_organizer_defaults(self) -> None:
        self.organizer_settings = {
            "default_destination": self.destination_combo.currentText().strip(),
            "naming_template": str(self.naming_combo.currentData()),
            "custom_template": self.custom_template.text().strip(),
            "keep_subfolders": self.keep_subfolders.isChecked(),
            "collision": str(self.collision_combo.currentData()),
            "custom_extensions": list(self.custom_extensions),
        }
        self.status_label.setText("現在の整理コピー設定を既定値として保存しました。")

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
        if self.plan_table.rowCount() != len(details):
            self.refresh_rename_table(preserve=True)
        overrides: dict[str, str] = {}
        for row in range(self.plan_table.rowCount()):
            source_item = self.plan_table.item(row, 0)
            name_item = self.plan_table.item(row, 1)
            extension = self.plan_table.cellWidget(row, 2)
            if source_item and name_item and isinstance(extension, QComboBox):
                overrides[str(source_item.data(Qt.ItemDataRole.UserRole))] = (
                    name_item.text().strip() + self.normalized_extension(extension.currentText())
                )
        if any(not value for value in overrides.values()):
            QMessageBox.warning(self, "確認", "新しいファイル名が空欄の行があります。")
            return
        try:
            self.copy_plans = build_copy_plans(
                details, destination, self.current_naming_template(),
                self.keep_subfolders.isChecked(), str(self.collision_combo.currentData()),
                name_overrides=overrides,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "命名ルール", str(exc))
            return
        extension_changes = [
            plan for plan in self.copy_plans
            if plan.status == "コピー予定" and extension_was_changed(plan)
        ]
        if extension_changes:
            examples = "\n".join(
                f"・{plan.source.name} → {plan.destination.name}"
                for plan in extension_changes[:5]
            )
            more = (
                f"\nほか {len(extension_changes) - 5:,}件" if len(extension_changes) > 5 else ""
            )
            answer = QMessageBox.warning(
                self, "拡張子の変更を確認",
                f"拡張子が変わる計画が {len(extension_changes):,}件あります。\n"
                "拡張子名だけが変わり、ファイル内容の形式は変換されません。\n\n"
                f"{examples}{more}\n\nこの内容で計画を作成しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.copy_plans = []
                self.copy_ready = False
                return
        self.populate_plan_table()
        self.copy_ready = bool(self.copy_plans)
        self.copy_button.setEnabled(self.copy_ready)
        self.status_label.setText("コピー内容を確認してください。まだコピーは実行していません。")

    def populate_plan_table(self) -> None:
        self.plan_table.blockSignals(True)
        self.plan_table.setRowCount(len(self.copy_plans))
        for row, plan in enumerate(self.copy_plans):
            original = QTableWidgetItem(Path(plan.relative_path).name)
            original.setData(Qt.ItemDataRole.UserRole, str(plan.source))
            original.setToolTip(plan.relative_path)
            destination_name = plan.destination.name
            extension_text = Path(destination_name).suffix
            stem_text = destination_name[:-len(extension_text)] if extension_text else destination_name
            new_name = QTableWidgetItem(stem_text)
            extension = QComboBox()
            extension.setEditable(True)
            extension.addItems(self.extension_candidates(extension_text))
            if not extension_text:
                extension.insertItem(0, "")
            extension.setCurrentText(extension_text)
            self.connect_extension_combo(extension)
            destination = QTableWidgetItem(str(plan.destination))
            status = QTableWidgetItem(plan.status)
            for item in (original, destination, status):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.plan_table.setItem(row, 0, original)
            self.plan_table.setItem(row, 1, new_name)
            self.plan_table.setCellWidget(row, 2, extension)
            self.plan_table.setItem(row, 3, destination)
            self.plan_table.setItem(row, 4, status)
        self.plan_table.blockSignals(False)

    def start_copy(self) -> None:
        if not self.copy_plans or not self.copy_ready:
            return
        count = len(self.copy_plans)
        warning = (
            "\n\n大量のファイルが選択されています。件数とコピー先をもう一度確認してください。"
            if count >= 100 else ""
        )
        delete_sources = bool(self.source_action_combo.currentData())
        if delete_sources:
            title = "最終確認：元ファイルを削除します"
            message = (
                f"{count:,}件の計画を実行します。\n\n"
                "コピー成功後、コピー元とコピー先のサイズが一致した元ファイルを削除します。\n"
                "この削除は元に戻せません。スキップ・コピー失敗・確認失敗の元ファイルは削除しません。"
                f"{warning}\n\n本当に実行しますか？"
            )
        else:
            title = "整理コピーの実行"
            message = (
                f"{count:,}件の計画を実行します。\n元ファイルは保持されます。"
                f"{warning}\n\n実行しますか？"
            )
        answer = QMessageBox.question(
            self, title, message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        destination = Path(self.destination_combo.currentText().strip()).expanduser().resolve()
        self.copy_ready = False
        self._start_worker(
            CopyWorker(self.copy_plans, destination, delete_sources=delete_sources), "copy"
        )

    def invalidate_copy_plan(self, *_args) -> None:  # type: ignore[no-untyped-def]
        self.copy_ready = False
        if hasattr(self, "copy_button"):
            self.copy_button.setEnabled(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, "処理中", "処理を中止してから閉じてください。")
            event.ignore()
            return
        self.media_player.stop()
        event.accept()


class OrganizerSettingsDialog(QDialog):
    """Edit organizer defaults without requiring a source scan."""

    def __init__(
        self, settings: dict[str, object], destination_history: list[str], parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("整理コピーの既定設定")
        self.resize(720, 340)
        layout = QVBoxLayout(self)
        title = QLabel("整理コピーの既定設定")
        title.setStyleSheet("font-size:16pt;font-weight:700")
        layout.addWidget(title)
        help_label = QLabel(
            "ここでよく使う設定を決められます。実際の整理コピー画面では、毎回変更できます。"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        form = QFormLayout()
        destination_row = QHBoxLayout()
        self.destination = FolderDropComboBox()
        self.destination.setEditable(True)
        self.destination.addItems(destination_history)
        self.destination.setCurrentText(str(settings.get("default_destination", "")))
        browse = QPushButton("参照…")
        browse.clicked.connect(self.choose_destination)
        destination_row.addWidget(self.destination, 1)
        destination_row.addWidget(browse)
        form.addRow("既定のコピー先", destination_row)
        self.naming = QComboBox()
        for label, template in FileManagerDialog.NAMING_PRESETS:
            self.naming.addItem(label, template)
        index = self.naming.findData(str(settings.get("naming_template", "{name}")))
        self.naming.setCurrentIndex(max(index, 0))
        self.naming.currentIndexChanged.connect(self.update_custom_visibility)
        form.addRow("名前の付け方", self.naming)
        self.custom = QLineEdit(str(settings.get("custom_template", "{name}")))
        form.addRow("高度な命名ルール", self.custom)
        self.keep_subfolders = QCheckBox("元のサブフォルダー構成を維持する")
        self.keep_subfolders.setChecked(bool(settings.get("keep_subfolders", True)))
        form.addRow("", self.keep_subfolders)
        self.collision = QComboBox()
        self.collision.addItem("自動で連番を付ける（推奨）", "number")
        self.collision.addItem("同名ファイルはスキップ", "skip")
        collision_index = self.collision.findData(str(settings.get("collision", "number")))
        self.collision.setCurrentIndex(max(collision_index, 0))
        form.addRow("同名ファイル", self.collision)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.update_custom_visibility()

    def choose_destination(self) -> None:
        initial = self.destination.currentText().strip()
        selected = QFileDialog.getExistingDirectory(self, "既定のコピー先", initial)
        if selected:
            self.destination.setCurrentText(selected)

    def update_custom_visibility(self, *_args) -> None:  # type: ignore[no-untyped-def]
        self.custom.setVisible(self.naming.currentData() == "__custom__")

    def values(self) -> dict[str, object]:
        return {
            "default_destination": self.destination.currentText().strip(),
            "naming_template": str(self.naming.currentData()),
            "custom_template": self.custom.text().strip(),
            "keep_subfolders": self.keep_subfolders.isChecked(),
            "collision": str(self.collision.currentData()),
        }
