import csv
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from dsg_app.media_analyzer import analyze_scan_result, export_media_csv, export_media_json
from dsg_app.models import FilterSettings
from dsg_app.scanner import DirectoryScanner


class MediaAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "sample"
        self.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_image_metadata_and_non_images(self):
        Image.new("RGB", (1920, 1080), "blue").save(self.root / "header.png")
        (self.root / "notes.txt").write_text("not an image", encoding="utf-8")
        result = DirectoryScanner(FilterSettings()).scan(self.root)

        records = analyze_scan_result(result)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].resolution, "1920 × 1080")
        self.assertEqual(records[0].aspect_ratio, "16:9")
        self.assertEqual(records[0].format, "PNG")

    def test_broken_image_is_reported_without_stopping(self):
        (self.root / "broken.jpg").write_bytes(b"not a jpeg")
        result = DirectoryScanner(FilterSettings()).scan(self.root)

        records = analyze_scan_result(result)

        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].error)
        self.assertEqual(records[0].resolution, "")

    def test_csv_and_json_export(self):
        Image.new("RGB", (800, 600), "white").save(self.root / "photo.jpg")
        result = DirectoryScanner(FilterSettings()).scan(self.root)
        records = analyze_scan_result(result)
        csv_path = Path(self.temp.name) / "report.csv"
        json_path = Path(self.temp.name) / "report.json"

        export_media_csv(records, csv_path)
        export_media_json(records, self.root, json_path)

        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(rows[0]["resolution"], "800 × 600")
        self.assertEqual(payload["image_count"], 1)
        self.assertFalse(payload["gps_exported"])


if __name__ == "__main__":
    unittest.main()
