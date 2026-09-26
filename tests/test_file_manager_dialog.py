import os
import sys
import tempfile
import unittest
from pathlib import Path

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl, Qt
from PySide6.QtWidgets import QApplication, QSplitter

from dsg_app.file_inspector import FileDetail
from dsg_app.file_manager_dialog import (
    FileManagerDialog, OrganizerSettingsDialog, copy_plan_column_widths, copy_result_counts, first_dropped_directory,
)
from dsg_app.organizer import CopyPlan
from dsg_app.models import FilterSettings


class DroppedDirectoryTests(unittest.TestCase):
    def test_returns_first_existing_local_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_path = root / "sample.txt"
            folder_path = root / "destination"
            file_path.write_text("sample", encoding="utf-8")
            folder_path.mkdir()

            result = first_dropped_directory([
                QUrl("https://example.com/folder"),
                QUrl.fromLocalFile(str(file_path)),
                QUrl.fromLocalFile(str(folder_path)),
            ])

            self.assertEqual(result, str(folder_path.resolve()))

    def test_returns_none_when_no_directory_is_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "sample.txt"
            file_path.write_text("sample", encoding="utf-8")

            result = first_dropped_directory([QUrl.fromLocalFile(str(file_path))])

            self.assertIsNone(result)


class MediaTimeTests(unittest.TestCase):
    def test_formats_minutes_and_hours(self) -> None:
        self.assertEqual(FileManagerDialog.format_media_time(65_000), "01:05")
        self.assertEqual(FileManagerDialog.format_media_time(3_661_000), "01:01:01")


class CopyResultCountTests(unittest.TestCase):
    def test_counts_success_skip_failure_and_cancelled(self) -> None:
        root = Path("C:/temporary")
        plans = [
            CopyPlan(root / "a", root / "out-a", "a", "コピー完了"),
            CopyPlan(root / "b", root / "out-b", "b", "既存のためスキップ"),
            CopyPlan(root / "c", root / "out-c", "c", "コピー失敗"),
            CopyPlan(root / "d", root / "out-d", "d", "中止により未実行"),
        ]

        self.assertEqual(
            copy_result_counts(plans),
            {"success": 1, "skipped": 1, "failed": 1, "cancelled": 1},
        )


class CopyPlanColumnWidthTests(unittest.TestCase):
    def test_widths_fill_normal_viewport_without_hidden_columns(self) -> None:
        viewport = 1040
        widths = copy_plan_column_widths(viewport)

        self.assertEqual(len(widths), 5)
        self.assertEqual(sum(widths), viewport - 2)
        self.assertTrue(all(width > 0 for width in widths))

    def test_small_viewport_uses_a_valid_width_distribution(self) -> None:
        widths = copy_plan_column_widths(420)

        self.assertEqual(len(widths), 5)
        self.assertEqual(sum(widths), 418)
        self.assertTrue(all(width > 0 for width in widths))


class CopyResultButtonStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.dialog = FileManagerDialog(self.root, self.output, FilterSettings())
        self.defaults = OrganizerSettingsDialog({}, [])

    def tearDown(self) -> None:
        self.dialog.close()
        self.defaults.close()
        self.temp.cleanup()

    def test_result_buttons_start_disabled(self) -> None:
        self.assertFalse(self.dialog.open_copy_log_button.isEnabled())
        self.assertFalse(self.dialog.open_copy_destination_button.isEnabled())
        self.assertFalse(self.dialog.reveal_copied_file_button.isEnabled())

    def test_dialog_has_standard_resize_controls(self) -> None:
        flags = self.dialog.windowFlags()
        self.assertTrue(flags & Qt.WindowType.WindowMinMaxButtonsHint)
        self.assertGreaterEqual(self.dialog.height(), self.dialog.minimumHeight())

    def test_copy_result_options_are_managed_only_in_default_settings(self) -> None:
        self.assertFalse(hasattr(self.dialog, "result_csv_radio"))
        self.assertTrue(self.defaults.result_csv_radio.isChecked())
        self.defaults.result_xlsx_radio.click()
        self.defaults.result_reset_radio.click()
        values = self.defaults.values()
        self.assertEqual(values["result_format"], "xlsx")
        self.assertEqual(values["result_history_mode"], "reset")

    def test_result_log_directory_is_editable_in_default_settings(self) -> None:
        history_path = self.root / "履歴"
        self.defaults.result_directory.setText(str(history_path))
        self.assertEqual(self.defaults.values()["result_log_directory"], str(history_path))

    def test_organize_tab_has_visible_vertical_resize_handle(self) -> None:
        splitter = self.dialog.findChild(QSplitter, "organizeResizeSplitter")
        self.assertIsNotNone(splitter)
        self.assertEqual(splitter.orientation(), Qt.Orientation.Vertical)
        self.assertIn("ドラッグ", self.dialog.plan_resize_hint.text())

    def test_csv_and_destination_enable_after_log_exists(self) -> None:
        log_path = self.output / "_DirectoryStructureGenerator_copy_log.csv"
        log_path.write_text("result\n", encoding="utf-8")
        self.dialog.last_copy_log_path = log_path
        self.dialog.last_copy_destination = self.output
        self.dialog.update_copy_result_buttons()

        self.assertTrue(self.dialog.open_copy_log_button.isEnabled())
        self.assertTrue(self.dialog.open_copy_destination_button.isEnabled())
        self.assertFalse(self.dialog.reveal_copied_file_button.isEnabled())

    def test_reveal_button_enables_only_for_existing_success_file(self) -> None:
        copied = self.output / "saved.txt"
        copied.write_text("copy", encoding="utf-8")
        self.dialog.last_copied_files = [copied]
        self.dialog.update_copy_result_buttons()

        self.assertTrue(self.dialog.reveal_copied_file_button.isEnabled())

class NaturalSortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.detail = FileDetail(
            name="sample.png",
            relative_path="images/sample.png",
            full_path="C:/sample/images/sample.png",
            category="image",
            extension=".png",
            file_size=1_500_000,
            modified="2026-09-22 10:00:00",
            created="2026-09-21 09:00:00",
            permissions="-rw-rw-rw-",
            readonly=False,
            line_count=1234,
            width=1920,
            height=1080,
            duration_seconds=65.5,
            frame_rate="29.97 fps",
        )

    def test_numeric_columns_use_raw_values(self) -> None:
        self.assertEqual(
            FileManagerDialog.sort_value_for_column(
                self.detail, FileManagerDialog.SIZE_COLUMN, "1.43 MB"
            ),
            1_500_000,
        )
        self.assertEqual(
            FileManagerDialog.sort_value_for_column(
                self.detail, FileManagerDialog.LINE_COUNT_COLUMN, "1,234"
            ),
            1234,
        )
        self.assertEqual(
            FileManagerDialog.sort_value_for_column(
                self.detail, FileManagerDialog.RESOLUTION_COLUMN, "1920 × 1080"
            ),
            1920 * 1080,
        )

    def test_duration_and_fps_are_sorted_numerically(self) -> None:
        self.assertEqual(
            FileManagerDialog.sort_value_for_column(
                self.detail, FileManagerDialog.DURATION_COLUMN, "01:06"
            ),
            65.5,
        )
        self.assertEqual(
            FileManagerDialog.sort_value_for_column(
                self.detail, FileManagerDialog.FPS_COLUMN, "29.97 fps"
            ),
            29.97,
        )


if __name__ == "__main__":
    unittest.main()

