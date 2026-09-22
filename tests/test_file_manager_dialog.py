import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QUrl

from dsg_app.file_inspector import FileDetail
from dsg_app.file_manager_dialog import FileManagerDialog, first_dropped_directory


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
