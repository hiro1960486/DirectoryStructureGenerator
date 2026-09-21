import csv
import json
import tempfile
import unittest
from pathlib import Path

from dsg_app.exporters import export_selected, tree_lines
from dsg_app.models import FilterSettings
from dsg_app.scanner import DirectoryScanner


class ExporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_all_export_formats(self):
        source = self.root / "sample"
        output = self.root / "output"
        (source / "docs").mkdir(parents=True)
        (source / "docs" / "readme.md").write_text("hello", encoding="utf-8")
        (source / "=formula.csv").write_text("safe", encoding="utf-8")
        result = DirectoryScanner(FilterSettings()).scan(source)
        created = export_selected(result, output, ["txt", "html", "csv", "json"])
        self.assertEqual(len(created), 4)
        self.assertTrue(all(path.exists() and path.stat().st_size > 0 for path in created))
        self.assertIn("docs/", "\n".join(tree_lines(result.root)))
        payload = json.loads((output / "sample_tree_data.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["statistics"]["files"], 2)
        self.assertEqual(payload["application"]["version"], "2.1.0")

    def test_csv_neutralizes_spreadsheet_formula(self):
        source = self.root / "sample"
        source.mkdir()
        (source / "=danger.txt").write_text("x", encoding="utf-8")
        output = self.root / "output"
        result = DirectoryScanner(FilterSettings()).scan(source)
        export_selected(result, output, ["csv"])
        with (output / "sample_file_list.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[1]["name"], "'=danger.txt")


if __name__ == "__main__":
    unittest.main()
