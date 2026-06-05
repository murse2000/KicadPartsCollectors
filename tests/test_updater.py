from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from kicad_parts_collectors.updater import UpdateError, _release_asset, _verify_digest, is_newer_version


class UpdaterTests(unittest.TestCase):
    def test_version_compare_uses_numeric_parts(self) -> None:
        self.assertTrue(is_newer_version("v1.2.0", "1.1.9"))
        self.assertTrue(is_newer_version("1.0.10", "1.0.2"))
        self.assertFalse(is_newer_version("1.0.0", "1.0.0"))

    def test_release_asset_prefers_named_exe(self) -> None:
        asset = _release_asset(
            [
                {"name": "Other.exe", "browser_download_url": "https://example.com/other.exe"},
                {"name": "KiCadPartsCollector.exe", "browser_download_url": "https://example.com/app.exe", "digest": "sha256:abc"},
            ]
        )

        self.assertIsNotNone(asset)
        self.assertEqual("KiCadPartsCollector.exe", asset.name)
        self.assertEqual("https://example.com/app.exe", asset.url)

    def test_verify_digest_rejects_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "download.exe"
            path.write_bytes(b"content")
            digest = "sha256:" + hashlib.sha256(b"other").hexdigest()

            with self.assertRaises(UpdateError):
                _verify_digest(path, digest)


if __name__ == "__main__":
    unittest.main()
