"""Modern PySide6 user interface.

Version: 2.0.2
Updated: 2026-09-20
Author: hiro1960
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence, QTextCursor
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSpinBox, QSplitter, QStatusBar, QTextBrowser, QTextEdit, QToolBar, QVBoxLayout, QWidget,
)

from .config_manager import add_history, load_config, save_config
from .exporters import export_selected, format_size, tree_lines
from .models import FilterSettings, PRESETS, ScanResult
from .scanner import DirectoryScanner, ScanCancelled
from .version import APP_NAME, APP_VERSION, AUTHOR, UPDATED


DARK_STYLE = """
QWidget { background:#101827; color:#e8eef9; font-family:'Segoe UI'; font-size:10pt; }
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget { background:#101827; }
QFrame#hero { background:#17243a; border:1px solid #263a59; border-radius:16px; }
QGroupBox { border:1px solid #2b3c56; border-radius:12px; margin-top:12px; padding-top:14px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 6px; color:#8db8ff; }
QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser, QSpinBox { background:#0d1421; border:1px solid #344966; border-radius:8px; padding:7px; selection-background-color:#2563eb; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus { border:1px solid #60a5fa; }
QPushButton { background:#263750; border:1px solid #385173; border-radius:8px; padding:8px 14px; font-weight:600; }
QPushButton:hover { background:#314866; } QPushButton:disabled { color:#718096; background:#1a2536; }
QPushButton#primary { background:#2563eb; border-color:#3b82f6; color:white; }
QPushButton#primary:hover { background:#1d4ed8; }
QPushButton#danger { background:#7f1d1d; border-color:#b91c1c; }
QToolBar { background:#17243a; border-bottom:1px solid #263a59; spacing:8px; padding:4px; }
QStatusBar { background:#17243a; } QProgressBar { border:1px solid #344966; border-radius:6px; text-align:center; background:#0d1421; }
QProgressBar::chunk { background:#2563eb; border-radius:5px; } QSplitter::handle { background:#263a59; }
"""

LIGHT_STYLE = """
QWidget { background:#f4f7fb; color:#172033; font-family:'Segoe UI'; font-size:10pt; }
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget { background:#f4f7fb; }
QFrame#hero { background:white; border:1px solid #dbe4f0; border-radius:16px; }
QGroupBox { border:1px solid #d5deea; border-radius:12px; margin-top:12px; padding-top:14px; font-weight:600; background:white; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 6px; color:#1d4ed8; }
QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser, QSpinBox { background:white; border:1px solid #c9d4e3; border-radius:8px; padding:7px; selection-background-color:#93c5fd; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus { border:1px solid #2563eb; }
QPushButton { background:#edf2f8; border:1px solid #c8d4e4; border-radius:8px; padding:8px 14px; font-weight:600; }
QPushButton:hover { background:#e1eaf5; } QPushButton:disabled { color:#94a3b8; }
QPushButton#primary { background:#2563eb; border-color:#2563eb; color:white; } QPushButton#primary:hover { background:#1d4ed8; }
QPushButton#danger { background:#fee2e2; border-color:#fca5a5; color:#991b1b; }
QToolBar { background:white; border-bottom:1px solid #dbe4f0; spacing:8px; padding:4px; }
QStatusBar { background:white; } QProgressBar { border:1px solid #c9d4e3; border-radius:6px; text-align:center; background:white; }
QProgressBar::chunk { background:#2563eb; border-radius:5px; } QSplitter::handle { background:#d5deea; }
"""


class ScanWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(str, int, int)

    def __init__(self, source: Path, output: Path, settings: FilterSettings) -> None:
        super().__init__()
        self.source = source
        self.output = output
        self.settings = settings
        self._cancel = False

    @Slot()
    def run(self) -> None:
        try:
            scanner = DirectoryScanner(
                self.settings, lambda: self._cancel,
                lambda path, stats: self.progress.emit(path, stats.folders, stats.files),
                excluded_absolute_paths=[self.output],
            )
            self.finished.emit(scanner.scan(self.source))
        except ScanCancelled:
            self.cancelled.emit()
        except Exception as exc:  # GUI boundary: display all operational errors
            self.failed.emit(str(exc))

    @Slot()
    def cancel(self) -> None:
        self._cancel = True


class PathDropEdit(QComboBox):
    pathDropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setEditable(True)
        self.setAcceptDrops(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasUrls() and event.mimeData().urls()[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        path = event.mimeData().urls()[0].toLocalFile()
        if Path(path).is_dir():
            self.setCurrentText(path)
            self.pathDropped.emit(path)
            event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.result: ScanResult | None = None
        self.thread: QThread | None = None
        self.worker: ScanWorker | None = None
        self._generate_after_scan = False
        self.setWindowTitle(f"{APP_NAME}  Ver.{APP_VERSION}")
        self.setAcceptDrops(True)
        self.resize(int(self.config["window"]["width"]), int(self.config["window"]["height"]))
        self.setMinimumSize(980, 680)
        self._build_ui()
        self._load_config_into_ui()
        self.apply_theme(str(self.config.get("theme", "dark")))
        QTimer.singleShot(0, self._clear_initial_text_selections)

    def _build_ui(self) -> None:
        toolbar = QToolBar("メインツールバー")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.theme_action = QAction("☀ ライト表示", self)
        self.theme_action.triggered.connect(self.toggle_theme)
        toolbar.addAction(self.theme_action)
        toolbar.addSeparator()
        about = QAction("このアプリについて", self)
        about.triggered.connect(self.show_about)
        toolbar.addAction(about)

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        hero = QFrame(objectName="hero")
        hero_layout = QHBoxLayout(hero)
        title_box = QVBoxLayout()
        title = QLabel("Directory Structure Generator")
        title.setStyleSheet("font-size:20pt;font-weight:700;background:transparent")
        subtitle = QLabel("必要なものだけを、見やすいツリーに。")
        subtitle.setStyleSheet("color:#8da2c0;background:transparent")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        hero_layout.addLayout(title_box)
        hero_layout.addStretch()
        badge = QLabel(f"Ver.{APP_VERSION}")
        badge.setStyleSheet("background:#2563eb;color:white;border-radius:12px;padding:6px 12px;font-weight:700")
        hero_layout.addWidget(badge)
        outer.addWidget(hero)

        paths = QGroupBox("1. フォルダーを選ぶ")
        grid = QGridLayout(paths)
        self.source_combo = PathDropEdit()
        self.output_combo = PathDropEdit()
        source_button = QPushButton("参照…")
        output_button = QPushButton("参照…")
        source_button.clicked.connect(self.choose_source)
        output_button.clicked.connect(self.choose_output)
        grid.addWidget(QLabel("対象フォルダー"), 0, 0)
        grid.addWidget(self.source_combo, 0, 1)
        grid.addWidget(source_button, 0, 2)
        grid.addWidget(QLabel("出力先"), 1, 0)
        grid.addWidget(self.output_combo, 1, 1)
        grid.addWidget(output_button, 1, 2)
        grid.setColumnStretch(1, 1)
        outer.addWidget(paths)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        settings_panel = QWidget()
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(0, 0, 8, 0)

        filters = QGroupBox("2. フィルター")
        filter_layout = QFormLayout(filters)
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(PRESETS.keys())
        self.preset_combo.currentTextChanged.connect(self.apply_preset)
        self.excluded_dirs = QPlainTextEdit()
        self.excluded_dirs.setPlaceholderText("1行に1つ：.git、node_modules など")
        self.excluded_dirs.setMinimumHeight(72)
        self.excluded_dirs.setMaximumHeight(82)
        self.excluded_dirs.setTabChangesFocus(True)
        self.excluded_dirs.setToolTip("除外するフォルダー名を1行に1つ入力します")
        self.excluded_exts = QLineEdit()
        self.excluded_exts.setPlaceholderText(".log, .tmp, .pyc")
        self.included_exts = QLineEdit()
        self.included_exts.setPlaceholderText("空欄ならすべて。例: .py, .md")
        self.patterns = QLineEdit()
        self.patterns.setPlaceholderText("*.egg-info, *_backup, temp/*")
        self.max_depth = QSpinBox()
        self.max_depth.setRange(-1, 999)
        self.max_depth.setSpecialValueText("制限なし")
        filter_layout.addRow("プリセット", self.preset_combo)
        filter_layout.addRow("除外フォルダー\n（1行に1つ）", self.excluded_dirs)
        filter_layout.addRow("除外拡張子", self.excluded_exts)
        filter_layout.addRow("対象拡張子", self.included_exts)
        filter_layout.addRow("除外パターン", self.patterns)
        filter_layout.addRow("最大階層", self.max_depth)
        self.hidden_check = QCheckBox("隠しファイル・フォルダーを含める")
        self.empty_check = QCheckBox("空フォルダーを含める")
        self.symlink_check = QCheckBox("リンク先をたどる（循環に注意）")
        filter_layout.addRow(self.hidden_check)
        filter_layout.addRow(self.empty_check)
        filter_layout.addRow(self.symlink_check)
        settings_layout.addWidget(filters)

        formats = QGroupBox("3. 出力形式")
        format_layout = QHBoxLayout(formats)
        self.format_checks: dict[str, QCheckBox] = {}
        for key, label in (("txt", "TXTツリー"), ("html", "HTML"), ("csv", "CSV"), ("json", "JSON")):
            checkbox = QCheckBox(label)
            self.format_checks[key] = checkbox
            format_layout.addWidget(checkbox)
        settings_layout.addWidget(formats)

        actions = QHBoxLayout()
        self.preview_button = QPushButton("プレビュー走査")
        self.preview_button.setToolTip("出力せずにフォルダー構成を確認します (Ctrl+P)")
        self.generate_button = QPushButton("構成ファイルを生成")
        self.generate_button.setObjectName("primary")
        self.generate_button.setToolTip("選択形式でファイルを作成します (Ctrl+G)")
        self.cancel_button = QPushButton("中止")
        self.cancel_button.setObjectName("danger")
        self.cancel_button.setEnabled(False)
        self.preview_button.clicked.connect(lambda: self.start_scan(False))
        self.generate_button.clicked.connect(lambda: self.start_scan(True))
        self.cancel_button.clicked.connect(self.cancel_scan)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.generate_button)
        actions.addWidget(self.cancel_button)
        settings_layout.addLayout(actions)
        settings_layout.addStretch()

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(8, 0, 0, 0)
        preview_header = QHBoxLayout()
        preview_header.addWidget(QLabel("プレビュー"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("プレビュー内を検索")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self.find_next)
        preview_header.addWidget(self.search_edit, 1)
        copy_button = QPushButton("コピー")
        copy_button.clicked.connect(self.copy_preview)
        preview_header.addWidget(copy_button)
        preview_layout.addLayout(preview_header)
        self.preview = QTextBrowser()
        self.preview.setPlaceholderText("「プレビュー走査」を押すと、ここにツリーが表示されます。")
        self.preview.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        preview_layout.addWidget(self.preview, 1)
        self.stats_label = QLabel("フォルダー 0  ｜  ファイル 0  ｜  0 B  ｜  除外 0")
        preview_layout.addWidget(self.stats_label)

        settings_scroll = QScrollArea()
        settings_scroll.setObjectName("settingsScroll")
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_scroll.setMinimumWidth(420)
        settings_scroll.setWidget(settings_panel)
        splitter.addWidget(settings_scroll)
        splitter.addWidget(preview_panel)
        splitter.setSizes([470, 710])
        outer.addWidget(splitter, 1)

        progress_row = QHBoxLayout()
        self.progress_label = QLabel("準備完了")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.open_output_button = QPushButton("出力先を開く")
        self.open_output_button.clicked.connect(self.open_output)
        progress_row.addWidget(self.progress_label, 2)
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.open_output_button)
        outer.addLayout(progress_row)

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("フォルダーを選択してください")
        for widget in (
            self.source_combo.lineEdit(), self.output_combo.lineEdit(),
            self.excluded_dirs, self.excluded_exts, self.included_exts,
            self.patterns, self.search_edit,
        ):
            if widget is not None:
                self._install_japanese_context_menu(widget)
        self._add_shortcuts()

    def _install_japanese_context_menu(self, widget: QLineEdit | QPlainTextEdit) -> None:
        """Replace the platform's English edit menu with a Japanese one."""
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(
            lambda position, target=widget: self._show_japanese_context_menu(target, position)
        )

    def _show_japanese_context_menu(
        self, widget: QLineEdit | QPlainTextEdit, position
    ) -> None:  # type: ignore[no-untyped-def]
        is_line_edit = isinstance(widget, QLineEdit)
        selected = widget.hasSelectedText() if is_line_edit else widget.textCursor().hasSelection()
        read_only = widget.isReadOnly()
        if is_line_edit:
            undo_available = widget.isUndoAvailable()
            redo_available = widget.isRedoAvailable()
        else:
            undo_available = widget.document().isUndoAvailable()
            redo_available = widget.document().isRedoAvailable()

        menu = QMenu(widget)
        undo_action = menu.addAction("元に戻す")
        undo_action.setShortcut(QKeySequence.Undo)
        undo_action.setEnabled(undo_available and not read_only)
        undo_action.triggered.connect(widget.undo)
        redo_action = menu.addAction("やり直す")
        redo_action.setShortcut(QKeySequence.Redo)
        redo_action.setEnabled(redo_available and not read_only)
        redo_action.triggered.connect(widget.redo)
        menu.addSeparator()

        cut_action = menu.addAction("切り取り")
        cut_action.setShortcut(QKeySequence.Cut)
        cut_action.setEnabled(selected and not read_only)
        cut_action.triggered.connect(widget.cut)
        copy_action = menu.addAction("コピー")
        copy_action.setShortcut(QKeySequence.Copy)
        copy_action.setEnabled(selected)
        copy_action.triggered.connect(widget.copy)
        paste_action = menu.addAction("貼り付け")
        paste_action.setShortcut(QKeySequence.Paste)
        paste_action.setEnabled(not read_only and bool(QApplication.clipboard().text()))
        paste_action.triggered.connect(widget.paste)
        delete_action = menu.addAction("削除")
        delete_action.setShortcut(QKeySequence.Delete)
        delete_action.setEnabled(selected and not read_only)
        delete_action.triggered.connect(lambda: self._delete_text_selection(widget))
        menu.addSeparator()

        select_all_action = menu.addAction("すべて選択")
        select_all_action.setShortcut(QKeySequence.SelectAll)
        select_all_action.setEnabled(bool(widget.text() if is_line_edit else widget.toPlainText()))
        select_all_action.triggered.connect(widget.selectAll)
        menu.exec(widget.mapToGlobal(position))

    @staticmethod
    def _delete_text_selection(widget: QLineEdit | QPlainTextEdit) -> None:
        if isinstance(widget, QLineEdit):
            widget.insert("")
            return
        cursor = widget.textCursor()
        cursor.removeSelectedText()
        widget.setTextCursor(cursor)

    def _clear_initial_text_selections(self) -> None:
        """Keep preset values visible without showing an accidental selection."""
        for line_edit in (
            self.source_combo.lineEdit(), self.output_combo.lineEdit(),
            self.excluded_exts, self.included_exts, self.patterns, self.search_edit,
        ):
            if line_edit is not None:
                line_edit.deselect()
                line_edit.setCursorPosition(len(line_edit.text()))
        cursor = self.excluded_dirs.textCursor()
        cursor.clearSelection()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.excluded_dirs.setTextCursor(cursor)
        self.preview_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def _add_shortcuts(self) -> None:
        preview_action = QAction(self)
        preview_action.setShortcut(QKeySequence("Ctrl+P"))
        preview_action.triggered.connect(lambda: self.start_scan(False))
        self.addAction(preview_action)
        generate_action = QAction(self)
        generate_action.setShortcut(QKeySequence("Ctrl+G"))
        generate_action.triggered.connect(lambda: self.start_scan(True))
        self.addAction(generate_action)
        find_action = QAction(self)
        find_action.setShortcut(QKeySequence.Find)
        find_action.triggered.connect(self.search_edit.setFocus)
        self.addAction(find_action)

    def _load_config_into_ui(self) -> None:
        for value in self.config.get("source_history", []):
            self.source_combo.addItem(value)
        for value in self.config.get("output_history", []):
            self.output_combo.addItem(value)
        self.source_combo.setCurrentText(str(self.config.get("source", "")))
        self.output_combo.setCurrentText(str(self.config.get("output", "")))
        preset = str(self.config.get("preset", "開発用おすすめ"))
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentText(preset if preset in PRESETS else "開発用おすすめ")
        self.preset_combo.blockSignals(False)
        self._set_filter_ui(FilterSettings.from_dict(self.config.get("filters")))
        for key, checkbox in self.format_checks.items():
            checkbox.setChecked(bool(self.config.get("formats", {}).get(key, key != "json")))

    def _set_filter_ui(self, settings: FilterSettings) -> None:
        self.excluded_dirs.setPlainText("\n".join(settings.excluded_dirs))
        self.excluded_exts.setText(", ".join(settings.excluded_extensions))
        self.included_exts.setText(", ".join(settings.included_extensions))
        self.patterns.setText(", ".join(settings.patterns))
        self.hidden_check.setChecked(settings.include_hidden)
        self.empty_check.setChecked(settings.include_empty_dirs)
        self.symlink_check.setChecked(settings.follow_symlinks)
        self.max_depth.setValue(settings.max_depth)

    @staticmethod
    def _split_csv(text: str) -> list[str]:
        return [item.strip() for item in text.replace(";", ",").split(",") if item.strip()]

    def current_filters(self) -> FilterSettings:
        return FilterSettings(
            excluded_dirs=[line.strip() for line in self.excluded_dirs.toPlainText().splitlines() if line.strip()],
            excluded_extensions=self._split_csv(self.excluded_exts.text()),
            included_extensions=self._split_csv(self.included_exts.text()),
            patterns=self._split_csv(self.patterns.text()), include_hidden=self.hidden_check.isChecked(),
            include_empty_dirs=self.empty_check.isChecked(), follow_symlinks=self.symlink_check.isChecked(),
            max_depth=self.max_depth.value(),
        )

    @Slot(str)
    def apply_preset(self, name: str) -> None:
        if name not in PRESETS:
            return
        current = self.current_filters()
        preset = PRESETS[name]
        current.excluded_dirs = list(preset["excluded_dirs"])
        current.excluded_extensions = list(preset["excluded_extensions"])
        current.patterns = list(preset["patterns"])
        current.include_hidden = bool(preset["include_hidden"])
        self._set_filter_ui(current)

    def choose_source(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "対象フォルダーを選択", self.source_combo.currentText())
        if path:
            self.source_combo.setCurrentText(path)
            if not self.output_combo.currentText().strip():
                self.output_combo.setCurrentText(str(Path(path).parent / "DirectoryTree_Output"))

    def choose_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "出力先を選択", self.output_combo.currentText())
        if path:
            self.output_combo.setCurrentText(path)

    def _validate(self, require_format: bool) -> tuple[Path, Path] | None:
        source = Path(self.source_combo.currentText().strip())
        output_text = self.output_combo.currentText().strip()
        output = Path(output_text) if output_text else source.parent / "DirectoryTree_Output"
        if not source.is_dir():
            QMessageBox.warning(self, "確認", "対象フォルダーを正しく選択してください。")
            return None
        if source.resolve() == output.expanduser().resolve():
            QMessageBox.warning(self, "確認", "出力先は対象フォルダーとは別の場所を選択してください。")
            return None
        if require_format and not any(box.isChecked() for box in self.format_checks.values()):
            QMessageBox.warning(self, "確認", "出力形式を1つ以上選択してください。")
            return None
        return source, output

    def start_scan(self, generate: bool) -> None:
        if self.thread and self.thread.isRunning():
            return
        paths = self._validate(generate)
        if not paths:
            return
        source, output = paths
        self._generate_after_scan = generate
        self.result = None
        self.preview.clear()
        self._set_running(True)
        self.progress_label.setText("走査しています…")
        self.statusBar().showMessage("フォルダーを走査中")

        self.thread = QThread(self)
        self.worker = ScanWorker(source, output, self.current_filters())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_scan_finished)
        self.worker.failed.connect(self.on_scan_failed)
        self.worker.cancelled.connect(self.on_scan_cancelled)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.cancelled.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        self.thread.start()

    @Slot()
    def _thread_finished(self) -> None:
        finished_thread = self.thread
        self.worker = None
        self.thread = None
        if finished_thread is not None:
            finished_thread.deleteLater()

    def _set_running(self, running: bool) -> None:
        self.preview_button.setEnabled(not running)
        self.generate_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.progress_bar.setRange(0, 0 if running else 1)
        if not running:
            self.progress_bar.setValue(1)

    @Slot(str, int, int)
    def on_progress(self, path: str, folders: int, files: int) -> None:
        self.progress_label.setText(f"走査中: {folders}フォルダー / {files}ファイル — {path}")

    @Slot(object)
    def on_scan_finished(self, result: ScanResult) -> None:
        self.result = result
        self._set_running(False)
        self.preview.setPlainText("\n".join(tree_lines(result.root)))
        stats = result.stats
        self.stats_label.setText(
            f"フォルダー {stats.folders:,}  ｜  ファイル {stats.files:,}  ｜  "
            f"{format_size(stats.total_size)}  ｜  除外 {stats.excluded:,}  ｜  エラー {stats.error_count}"
        )
        self.progress_label.setText(f"走査完了（{stats.elapsed_seconds:.2f}秒）")
        self.statusBar().showMessage("プレビューを更新しました", 5000)
        if self._generate_after_scan:
            self.generate_outputs()

    @Slot(str)
    def on_scan_failed(self, message: str) -> None:
        self._set_running(False)
        self.progress_label.setText("エラー")
        QMessageBox.critical(self, "走査エラー", message)

    @Slot()
    def on_scan_cancelled(self) -> None:
        self._set_running(False)
        self.progress_label.setText("中止しました")
        self.statusBar().showMessage("走査を中止しました", 5000)

    def cancel_scan(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.progress_label.setText("中止を待っています…")

    def generate_outputs(self) -> None:
        if not self.result:
            return
        output = Path(self.output_combo.currentText().strip() or self.result.source.parent / "DirectoryTree_Output")
        formats = [key for key, checkbox in self.format_checks.items() if checkbox.isChecked()]
        try:
            created = export_selected(self.result, output, formats)
        except OSError as exc:
            QMessageBox.critical(self, "出力エラー", f"ファイルを保存できませんでした。\n\n{exc}")
            return
        self.output_combo.setCurrentText(str(output))
        self.progress_label.setText(f"{len(created)}ファイルを作成しました")
        names = "\n".join(f"・{path.name}" for path in created)
        warning = ""
        if self.result.stats.errors:
            warning = f"\n\n読み取れなかった項目: {self.result.stats.error_count}件"
        QMessageBox.information(self, "生成完了", f"次のファイルを作成しました。\n\n{names}{warning}")
        self._save_ui_config()

    def find_next(self) -> None:
        text = self.search_edit.text()
        if text and not self.preview.find(text):
            cursor = self.preview.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.preview.setTextCursor(cursor)
            self.preview.find(text)

    def copy_preview(self) -> None:
        QApplication.clipboard().setText(self.preview.toPlainText())
        self.statusBar().showMessage("プレビューをコピーしました", 3000)

    def open_output(self) -> None:
        path = Path(self.output_combo.currentText().strip())
        if not path.exists():
            QMessageBox.information(self, "確認", "出力先フォルダーはまだ作成されていません。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def toggle_theme(self) -> None:
        self.apply_theme("light" if self.config.get("theme") == "dark" else "dark")

    def apply_theme(self, theme: str) -> None:
        self.config["theme"] = theme
        self.setStyleSheet(DARK_STYLE if theme == "dark" else LIGHT_STYLE)
        self.theme_action.setText("☀ ライト表示" if theme == "dark" else "🌙 ダーク表示")

    def show_about(self) -> None:
        QMessageBox.about(
            self, "このアプリについて",
            f"{APP_NAME}\nVer.{APP_VERSION}\n\n更新日: {UPDATED}\n作者: {AUTHOR}\n\n"
            "フォルダー構成をフィルターして TXT / HTML / CSV / JSON に出力します。",
        )

    def _save_ui_config(self) -> None:
        source = self.source_combo.currentText().strip()
        output = self.output_combo.currentText().strip()
        self.config.update({
            "source": source, "output": output,
            "source_history": add_history(list(self.config.get("source_history", [])), source),
            "output_history": add_history(list(self.config.get("output_history", [])), output),
            "formats": {key: checkbox.isChecked() for key, checkbox in self.format_checks.items()},
            "filters": self.current_filters().to_dict(), "preset": self.preset_combo.currentText(),
            "window": {"width": self.width(), "height": self.height()},
        })
        try:
            save_config(self.config)
        except OSError:
            pass

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.thread and self.thread.isRunning():
            answer = QMessageBox.question(self, "終了確認", "走査中です。中止して終了しますか？")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if self.worker:
                self.worker.cancel()
            self.thread.quit()
            self.thread.wait(2000)
        self._save_ui_config()
        event.accept()
