import tempfile
import unittest
from pathlib import Path

from dsg_app.settings_presets import (
    MAX_FAVORITES, builtin_presets, export_presets_csv, import_presets_csv,
    merge_presets, normalize_presets,
)


class SettingsPresetTests(unittest.TestCase):
    def test_builtin_presets_have_memos_and_favorite_limit(self) -> None:
        presets = builtin_presets()
        self.assertEqual(len(presets), 6)
        self.assertTrue(all(item["memo"] for item in presets))
        self.assertEqual(sum(bool(item["favorite"]) for item in presets), MAX_FAVORITES)

    def test_normalize_limits_favorites_to_five(self) -> None:
        presets = builtin_presets()
        for item in presets:
            item["favorite"] = True
        normalized = normalize_presets(presets)
        self.assertEqual(sum(bool(item["favorite"]) for item in normalized), MAX_FAVORITES)

    def test_csv_round_trip_preserves_memo_and_safe_organizer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            preset = builtin_presets()[0]
            preset["memo"] = "毎週使う設定, カンマと改行\nも保持"
            preset["organizer"]["source_action"] = "delete"
            path = Path(temporary) / "presets.csv"
            export_presets_csv(path, [preset])
            loaded = import_presets_csv(path)
        self.assertEqual(loaded[0]["memo"], preset["memo"])
        self.assertNotIn("source_action", loaded[0]["organizer"])

    def test_import_rejects_missing_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.csv"
            path.write_text("name,memo\n写真,画像用\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "必要な列"):
                import_presets_csv(path)

    def test_merge_updates_same_name_and_keeps_builtin_flag(self) -> None:
        existing = builtin_presets()
        incoming = [dict(existing[0], memo="CSVから更新", builtin=False)]
        merged = merge_presets(existing, incoming)
        target = next(item for item in merged if item["name"] == existing[0]["name"])
        self.assertEqual(target["memo"], "CSVから更新")
        self.assertTrue(target["builtin"])

    def test_csv_neutralizes_formula_and_restores_original_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            preset = builtin_presets()[0]
            preset["name"] = "=危険な数式"
            path = Path(temporary) / "presets.csv"
            export_presets_csv(path, [preset])
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("'=危険な数式", text)
            loaded = import_presets_csv(path)
        self.assertEqual(loaded[0]["name"], "=危険な数式")


if __name__ == "__main__":
    unittest.main()
