import os
import sys
import tempfile
import unittest
from pathlib import Path

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractSpinBox, QDialog, QFileDialog
from unittest.mock import patch

from dsg_app.settings_presets import (
    MAX_FAVORITES, builtin_presets, export_presets_csv, import_presets_csv,
    merge_presets, normalize_presets,
    set_preset_organizer_settings, startup_preset_name,
)
from dsg_app.preset_dialog import PresetCreateDialog, PresetManagerDialog


class SettingsPresetTests(unittest.TestCase):
    def test_builtin_presets_have_memos_and_favorite_limit(self) -> None:
        presets = builtin_presets()
        self.assertEqual(len(presets), 6)
        self.assertTrue(all(item["memo"] for item in presets))
        self.assertEqual(sum(bool(item["favorite"]) for item in presets), MAX_FAVORITES)
        self.assertEqual(sum(bool(item["default"]) for item in presets), 1)
        self.assertEqual(sum(bool(item["quick"]) for item in presets), MAX_FAVORITES)

    def test_normalize_limits_favorites_to_five(self) -> None:
        presets = builtin_presets()
        for item in presets:
            item["favorite"] = True
        normalized = normalize_presets(presets)
        self.assertEqual(sum(bool(item["favorite"]) for item in normalized), MAX_FAVORITES)

    def test_normalize_accepts_user_selected_quick_limit(self) -> None:
        presets = builtin_presets()
        for index in range(8):
            presets.append(dict(presets[0], name=f"ユーザー設定{index + 1}",
                                builtin=False, default=False, quick=True, favorite=True,
                                order=len(presets) + 1))
        normalized = normalize_presets(presets, max_favorites=8)
        self.assertEqual(sum(bool(item["quick"]) for item in normalized), 8)
        self.assertEqual(sum(bool(item["default"]) for item in normalized), 1)

    def test_preset_manager_limit_control_accepts_custom_number(self) -> None:
        app = QApplication.instance() or QApplication([])
        dialog = PresetManagerDialog(builtin_presets(), lambda: {})
        changed: list[int] = []
        dialog.quickLimitChanged.connect(changed.append)
        dialog.quick_limit_spin.setValue(8)
        self.assertEqual(dialog.max_quick_presets, 8)
        self.assertEqual(changed[-1], 8)
        dialog.close()

    def test_increasing_quick_limit_adds_more_presets_automatically(self) -> None:
        app = QApplication.instance() or QApplication([])
        dialog = PresetManagerDialog(builtin_presets(), lambda: {}, max_quick_presets=5)
        self.assertEqual(sum(bool(item["quick"]) for item in dialog.presets), 5)
        dialog.quick_limit_spin.setValue(6)
        self.assertEqual(sum(bool(item["quick"]) for item in dialog.presets), 6)
        dialog.quick_limit_spin.setValue(3)
        self.assertEqual(sum(bool(item["quick"]) for item in dialog.presets), 3)
        dialog.quick_limit_spin.setValue(6)
        self.assertEqual(sum(bool(item["quick"]) for item in dialog.presets), 6)
        dialog.close()

    def test_quick_limit_spin_has_active_arrow_controls_and_default_column_label(self) -> None:
        app = QApplication.instance() or QApplication([])
        dialog = PresetManagerDialog(builtin_presets(), lambda: {})
        self.assertTrue(dialog.quick_limit_spin.isEnabled())
        self.assertEqual(dialog.quick_limit_spin.buttonSymbols(), QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.assertTrue(dialog.quick_limit_up_button.isEnabled())
        self.assertTrue(dialog.quick_limit_down_button.isEnabled())
        self.assertEqual(dialog.table.horizontalHeaderItem(0).text(), "既定")
        dialog.close()

    def test_clicking_quick_limit_up_arrow_increments_the_value(self) -> None:
        app = QApplication.instance() or QApplication([])
        dialog = PresetManagerDialog(builtin_presets(), lambda: {})
        dialog.show()
        app.processEvents()
        before = dialog.quick_limit_spin.value()
        QTest.mouseClick(dialog.quick_limit_up_button, Qt.MouseButton.LeftButton)
        app.processEvents()
        self.assertEqual(dialog.quick_limit_spin.value(), before + 1)
        dialog.close()


    def test_clicking_order_up_and_down_buttons_changes_preset_order(self) -> None:
        app = QApplication.instance() or QApplication([])
        dialog = PresetManagerDialog(builtin_presets(), lambda: {})
        dialog.show()
        app.processEvents()
        self.assertEqual(len(dialog.order_up_buttons), len(dialog.presets))
        first_order = dialog.order_spin_boxes[0].value()
        self.assertGreaterEqual(dialog.order_up_buttons[0].width(), 36)
        QTest.mouseClick(dialog.order_up_buttons[0], Qt.MouseButton.LeftButton)
        app.processEvents()
        self.assertEqual(dialog.order_spin_boxes[0].value(), min(99, first_order + 1))
        QTest.mouseClick(dialog.order_down_buttons[0], Qt.MouseButton.LeftButton)
        app.processEvents()
        self.assertEqual(dialog.order_spin_boxes[0].value(), first_order)
        dialog.close()

    def test_preset_creation_saves_selected_source_and_output_folders(self) -> None:
        app = QApplication.instance() or QApplication([])
        manager = PresetManagerDialog(builtin_presets(), lambda: {
            "source": "C:/existing-source", "output": "D:/existing-output",
            "filters": {}, "formats": {}, "organizer": {},
        })
        from dsg_app import preset_dialog as preset_dialog_module
        create_dialog = PresetCreateDialog("選択フォルダー設定", "作成時に選んだ場所",
                                           "C:/selected-source", "D:/selected-output")
        with patch.object(preset_dialog_module, "PresetCreateDialog", return_value=create_dialog):
            with patch.object(create_dialog, "exec", return_value=QDialog.DialogCode.Accepted):
                manager.add_current()
        created = next(item for item in manager.presets if item["name"] == "選択フォルダー設定")
        self.assertEqual(created["source"], "C:/selected-source")
        self.assertEqual(created["output"], "D:/selected-output")
        self.assertEqual(created["memo"], "作成時に選んだ場所")
        manager.close()

    def test_preset_creation_folder_picker_sets_selected_path(self) -> None:
        app = QApplication.instance() or QApplication([])
        dialog = PresetCreateDialog("例", "", "", "")
        with patch.object(QFileDialog, "getExistingDirectory", return_value="D:/chosen"):
            dialog._choose_folder(dialog.source_edit, "対象フォルダーを選択")
        self.assertEqual(dialog.source_edit.text(), "D:/chosen")
        dialog.close()

    def test_organizer_defaults_are_saved_to_the_explicit_preset(self) -> None:
        presets = builtin_presets()
        organizer = {"result_format": "xlsx", "result_history_mode": "reset"}
        self.assertTrue(set_preset_organizer_settings(presets, "写真・画像", organizer))
        selected = next(item for item in presets if item["name"] == "写真・画像")
        self.assertEqual(selected["organizer"], organizer)
        self.assertEqual(presets[0]["organizer"], builtin_presets()[0]["organizer"])
        self.assertFalse(set_preset_organizer_settings(presets, "missing", organizer))

    def test_organizer_result_format_and_history_survive_normalization(self) -> None:
        presets = builtin_presets()
        settings = {
            "result_format": "xlsx", "result_history_mode": "reset",
            "result_log_directory": "D:/history", "default_destination": "D:/sorted",
        }
        self.assertTrue(set_preset_organizer_settings(presets, "写真・画像", settings))
        normalized = normalize_presets(presets)
        selected = next(item for item in normalized if item["name"] == "写真・画像")
        self.assertEqual(selected["organizer"]["result_format"], "xlsx")
        self.assertEqual(selected["organizer"]["result_history_mode"], "reset")
        self.assertEqual(selected["organizer"]["result_log_directory"], "D:/history")

    def test_startup_restores_last_active_preset_and_falls_back_to_default(self) -> None:
        presets = builtin_presets()
        presets.append(dict(presets[0], name="保存先を記憶", builtin=False, default=False, order=7))
        self.assertEqual(startup_preset_name(presets, "保存先を記憶"), "保存先を記憶")
        self.assertEqual(startup_preset_name(presets, "削除済み"), "開発フォルダー")

    def test_default_is_always_quick_and_only_one_default_exists(self) -> None:
        presets = builtin_presets()
        presets[0]["default"] = False
        presets[-1]["default"] = True
        presets[-1]["quick"] = False
        normalized = normalize_presets(presets)
        defaults = [item for item in normalized if item["default"]]
        self.assertEqual(len(defaults), 1)
        self.assertTrue(defaults[0]["quick"])

    def test_filter_lists_are_deduplicated_case_insensitively(self) -> None:
        preset = builtin_presets()[0]
        preset["filters"]["excluded_dirs"] = [".Trash", ".trash", " .git ", ".git"]
        normalized = normalize_presets([preset])
        self.assertEqual(normalized[0]["filters"]["excluded_dirs"], [".Trash", ".git"])

    def test_csv_round_trip_preserves_memo_and_safe_organizer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            preset = builtin_presets()[0]
            preset["memo"] = "毎週使う設定, カンマと改行\nも保持"
            preset["organizer"]["source_action"] = "delete"
            path = Path(temporary) / "presets.csv"
            export_presets_csv(path, [preset])
            loaded = import_presets_csv(path)
        self.assertEqual(loaded[0]["memo"], preset["memo"])
        self.assertNotIn("source_action", loaded[0]["organizer"])
        self.assertTrue(loaded[0]["default"])
        self.assertEqual(loaded[0]["order"], 1)

    def test_import_rejects_missing_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.csv"
            path.write_text("name,memo\n写真,画像用\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "必要な列"):
                import_presets_csv(path)

    def test_merge_updates_same_name_and_keeps_builtin_flag(self) -> None:
        existing = builtin_presets()
        incoming = [dict(existing[0], memo="CSVから更新", builtin=False)]
        merged = merge_presets(existing, incoming)
        target = next(item for item in merged if item["name"] == existing[0]["name"])
        self.assertEqual(target["memo"], "CSVから更新")
        self.assertTrue(target["builtin"])

    def test_csv_neutralizes_formula_and_restores_original_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            preset = builtin_presets()[0]
            preset["name"] = "=危険な数式"
            path = Path(temporary) / "presets.csv"
            export_presets_csv(path, [preset])
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("'=危険な数式", text)
            loaded = import_presets_csv(path)
        self.assertEqual(loaded[0]["name"], "=危険な数式")


if __name__ == "__main__":
    unittest.main()
