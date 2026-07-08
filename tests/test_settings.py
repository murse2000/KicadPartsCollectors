from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kicad_parts_collectors.settings import AppSettings, load_settings, save_settings


class SettingsTests(unittest.TestCase):
    def test_save_and_load_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"

            save_settings(
                AppSettings(
                    library_root="C:/Work/099. Etc/test",
                    theme="darkly",
                    incoming_folder="C:/watch/incoming",
                    processed_folder="C:/watch/processed",
                ),
                path,
            )
            settings = load_settings(path)

            self.assertEqual("C:/Work/099. Etc/test", settings.library_root)
            self.assertEqual("darkly", settings.theme)
            self.assertEqual("C:/watch/incoming", settings.incoming_folder)
            self.assertEqual("C:/watch/processed", settings.processed_folder)

    def test_invalid_settings_file_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text("{", encoding="utf-8")

            settings = load_settings(path)

            self.assertEqual("", settings.library_root)
            self.assertEqual("flatly", settings.theme)
            self.assertEqual("", settings.incoming_folder)
            self.assertEqual("", settings.processed_folder)


if __name__ == "__main__":
    unittest.main()
