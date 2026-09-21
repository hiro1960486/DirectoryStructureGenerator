import csv
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from dsg_app.file_inspector import (
    FileDetail, export_details_csv, export_details_json, inspect_scan_result,
)
from dsg_app.models import FilterSettings
from dsg_app.scanner import DirectoryScanner


class FileInspectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_general_image_and_svg_metadata(self):
        (self.root / "code.py").write_text("one\ntwo\nthree", encoding="utf-8")
        Image.new("RGBA", (640, 480), "blue").save(self.root / "image.png")
        (self.root / "vector.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080"></svg>',
            encoding="utf-8",
        )
        result = DirectoryScanner(FilterSettings()).scan(self.root)

        details = inspect_scan_result(result, include_lines=True, include_sha256=True)
        by_name = {detail.name: detail for detail in details}

        self.assertEqual(by_name["code.py"].line_count, 3)
        self.assertEqual(len(by_name["code.py"].sha256), 64)
        self.assertEqual(by_name["image.png"].resolution, "640 × 480")
        self.assertEqual(by_name["image.png"].aspect_ratio, "4:3")
        self.assertEqual(by_name["image.png"].color_mode, "RGBA")
        self.assertEqual(by_name["vector.svg"].resolution, "1920 × 1080")
        self.assertEqual(by_name["vector.svg"].image_format, "SVG")

    def test_detail_report_exports(self):
        (self.root / "notes.txt").write_text("hello", encoding="utf-8")
        details = inspect_scan_result(DirectoryScanner(FilterSettings()).scan(self.root))
        csv_path = Path(self.temp.name) / "details.csv"
        json_path = Path(self.temp.name) / "details.json"

        export_details_csv(details, csv_path)
        export_details_json(details, self.root, json_path)

        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(rows[0]["name"], "notes.txt")
        self.assertEqual(payload["file_count"], 1)

    def test_video_display_fields(self):
        detail = FileDetail(
            name="sample.mp4", relative_path="media/sample.mp4", full_path="sample.mp4",
            category="video", extension=".mp4", file_size=100, modified="", created="",
            permissions="-rw-r--r--", readonly=False, video_format="MP4", width=1920,
            height=1080, duration_seconds=65.2,
        )

        self.assertTrue(detail.is_video)
        self.assertEqual(detail.media_format, "MP4")
        self.assertEqual(detail.resolution, "1920 × 1080")
        self.assertEqual(detail.duration, "01:05")


if __name__ == "__main__":
    unittest.main()
