import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dsg_app.file_inspector import FileDetail
from dsg_app.organizer import (
    CopyCancelled, build_copy_plans, execute_copy_plans, extension_was_changed,
    sanitize_filename,
)


def detail(path: Path, relative: str) -> FileDetail:
    return FileDetail(
        name=path.name,
        relative_path=relative,
        full_path=str(path),
        category="general",
        extension=path.suffix,
        file_size=path.stat().st_size,
        modified="2026-09-21 10:00:00",
        created="2026-09-21 09:00:00",
        permissions="-rw-r--r--",
        readonly=False,
    )


class OrganizerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.destination = self.root / "destination"
        (self.source / "docs").mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_copy_with_rename_does_not_change_source(self):
        original = self.source / "docs" / "old.txt"
        original.write_text("original data", encoding="utf-8")
        plans = build_copy_plans(
            [detail(original, "docs/old.txt")], self.destination,
            "new_name.txt", keep_subfolders=True, collision="number",
        )

        results = execute_copy_plans(plans, self.destination)

        copied = self.destination / "docs" / "new_name.txt"
        self.assertTrue(original.exists())
        self.assertEqual(original.read_text(encoding="utf-8"), "original data")
        self.assertEqual(copied.read_text(encoding="utf-8"), "original data")
        self.assertEqual(results[0].status, "コピー完了")
        self.assertTrue((self.destination / "_DirectoryStructureGenerator_copy_log.csv").exists())

    def test_delete_source_only_after_verified_copy(self):
        original = self.source / "docs" / "move.txt"
        original.write_text("verified data", encoding="utf-8")
        plans = build_copy_plans(
            [detail(original, "docs/move.txt")], self.destination,
            "moved.txt", keep_subfolders=False, collision="number",
        )

        results = execute_copy_plans(plans, self.destination, delete_sources=True)

        copied = self.destination / "moved.txt"
        self.assertFalse(original.exists())
        self.assertEqual(copied.read_text(encoding="utf-8"), "verified data")
        self.assertEqual(results[0].status, "コピー完了・元ファイル削除")

    def test_size_mismatch_keeps_source(self):
        original = self.source / "docs" / "important.txt"
        original.write_text("do not delete", encoding="utf-8")
        plans = build_copy_plans(
            [detail(original, "docs/important.txt")], self.destination,
            "copy.txt", keep_subfolders=False, collision="number",
        )

        def bad_copy(_source: Path, destination: Path) -> None:
            destination.write_text("x", encoding="utf-8")

        with patch("dsg_app.organizer.shutil.copy2", side_effect=bad_copy):
            results = execute_copy_plans(plans, self.destination, delete_sources=True)

        self.assertTrue(original.exists())
        self.assertEqual(results[0].status, "コピー完了・安全確認失敗")
        self.assertIn("サイズが一致しない", results[0].error)

    def test_skipped_file_is_never_deleted(self):
        original = self.source / "docs" / "same.txt"
        original.write_text("source", encoding="utf-8")
        self.destination.mkdir()
        (self.destination / "same.txt").write_text("existing", encoding="utf-8")
        plans = build_copy_plans(
            [detail(original, "docs/same.txt")], self.destination,
            "{name}", keep_subfolders=False, collision="skip",
        )

        execute_copy_plans(plans, self.destination, delete_sources=True)

        self.assertTrue(original.exists())
        self.assertEqual(plans[0].status, "既存のためスキップ")

    def test_extension_change_is_detected_case_insensitively(self):
        original = self.source / "docs" / "photo.PNG"
        original.write_text("image bytes", encoding="utf-8")
        changed = build_copy_plans(
            [detail(original, "docs/photo.PNG")], self.destination,
            "photo.jpg", keep_subfolders=False, collision="number",
        )[0]
        same = build_copy_plans(
            [detail(original, "docs/photo.PNG")], self.destination,
            "renamed.png", keep_subfolders=False, collision="number",
        )[0]

        self.assertTrue(extension_was_changed(changed))
        self.assertFalse(extension_was_changed(same))

    def test_collision_adds_number(self):
        original = self.source / "docs" / "same.txt"
        original.write_text("new", encoding="utf-8")
        self.destination.mkdir()
        (self.destination / "same.txt").write_text("existing", encoding="utf-8")

        plans = build_copy_plans(
            [detail(original, "docs/same.txt")], self.destination,
            "{name}", keep_subfolders=False, collision="number",
        )

        self.assertEqual(plans[0].destination.name, "same (1).txt")

    def test_windows_filename_is_sanitized(self):
        self.assertEqual(sanitize_filename('bad:name?.txt'), "bad_name_.txt")
        self.assertEqual(sanitize_filename("CON.txt"), "_CON.txt")

    def test_individual_name_override_keeps_original_extension(self):
        original = self.source / "docs" / "old.txt"
        original.write_text("original", encoding="utf-8")

        plans = build_copy_plans(
            [detail(original, "docs/old.txt")], self.destination, "{name}",
            keep_subfolders=False, collision="number",
            name_overrides={str(original): "わかりやすい名前"},
        )

        self.assertEqual(plans[0].destination.name, "わかりやすい名前.txt")

    def test_cancel_is_logged_without_copying(self):
        original = self.source / "docs" / "cancel.txt"
        original.write_text("keep", encoding="utf-8")
        plans = build_copy_plans(
            [detail(original, "docs/cancel.txt")], self.destination,
            "{name}", keep_subfolders=False, collision="number",
        )

        with self.assertRaises(CopyCancelled):
            execute_copy_plans(plans, self.destination, cancel_requested=lambda: True)

        self.assertTrue(original.exists())
        self.assertFalse((self.destination / "cancel.txt").exists())
        self.assertEqual(plans[0].status, "中止により未実行")
        self.assertTrue((self.destination / "_DirectoryStructureGenerator_copy_log.csv").exists())


if __name__ == "__main__":
    unittest.main()
