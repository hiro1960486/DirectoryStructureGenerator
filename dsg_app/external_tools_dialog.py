"""Choose and launch companion Windows applications."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .config_manager import save_config


class ExternalToolsDialog(QDialog):
    """Store executable paths and launch the selected companion app."""

    TOOLS = (
        ("preset_manager", "DirectoryStructureGenerator.PresetManager"),
        ("rename_wizard", "RenameWizard"),
    )

    def __init__(self, config: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.path_edits: dict[str, QLineEdit] = {}
        self.setWindowTitle("関連アプリの設定・起動")
        self.setMinimumWidth(720)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "各アプリの実行ファイルを一度指定すると、設定に保存されます。"
        ))

        values = config.get("external_tools", {})
        if not isinstance(values, dict):
            values = {}
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        for row, (key, title) in enumerate(self.TOOLS):
            edit = QLineEdit(str(values.get(key, "")))
            edit.setObjectName(f"{key}_path")
            edit.setPlaceholderText("実行ファイル（.exe）の場所")
            edit.setClearButtonEnabled(True)
            browse = QPushButton("参照…")
            browse.clicked.connect(lambda _checked=False, tool_key=key: self.choose_executable(tool_key))
            launch = QPushButton("起動")
            launch.setObjectName(f"{key}_launch")
            launch.clicked.connect(lambda _checked=False, tool_key=key: self.launch_tool(tool_key))
            edit.editingFinished.connect(self.save_paths)
            self.path_edits[key] = edit
            grid.addWidget(QLabel(title), row, 0)
            grid.addWidget(edit, row, 1)
            grid.addWidget(browse, row, 2)
            grid.addWidget(launch, row, 3)
        layout.addLayout(grid)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_button = QPushButton("設定を保存")
        save_button.setObjectName("primary")
        save_button.clicked.connect(self.save_paths)
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(save_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def choose_executable(self, key: str) -> None:
        edit = self.path_edits[key]
        current = Path(edit.text().strip()).expanduser()
        initial = str(current.parent) if current.parent.is_dir() else str(Path.home())
        selected, _ = QFileDialog.getOpenFileName(
            self,
            f"{dict((k, title) for k, title in self.TOOLS)[key]} の実行ファイルを選択",
            initial,
            "実行ファイル (*.exe);;すべてのファイル (*)",
        )
        if selected:
            edit.setText(selected)
            self.save_paths()

    def save_paths(self) -> None:
        values = self.config.get("external_tools")
        if not isinstance(values, dict):
            values = {}
            self.config["external_tools"] = values
        for key, edit in self.path_edits.items():
            values[key] = edit.text().strip()
        try:
            save_config(self.config)
        except OSError as exc:
            QMessageBox.critical(self, "設定保存エラー", f"実行ファイルの場所を保存できませんでした。\n\n{exc}")
            return
        self.setWindowTitle("関連アプリの設定・起動 — 保存済み")

    def done(self, result: int) -> None:
        # Also keep edits when the dialog is closed with its title-bar button.
        self.save_paths()
        super().done(result)

    def launch_tool(self, key: str) -> None:
        self.save_paths()
        raw_path = self.path_edits[key].text().strip()
        title = dict((k, name) for k, name in self.TOOLS)[key]
        if not raw_path:
            QMessageBox.information(
                self, "実行ファイルの指定", f"先に「{title}」の実行ファイルを指定してください。"
            )
            return
        path = Path(raw_path).expanduser()
        if not path.is_file():
            QMessageBox.warning(
                self, "実行ファイルが見つかりません",
                f"指定されたファイルを確認できません。\n\n{path}\n\n参照ボタンから選び直してください。",
            )
            return
        try:
            started, _process_id = QProcess.startDetached(str(path.resolve()), [], str(path.resolve().parent))
        except (OSError, RuntimeError) as exc:
            QMessageBox.critical(self, "起動エラー", f"{title} を起動できませんでした。\n\n{exc}")
            return
        if not started:
            QMessageBox.critical(
                self, "起動エラー", f"{title} を起動できませんでした。\n\n実行ファイルを確認してください。"
            )
