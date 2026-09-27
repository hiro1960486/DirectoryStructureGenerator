from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from dsg_app import config_manager
from dsg_app.config_manager import default_config, load_config
from dsg_app.external_tools_dialog import ExternalToolsDialog


class ExternalToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_new_config_has_empty_companion_tool_paths(self) -> None:
        self.assertEqual(
            default_config()["external_tools"],
            {"preset_manager": "", "rename_wizard": ""},
        )

    def test_older_config_loads_with_missing_companion_path_defaulted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(json.dumps({
                "source": "C:/source",
                "external_tools": {"preset_manager": "C:/tools/PresetManager.exe"},
            }), encoding="utf-8")
            with patch.object(config_manager, "config_path", return_value=path):
                config = load_config()

        self.assertEqual(config["source"], "C:/source")
        self.assertEqual(config["external_tools"], {
            "preset_manager": "C:/tools/PresetManager.exe",
            "rename_wizard": "",
        })

    def test_browse_saves_the_selected_executable_path(self) -> None:
        config = default_config()
        dialog = ExternalToolsDialog(config)
        selected = "C:/Apps/Rename Wizard/RenameWizard.exe"
        with patch.object(QFileDialog, "getOpenFileName", return_value=(selected, "")):
            with patch("dsg_app.external_tools_dialog.save_config") as save:
                dialog.choose_executable("rename_wizard")

        self.assertEqual(dialog.path_edits["rename_wizard"].text(), selected)
        self.assertEqual(config["external_tools"]["rename_wizard"], selected)
        save.assert_called_once_with(config)
        with patch("dsg_app.external_tools_dialog.save_config"):
            dialog.close()

    def test_launch_uses_detached_process_with_executable_folder_as_working_directory(self) -> None:
        config = default_config()
        dialog = ExternalToolsDialog(config)
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "Preset Manager.exe"
            executable.touch()
            dialog.path_edits["preset_manager"].setText(str(executable))
            with patch("dsg_app.external_tools_dialog.save_config"):
                with patch.object(QProcess, "startDetached", return_value=(True, 123)) as start:
                    dialog.launch_tool("preset_manager")

        start.assert_called_once_with(str(executable.resolve()), [], str(executable.parent.resolve()))
        with patch("dsg_app.external_tools_dialog.save_config"):
            dialog.close()

    def test_missing_executable_is_reported_without_launching(self) -> None:
        config = default_config()
        dialog = ExternalToolsDialog(config)
        dialog.path_edits["rename_wizard"].setText("Z:/missing/RenameWizard.exe")
        with patch("dsg_app.external_tools_dialog.save_config"):
            with patch.object(QMessageBox, "warning") as warning:
                with patch.object(QProcess, "startDetached") as start:
                    dialog.launch_tool("rename_wizard")

        warning.assert_called_once()
        start.assert_not_called()
        with patch("dsg_app.external_tools_dialog.save_config"):
            dialog.close()


if __name__ == "__main__":
    unittest.main()
