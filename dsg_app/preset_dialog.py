"""Preset management dialog."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .settings_presets import (
    MAX_FAVORITES, export_presets_csv, import_presets_csv, merge_presets,
    normalize_preset, normalize_presets,
)


class PresetManagerDialog(QDialog):
    presetsChanged = Signal(object)
    presetApplied = Signal(object)

    def __init__(
        self,
        presets: list[dict[str, Any]],
        current_settings: Callable[[], dict[str, Any]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("設定プリセット管理")
        self.resize(820, 520)
        self.presets = normalize_presets(presets)
        self.current_settings = current_settings
        self._updating = False

        layout = QVBoxLayout(self)
        title = QLabel("設定プリセット")
        title.setStyleSheet("font-size:17pt;font-weight:700")
        layout.addWidget(title)
        layout.addWidget(QLabel(
            f"常用は最大{MAX_FAVORITES}件です。メモには用途や対象フォルダーを記録できます。"
        ))

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["常用", "プリセット名", "メモ", "種類"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        add_button = QPushButton("現在の設定を追加")
        edit_button = QPushButton("名前・メモを編集")
        duplicate_button = QPushButton("複製")
        delete_button = QPushButton("削除")
        apply_button = QPushButton("選択した設定を適用")
        apply_button.setObjectName("primary")
        add_button.clicked.connect(self.add_current)
        edit_button.clicked.connect(self.edit_selected)
        duplicate_button.clicked.connect(self.duplicate_selected)
        delete_button.clicked.connect(self.delete_selected)
        apply_button.clicked.connect(self.apply_selected)
        for button in (add_button, edit_button, duplicate_button, delete_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(apply_button)
        layout.addLayout(actions)

        csv_actions = QHBoxLayout()
        export_button = QPushButton("CSVへ書き出し")
        import_button = QPushButton("CSVから読み込み")
        export_button.clicked.connect(self.export_csv)
        import_button.clicked.connect(self.import_csv)
        csv_actions.addWidget(export_button)
        csv_actions.addWidget(import_button)
        csv_actions.addStretch()
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.accept)
        csv_actions.addWidget(close_button)
        layout.addLayout(csv_actions)
        self.refresh()

    def refresh(self, selected_name: str = "") -> None:
        self._updating = True
        self.table.setRowCount(len(self.presets))
        selected_row = 0
        for row, preset in enumerate(self.presets):
            check = QCheckBox()
            check.setChecked(bool(preset.get("favorite", False)))
            check.setToolTip("常用プリセットとして上部に表示します（最大5件）")
            check.stateChanged.connect(lambda state, index=row: self.toggle_favorite(index, state))
            holder = QWidget()
            holder.setLayout(QHBoxLayout())
            holder.layout().setContentsMargins(8, 0, 8, 0)
            holder.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
            holder.layout().addWidget(check)
            self.table.setCellWidget(row, 0, holder)
            self.table.setItem(row, 1, QTableWidgetItem(str(preset["name"])))
            self.table.setItem(row, 2, QTableWidgetItem(str(preset.get("memo", ""))))
            self.table.setItem(row, 3, QTableWidgetItem("標準" if preset.get("builtin") else "ユーザー"))
            if preset["name"] == selected_name:
                selected_row = row
        if self.presets:
            self.table.selectRow(selected_row)
        self._updating = False

    def selected_index(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def toggle_favorite(self, index: int, state: int) -> None:
        if self._updating or not (0 <= index < len(self.presets)):
            return
        enabled = state == Qt.CheckState.Checked.value
        if enabled and sum(bool(item.get("favorite")) for item in self.presets) >= MAX_FAVORITES:
            QMessageBox.information(self, "常用プリセット", f"常用プリセットは最大{MAX_FAVORITES}件です。")
            self.refresh(self.presets[index]["name"])
            return
        self.presets[index]["favorite"] = enabled
        self._changed()

    def _prompt_name_and_memo(self, name: str, memo: str) -> tuple[str, str] | None:
        new_name, ok = QInputDialog.getText(self, "プリセット名", "名前", text=name)
        new_name = new_name.strip()
        if not ok or not new_name:
            return None
        duplicate = any(
            item["name"].casefold() == new_name.casefold() and item["name"] != name
            for item in self.presets
        )
        if duplicate:
            QMessageBox.warning(self, "確認", "同じ名前のプリセットがあります。")
            return None
        new_memo, ok = QInputDialog.getMultiLineText(
            self, "プリセットのメモ", "用途・対象・注意点など", memo
        )
        if not ok:
            return None
        return new_name, new_memo.strip()

    def add_current(self) -> None:
        prompted = self._prompt_name_and_memo("新しいプリセット", "")
        if not prompted:
            return
        name, memo = prompted
        item = self.current_settings()
        item.update({"name": name, "memo": memo, "favorite": False, "builtin": False})
        self.presets.append(normalize_preset(item))
        self.refresh(name)
        self._changed()

    def edit_selected(self) -> None:
        index = self.selected_index()
        if index < 0:
            return
        item = self.presets[index]
        prompted = self._prompt_name_and_memo(str(item["name"]), str(item.get("memo", "")))
        if not prompted:
            return
        item["name"], item["memo"] = prompted
        self.refresh(item["name"])
        self._changed()

    def duplicate_selected(self) -> None:
        index = self.selected_index()
        if index < 0:
            return
        source = dict(self.presets[index])
        prompted = self._prompt_name_and_memo(str(source["name"]) + " のコピー", str(source.get("memo", "")))
        if not prompted:
            return
        source.update({"name": prompted[0], "memo": prompted[1], "favorite": False, "builtin": False})
        self.presets.append(normalize_preset(source))
        self.refresh(source["name"])
        self._changed()

    def delete_selected(self) -> None:
        index = self.selected_index()
        if index < 0:
            return
        item = self.presets[index]
        if item.get("builtin"):
            QMessageBox.information(self, "削除", "標準プリセットは削除できません。複製して編集できます。")
            return
        if QMessageBox.question(self, "削除確認", f"「{item['name']}」を削除しますか？") != QMessageBox.StandardButton.Yes:
            return
        del self.presets[index]
        self.refresh()
        self._changed()

    def apply_selected(self) -> None:
        index = self.selected_index()
        if index < 0:
            return
        self.presetApplied.emit(dict(self.presets[index]))
        self.accept()

    def export_csv(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, "プリセットCSVを保存", "DirectoryStructureGenerator_presets.csv", "CSV (*.csv)")
        if not filename:
            return
        try:
            export_presets_csv(Path(filename), self.presets)
        except OSError as exc:
            QMessageBox.critical(self, "CSV保存エラー", str(exc))
            return
        QMessageBox.information(self, "CSV保存", f"{len(self.presets)}件を書き出しました。")

    def import_csv(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "プリセットCSVを読み込み", "", "CSV (*.csv)")
        if not filename:
            return
        try:
            incoming = import_presets_csv(Path(filename))
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "CSV読み込みエラー", str(exc))
            return
        if QMessageBox.question(
            self, "読み込み確認",
            f"{len(incoming)}件を読み込みます。\n同名プリセットはCSVの内容で更新します。よろしいですか？",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.presets = merge_presets(self.presets, incoming)
        self.refresh()
        self._changed()

    def _changed(self) -> None:
        self.presets = normalize_presets(self.presets)
        self.presetsChanged.emit(self.presets)
