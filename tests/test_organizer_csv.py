import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dsg_app.file_inspector import FileDetail
from dsg_app.organizer import (
    RESULT_COLUMNS, RESULT_LOG_NAME, CopyCancelled, build_copy_plans,
    classify_copy_error, execute_copy_plans, excel_hyperlink, windows_file_uri,
)


def detail(path: Path, relative: str) -> FileDetail:
    return FileDetail(
        name=path.name, relative_path=relative, full_path=str(path),
        category="general", extension=path.suffix, file_size=path.stat().st_size,
        modified="2026-09-23 10:00:00", created="2026-09-23 09:00:00",
        permissions="-rw-r--r--", readonly=False,
    )


class WindowsLinkTests(unittest.TestCase):
    def test_drive_path_is_percent_encoded_uri(self):
        self.assertEqual(
            windows_file_uri(r"c:\写真\2026 09"),
            "file:///C:/%E5%86%99%E7%9C%9F/2026%2009",
        )

    def test_unc_path_is_percent_encoded_uri(self):
        self.assertEqual(
            windows_file_uri(r"\\server\share\写真"),
            "file://server/share/%E5%86%99%E7%9C%9F",
        )

    def test_excel_formula_prefers_native_windows_path(self):
        self.assertEqual(
            excel_hyperlink(r"C:\写真\2026", "保存先を開く"),
            '=HYPERLINK("C:\\写真\\2026","保存先を開く")',
        )


class IntegratedCopyCsvTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.destination = self.root / "保存先 folder"
        self.source.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def read_rows(self):
        with (self.destination / RESULT_LOG_NAME).open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            return list(csv.DictReader(handle))

    def make_plan(self, name="写真.txt"):
        original = self.source / name
        original.write_text("data", encoding="utf-8")
        plans = build_copy_plans(
            [detail(original, name)], self.destination, "{name}", False, "number"
        )
        return original, plans

    def test_copy_csv_and_shortcut_are_created(self):
        original, plans = self.make_plan()
        execute_copy_plans(plans, self.destination)

        rows = self.read_rows()
        self.assertEqual(rows[0]["処理結果"], "コピー完了")
        self.assertEqual(rows[0]["元ファイル名"], "写真.txt")
        self.assertTrue(rows[0]["保存先を開く"].startswith("=HYPERLINK("))
        self.assertEqual(rows[0]["元サイズ"], "4")
        self.assertEqual(rows[0]["保存後サイズ"], "4")
        self.assertTrue((self.destination / "保存先を開く.url").exists())
        self.assertTrue((self.destination / original.name).exists())
        raw = (self.destination / RESULT_LOG_NAME).read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", raw)

    def test_append_has_only_one_header(self):
        _, first = self.make_plan("first.txt")
        execute_copy_plans(first, self.destination)
        _, second = self.make_plan("second.txt")
        execute_copy_plans(second, self.destination)
        raw = (self.destination / RESULT_LOG_NAME).read_text(encoding="utf-8-sig")
        self.assertEqual(raw.count("実行ID,実行日時,処理結果"), 1)
        self.assertEqual(len(self.read_rows()), 2)

    def test_legacy_log_is_preserved_before_new_schema(self):
        self.destination.mkdir()
        (self.destination / RESULT_LOG_NAME).write_text(
            "日時,元ファイル,コピー先,結果,エラー\nold,row,,,\n", encoding="utf-8-sig"
        )
        _, plans = self.make_plan("new.txt")
        execute_copy_plans(plans, self.destination)
        legacy = list(self.destination.glob("*_legacy_*.csv"))
        self.assertEqual(len(legacy), 1)
        with (self.destination / RESULT_LOG_NAME).open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            self.assertEqual(next(csv.reader(handle)), RESULT_COLUMNS)

    def test_error_row_is_written_and_source_is_kept(self):
        original, plans = self.make_plan("blocked.txt")
        with patch("dsg_app.organizer.shutil.copy2", side_effect=PermissionError("denied")):
            execute_copy_plans(plans, self.destination)
        row = self.read_rows()[0]
        self.assertEqual(row["処理結果"], "コピー失敗")
        self.assertEqual(row["エラー分類"], "ACCESS_DENIED")
        self.assertTrue(original.exists())

    def test_missing_source_is_logged_and_processing_continues(self):
        original, plans = self.make_plan("missing.txt")
        original.unlink()
        execute_copy_plans(plans, self.destination)
        self.assertEqual(self.read_rows()[0]["エラー分類"], "FILE_NOT_FOUND")

    def test_size_mismatch_never_deletes_source(self):
        original, plans = self.make_plan("important.txt")

        def bad_copy(_source, destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("x", encoding="utf-8")

        with patch("dsg_app.organizer.shutil.copy2", side_effect=bad_copy):
            execute_copy_plans(plans, self.destination, delete_sources=True)
        self.assertTrue(original.exists())
        self.assertEqual(self.read_rows()[0]["処理結果"], "コピー完了・安全確認失敗")

    def test_formula_like_filename_is_neutralized(self):
        _, plans = self.make_plan("=SUM(A1).txt")
        execute_copy_plans(plans, self.destination)
        self.assertTrue(self.read_rows()[0]["元ファイル名"].startswith("'="))

    def test_cancel_is_logged(self):
        original, plans = self.make_plan("cancel.txt")
        with self.assertRaises(CopyCancelled):
            execute_copy_plans(plans, self.destination, cancel_requested=lambda: True)
        self.assertEqual(self.read_rows()[0]["エラー分類"], "CANCELLED")
        self.assertTrue(original.exists())

    def test_cancel_after_first_copy_records_unexecuted_rows(self):
        first, first_plans = self.make_plan("first.txt")
        second, second_plans = self.make_plan("second.txt")
        plans = [*first_plans, *second_plans]
        checks = iter([False, True])
        with self.assertRaises(CopyCancelled):
            execute_copy_plans(plans, self.destination, cancel_requested=lambda: next(checks))
        rows = self.read_rows()
        self.assertEqual([row["処理結果"] for row in rows], ["コピー完了", "中止により未実行"])
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        self.assertTrue(plans[0].destination.exists())
        self.assertFalse(plans[1].destination.exists())

    def test_disk_full_copy_error_is_logged(self):
        original, plans = self.make_plan("disk-full.txt")
        error = OSError("disk full")
        error.errno = 28
        with patch("dsg_app.organizer.shutil.copy2", side_effect=error):
            execute_copy_plans(plans, self.destination)
        self.assertEqual(self.read_rows()[0]["エラー分類"], "DISK_FULL")
        self.assertTrue(original.exists())


class ErrorClassificationTests(unittest.TestCase):
    def test_disk_full_windows_error(self):
        exc = OSError("disk full")
        exc.winerror = 112
        self.assertEqual(classify_copy_error(exc), "DISK_FULL")


if __name__ == "__main__":
    unittest.main()
