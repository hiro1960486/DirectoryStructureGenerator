"""Preset management dialog.

Version: 2.9.5
Updated: 2026-09-26
Author: hiro1960
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from .settings_presets import (
    MAX_FAVORITES, export_presets_csv, import_presets_csv, merge_presets,
    normalize_preset, normalize_presets,
)


class PresetCreateDialog(QDialog):
    """Collect a preset name, memo, and its source/output folders."""

    def __init__(self, name: str, memo: str, source: str, output: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("プリセットを作成")
        self.resize(680, 250)
        form = QFormLayout(self)
        self.name_edit = QLineEdit(name)
        self.memo_edit = QTextEdit(memo)
        self.memo_edit.setMaximumHeight(70)
        self.source_edit = QLineEdit(source)
        self.output_edit = QLineEdit(output)
        form.addRow("プリセット名", self.name_edit)
        form.addRow("メモ", self.memo_edit)
        form.addRow("1. 対象フォルダー", self._folder_row(self.source_edit, "対象フォルダーを選択"))
        form.addRow("出力先フォルダー", self._folder_row(self.output_edit, "出力先フォルダーを選択"))
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.save_button = QPushButton("作成")
        self.cancel_button = QPushButton("キャンセル")
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.cancel_button)
        form.addRow(buttons)

    def _folder_row(self, edit: QLineEdit, title: str) -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit, 1)
        browse = QPushButton("参照…")
        browse.clicked.connect(lambda: self._choose_folder(edit, title))
        layout.addWidget(browse)
        return row

    def _choose_folder(self, edit: QLineEdit, title: str) -> None:
        selected = QFileDialog.getExistingDirectory(self, title, edit.text().strip())
        if selected:
            edit.setText(selected)


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
        self.resize(900, 560)
        self.max_quick_presets = max(1, min(99, int(max_quick_presets)))
        self.presets = normalize_presets(presets, self.max_quick_presets)
        self.current_settings = current_settings
        self._updating = False
        self.order_spin_boxes: list[QSpinBox] = []
        self.order_up_buttons: list[QPushButton] = []
        self.order_down_buttons: list[QPushButton] = []

        layout = QVBoxLayout(self)
        title = QLabel("設定プリセット")
        title.setStyleSheet("font-size:17pt;font-weight:700")
        layout.addWidget(title)
        limit_row = QHBoxLayout()
        limit_row.addWidget(QLabel("基本は1件。クイック表示の上限（基本を含む）:"))
        self.quick_limit_spin = QSpinBox()
        self.quick_limit_spin.setRange(1, 99)
        # Separate, roomy arrow buttons make the count easy to adjust by mouse.
        self.quick_limit_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.quick_limit_spin.setEnabled(True)
        self.quick_limit_spin.setReadOnly(False)
        self.quick_limit_spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.quick_limit_spin.setMinimumWidth(82)
        self.quick_limit_spin.setMinimumHeight(38)
        self.quick_limit_spin.setSuffix(" 件")
        self.quick_limit_spin.setValue(self.max_quick_presets)
        self.quick_limit_spin.setToolTip("メイン画面に表示できるクイック設定の最大数を指定します")
        self.quick_limit_spin.valueChanged.connect(self._on_quick_limit_changed)
        limit_row.addWidget(self.quick_limit_spin)
        arrow_buttons = QWidget()
        arrow_layout = QVBoxLayout(arrow_buttons)
        arrow_layout.setContentsMargins(0, 0, 0, 0)
        arrow_layout.setSpacing(2)
        self.quick_limit_up_button = QPushButton("▲")
        self.quick_limit_up_button.setToolTip("件数を1増やす")
        self.quick_limit_up_button.clicked.connect(self.quick_limit_spin.stepUp)
        self.quick_limit_down_button = QPushButton("▼")
        self.quick_limit_down_button.setToolTip("件数を1減らす")
        self.quick_limit_down_button.clicked.connect(self.quick_limit_spin.stepDown)
        for button in (self.quick_limit_up_button, self.quick_limit_down_button):
            button.setFixedSize(32, 18)
            button.setStyleSheet("padding:0px; border-radius:3px; font-size:8pt;")
            arrow_layout.addWidget(button)
        limit_row.addWidget(arrow_buttons)
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
        for column in (0, 1, 3, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 124)
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
        self.order_spin_boxes.clear()
        self.order_up_buttons.clear()
        self.order_down_buttons.clear()
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
            order_cell = QWidget()
            order_layout = QHBoxLayout(order_cell)
            order_layout.setContentsMargins(3, 2, 3, 2)
            order_layout.setSpacing(4)
            order = QSpinBox()
            order.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            order.setRange(1, 99)
            order.setAlignment(Qt.AlignmentFlag.AlignCenter)
            order.setFixedSize(68, 40)
            order.setStyleSheet("QSpinBox { padding:2px; min-height:32px; }")
            order.setValue(int(preset.get("order", row + 1)))
            order.valueChanged.connect(lambda value, index=row: self.set_order(index, value))

            order_arrows = QWidget()
            arrow_layout = QVBoxLayout(order_arrows)
            arrow_layout.setContentsMargins(0, 0, 0, 0)
            arrow_layout.setSpacing(2)
            up_button = QPushButton("▲")
            up_button.setToolTip("このプリセットの表示順を1つ上げます")
            up_button.setAccessibleName(f"順番を上げる: {preset['name']}")
            up_button.setFixedSize(36, 21)
            up_button.setStyleSheet("padding:0px; min-height:21px; max-height:21px; font-size:8pt;")
            up_button.clicked.connect(order.stepUp)
            down_button = QPushButton("▼")
            down_button.setToolTip("このプリセットの表示順を1つ下げます")
            down_button.setAccessibleName(f"順番を下げる: {preset['name']}")
            down_button.setFixedSize(36, 21)
            down_button.setStyleSheet("padding:0px; min-height:21px; max-height:21px; font-size:8pt;")
            down_button.clicked.connect(order.stepDown)
            arrow_layout.addWidget(up_button)
            arrow_layout.addWidget(down_button)

            order_layout.addWidget(order)
            order_layout.addWidget(order_arrows)
            self.table.setCellWidget(row, 2, order_cell)
            self.table.setRowHeight(row, 48)
            self.order_spin_boxes.append(order)
            self.order_up_buttons.append(up_button)
            self.order_down_buttons.append(down_button)
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
        current = self.current_settings()
        dialog = PresetCreateDialog(
            "新しいプリセット", "", str(current.get("source", "")),
            str(current.get("output", "")), self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "プリセット名", "プリセット名を入力してください。")
            return
        if any(item["name"].casefold() == name.casefold() for item in self.presets):
            QMessageBox.warning(self, "確認", "同じ名前のプリセットがあります。")
            return
        item = current
        item.update({"source": dialog.source_edit.text().strip(),
                     "output": dialog.output_edit.text().strip()})
        item.update({"name": name, "memo": dialog.memo_edit.toPlainText().strip(),
                     "favorite": False, "quick": False,
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
