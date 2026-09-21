import tempfile
import unittest
from pathlib import Path

from dsg_app.file_inspector import FileDetail
from dsg_app.organizer import CopyCancelled, build_copy_plans, execute_copy_plans, sanitize_filename


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
