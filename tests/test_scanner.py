import tempfile
import unittest
from pathlib import Path

from dsg_app.models import FilterSettings
from dsg_app.scanner import DirectoryScanner


def names(result):
    found = []

    def visit(node):
        found.append(node.relative_path.as_posix())
        for child in node.children:
            visit(child)

    visit(result.root)
    return found


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_development_directories_are_excluded(self):
        (self.root / ".git" / "objects").mkdir(parents=True)
        (self.root / "node_modules").mkdir()
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("print('ok')", encoding="utf-8")
        result = DirectoryScanner(FilterSettings()).scan(self.root)
        self.assertIn("src/app.py", names(result))
        self.assertNotIn(".git", names(result))
        self.assertNotIn("node_modules", names(result))
        self.assertEqual(result.stats.excluded, 2)

    def test_extension_include_and_exclude_filters(self):
        (self.root / "keep.py").write_text("x", encoding="utf-8")
        (self.root / "skip.log").write_text("log", encoding="utf-8")
        (self.root / "skip.txt").write_text("text", encoding="utf-8")
        filters = FilterSettings(included_extensions=["py", "log"], excluded_extensions=[".log"])
        result = DirectoryScanner(filters).scan(self.root)
        self.assertIn("keep.py", names(result))
        self.assertNotIn("skip.log", names(result))
        self.assertNotIn("skip.txt", names(result))
        self.assertEqual(result.stats.files, 1)

    def test_max_depth_stops_recursion(self):
        level1 = self.root / "level1"
        level2 = level1 / "level2"
        level2.mkdir(parents=True)
        (level1 / "one.txt").write_text("1", encoding="utf-8")
        (level2 / "two.txt").write_text("2", encoding="utf-8")
        result = DirectoryScanner(FilterSettings(max_depth=1)).scan(self.root)
        self.assertIn("level1", names(result))
        self.assertNotIn("level1/one.txt", names(result))
        self.assertNotIn("level1/level2", names(result))

    def test_output_directory_can_be_excluded_automatically(self):
        output = self.root / "generated"
        output.mkdir()
        (output / "old.txt").write_text("old", encoding="utf-8")
        (self.root / "real.txt").write_text("real", encoding="utf-8")
        result = DirectoryScanner(FilterSettings(), excluded_absolute_paths=[output]).scan(self.root)
        self.assertIn("real.txt", names(result))
        self.assertNotIn("generated", names(result))


if __name__ == "__main__":
    unittest.main()
