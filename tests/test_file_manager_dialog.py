import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QUrl

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


if __name__ == "__main__":
    unittest.main()
