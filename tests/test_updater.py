from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kicad_parts_collectors.updater import UpdateError, _release_asset, _verify_digest, is_newer_version, install_downloaded_update


class UpdaterTests(unittest.TestCase):
    def test_update_script_does_not_define_kicad_appimage_variable(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch("kicad_parts_collectors.updater.tempfile.gettempdir", return_value=temp_dir), \
             patch("kicad_parts_collectors.updater.sys.platform", "win32"), \
             patch("kicad_parts_collectors.updater.subprocess.Popen"):
            install_downloaded_update(Path(temp_dir) / "new.exe", Path(temp_dir) / "app.exe")
            script = (Path(temp_dir) / "KiCadPartsCollector_update.cmd").read_text(encoding="utf-8")
            self.assertNotIn("APPDIR", script)
            self.assertIn('start "" /D "%KPC_UPDATE_DIR%" "%DST%"', script)

    def test_version_compare_uses_numeric_parts(self) -> None:
        self.assertTrue(is_newer_version("v1.2.0", "1.1.9"))
        self.assertTrue(is_newer_version("1.0.10", "1.0.2"))
        self.assertFalse(is_newer_version("1.0.0", "1.0.0"))

    def test_release_asset_prefers_named_windows_exe(self) -> None:
        asset = _release_asset(
            [
                {"name": "Other.exe", "browser_download_url": "https://example.com/other.exe"},
                {"name": "KiCadPartsCollector.exe", "browser_download_url": "https://example.com/app.exe", "digest": "sha256:abc"},
            ],
            platform="win32",
        )

        self.assertIsNotNone(asset)
        self.assertEqual("KiCadPartsCollector.exe", asset.name)
        self.assertEqual("https://example.com/app.exe", asset.url)

    def test_release_asset_prefers_named_macos_dmg(self) -> None:
        asset = _release_asset(
            [
                {"name": "KiCadPartsCollector.exe", "browser_download_url": "https://example.com/app.exe"},
                {"name": "KiCadPartsCollector.app.zip", "browser_download_url": "https://example.com/app.zip"},
                {"name": "KiCadPartsCollector.dmg", "browser_download_url": "https://example.com/app.dmg"},
            ],
            platform="darwin",
        )

        self.assertIsNotNone(asset)
        self.assertEqual("KiCadPartsCollector.dmg", asset.name)
        self.assertEqual("https://example.com/app.dmg", asset.url)

    def test_verify_digest_rejects_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "download.exe"
            path.write_bytes(b"content")
            digest = "sha256:" + hashlib.sha256(b"other").hexdigest()

            with self.assertRaises(UpdateError):
                _verify_digest(path, digest)


if __name__ == "__main__":
    unittest.main()
