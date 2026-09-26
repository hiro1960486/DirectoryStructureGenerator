"""Preset management dialog."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QMessageBox, QPushButton, QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .settings_presets import (
    MAX_FAVORITES, export_presets_csv, import_presets_csv, merge_presets,
    normalize_preset, normalize_presets,
)


class PresetManagerDialog(QDialog):
    presetsChanged = Signal(object)
    presetApplied = Signal(object)
    quickLimitChanged = Signal(int)

    def __init__(
        self,
        presets: list[dict[str, Any]],
        current_settings: Callable[[], dict[str, Any]],
        parent=None,
        max_quick_presets: int = MAX_FAVORITES,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("設定プリセット管理")
        self.resize(820, 520)
        self.max_quick_presets = max(1, min(99, int(max_quick_presets)))
        self.presets = normalize_presets(presets, self.max_quick_presets)
        self.current_settings = current_settings
        self._updating = False

        layout = QVBoxLayout(self)
        title = QLabel("設定プリセット")
        title.setStyleSheet("font-size:17pt;font-weight:700")
        layout.addWidget(title)
        limit_row = QHBoxLayout()
        limit_row.addWidget(QLabel("基本は1件。クイック表示の上限（基本を含む）:"))
        self.quick_limit_spin = QSpinBox()
        self.quick_limit_spin.setRange(1, 99)
        self.quick_limit_spin.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        self.quick_limit_spin.setEnabled(True)
        self.quick_limit_spin.setSuffix(" 件")
        self.quick_limit_spin.setValue(self.max_quick_presets)
        self.quick_limit_spin.setToolTip("メイン画面に表示できるクイック設定の最大数を指定します")
        self.quick_limit_spin.valueChanged.connect(self._on_quick_limit_changed)
        limit_row.addWidget(self.quick_limit_spin)
        limit_row.addStretch()
        layout.addLayout(limit_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["既定", "クイック", "順番", "プリセット名", "メモ", "種類"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.setStyleSheet(
            "QTableWidget::item:selected { background:#2563eb; color:white; }"
            "QTableWidget::item:selected:!active { background:#3b82f6; color:white; }"
        )
        self.table.itemChanged.connect(self._on_cell_edited)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column in (0, 1, 2, 3, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        add_button = QPushButton("現在の設定を追加")
        update_button = QPushButton("現在の設定で更新")
        edit_button = QPushButton("名前・メモを編集")
        duplicate_button = QPushButton("複製")
        delete_button = QPushButton("削除")
        apply_button = QPushButton("選択した設定を適用")
        apply_button.setObjectName("primary")
        add_button.clicked.connect(self.add_current)
        update_button.clicked.connect(self.update_selected)
        edit_button.clicked.connect(self.edit_selected)
        duplicate_button.clicked.connect(self.duplicate_selected)
        delete_button.clicked.connect(self.delete_selected)
        apply_button.clicked.connect(self.apply_selected)
        for button in (add_button, update_button, edit_button, duplicate_button, delete_button):
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
            default = QRadioButton()
            default.setChecked(bool(preset.get("default", False)))
            default.setToolTip("アプリ起動時に使う基本プリセット（1件）")
            default.clicked.connect(lambda _checked=False, index=row: self.set_default(index))
            self.table.setCellWidget(row, 0, self._centered(default))
            quick = QCheckBox()
            quick.setChecked(bool(preset.get("quick", preset.get("favorite", False))))
            quick.setToolTip(f"メイン画面に表示します（最大{self.max_quick_presets}件）")
            quick.stateChanged.connect(lambda state, index=row: self.toggle_favorite(index, state))
            self.table.setCellWidget(row, 1, self._centered(quick))
            order = QSpinBox()
            order.setRange(1, 99)
            order.setValue(int(preset.get("order", row + 1)))
            order.valueChanged.connect(lambda value, index=row: self.set_order(index, value))
            self.table.setCellWidget(row, 2, order)
            name_item = QTableWidgetItem(str(preset["name"]))
            memo_item = QTableWidgetItem(str(preset.get("memo", "")))
            if preset.get("builtin"):
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                memo_item.setFlags(memo_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            else:
                name_item.setToolTip("ダブルクリックして、この欄で名前を編集できます")
                memo_item.setToolTip("ダブルクリックして、この欄でメモを編集できます")
            self.table.setItem(row, 3, name_item)
            self.table.setItem(row, 4, memo_item)
            kind_item = QTableWidgetItem("標準" if preset.get("builtin") else "ユーザー")
            kind_item.setFlags(kind_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 5, kind_item)
            if preset["name"] == selected_name:
                selected_row = row
        if self.presets:
            self.table.selectRow(selected_row)
        self._updating = False

    @staticmethod
    def _centered(widget: QWidget) -> QWidget:
        holder = QWidget()
        holder.setLayout(QHBoxLayout())
        holder.layout().setContentsMargins(8, 0, 8, 0)
        holder.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
        holder.layout().addWidget(widget)
        return holder

    def set_default(self, index: int) -> None:
        if self._updating or not (0 <= index < len(self.presets)):
            return
        for row, item in enumerate(self.presets):
            item["default"] = row == index
        self.presets[index]["quick"] = True
        self.presets[index]["favorite"] = True
        self.refresh(self.presets[index]["name"])
        self._changed()

    def set_order(self, index: int, value: int) -> None:
        if self._updating or not (0 <= index < len(self.presets)):
            return
        name = self.presets[index]["name"]
        self.presets[index]["order"] = value
        self._changed()
        QTimer.singleShot(0, lambda selected_name=name: self.refresh(selected_name))

    def _on_cell_edited(self, cell: QTableWidgetItem) -> None:
        if self._updating or cell.column() not in (3, 4):
            return
        row = cell.row()
        if not (0 <= row < len(self.presets)) or self.presets[row].get("builtin"):
            return
        old = self.presets[row]
        value = cell.text().strip()
        if cell.column() == 3:
            if not value:
                self.refresh(str(old["name"]))
                QMessageBox.warning(self, "プリセット名", "名前を空欄にはできません。")
                return
            if any(
                i != row and item["name"].casefold() == value.casefold()
                for i, item in enumerate(self.presets)
            ):
                self.refresh(str(old["name"]))
                QMessageBox.warning(self, "プリセット名", "同じ名前のプリセットがあります。")
                return
            old["name"] = value
        else:
            old["memo"] = value
        selected_name = str(old["name"])
        self._changed()
        self.refresh(selected_name)

    def selected_index(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def toggle_favorite(self, index: int, state: int) -> None:
        if self._updating or not (0 <= index < len(self.presets)):
            return
        enabled = state == Qt.CheckState.Checked.value
        if not enabled and self.presets[index].get("default"):
            QMessageBox.information(self, "基本プリセット", "基本プリセットはクイック表示から外せません。")
            self.refresh(self.presets[index]["name"])
            return
        if enabled and sum(bool(item.get("quick")) for item in self.presets) >= self.max_quick_presets:
            QMessageBox.information(
                self, "クイック表示", f"クイック表示は最大{self.max_quick_presets}件です。"
            )
            self.refresh(self.presets[index]["name"])
            return
        self.presets[index]["quick"] = enabled
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
        item.update({"name": name, "memo": memo, "favorite": False, "quick": False,
                     "default": False, "order": len(self.presets) + 1, "builtin": False})
        self.presets.append(normalize_preset(item))
        self.refresh(name)
        self._changed()

    def update_selected(self) -> None:
        index = self.selected_index()
        if index < 0:
            return
        old = self.presets[index]
        if old.get("builtin"):
            QMessageBox.information(self, "更新", "標準プリセットは更新できません。複製して編集してください。")
            return
        if QMessageBox.question(
            self, "プリセット更新確認",
            f"「{old['name']}」を現在の画面設定で更新しますか？\n走査やコピーは開始されません。",
        ) != QMessageBox.StandardButton.Yes:
            return
        updated = self.current_settings()
        updated.update({key: old[key] for key in (
            "name", "memo", "favorite", "quick", "default", "order", "builtin"
        ) if key in old})
        self.presets[index] = normalize_preset(updated)
        self.refresh(str(old["name"]))
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
        source.update({"name": prompted[0], "memo": prompted[1], "favorite": False,
                       "quick": False, "default": False,
                       "order": len(self.presets) + 1, "builtin": False})
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
            export_presets_csv(Path(filename), self.presets, self.max_quick_presets)
        except OSError as exc:
            QMessageBox.critical(self, "CSV保存エラー", str(exc))
            return
        QMessageBox.information(self, "CSV保存", f"{len(self.presets)}件を書き出しました。")

    def import_csv(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "プリセットCSVを読み込み", "", "CSV (*.csv)")
        if not filename:
            return
        try:
            incoming = import_presets_csv(Path(filename), self.max_quick_presets)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "CSV読み込みエラー", str(exc))
            return
        if QMessageBox.question(
            self, "読み込み確認",
            f"{len(incoming)}件を読み込みます。\n同名プリセットはCSVの内容で更新します。よろしいですか？",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.presets = merge_presets(self.presets, incoming, self.max_quick_presets)
        self.refresh()
        self._changed()

    def _changed(self) -> None:
        self.presets = normalize_presets(self.presets, self.max_quick_presets)
        self.presetsChanged.emit(self.presets)

    def _on_quick_limit_changed(self, value: int) -> None:
        self.max_quick_presets = max(1, min(99, int(value)))
        self.quickLimitChanged.emit(self.max_quick_presets)
        self.presets = normalize_presets(self.presets, self.max_quick_presets)
        # Treat the selected limit as the desired number of quick presets.
        # Raising it should make additional presets appear without requiring
        # users to discover and check each row manually.
        quick_count = sum(bool(item.get("quick")) for item in self.presets)
        for item in self.presets:
            if quick_count >= self.max_quick_presets:
                break
            if not item.get("quick"):
                item["quick"] = True
                item["favorite"] = True
                quick_count += 1
        self.refresh()
        self._changed()

