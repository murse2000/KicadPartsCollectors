import json
import runpy
import sys
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

from kicad_parts_collectors import preview_server
from kicad_parts_collectors.collector import LibraryEntry


class PreviewServerTests(unittest.TestCase):
    def setUp(self):
        entry = LibraryEntry("Part", "Part", "parts:Part", "", "", {}, True, "", False)
        self.url = preview_server.preview_url(Path("."), entry)

    def tearDown(self):
        preview_server.release_preview(self.url)
        preview_server._server.shutdown()
        preview_server._server.server_close()
        preview_server._server = None

    def test_model_payload_is_served_to_embedded_view(self):
        with patch.object(preview_server, "render_preview", return_value=[("Part", b"glTF")]):
            with urllib.request.urlopen(self.url.replace("index.html", "model")) as response:
                self.assertEqual(json.load(response)["pages"][0]["data"], "Z2xURg==")

    def test_closed_preview_is_no_longer_accessible(self):
        preview_server.release_preview(self.url)
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(self.url)
        self.assertEqual(raised.exception.code, 404)
        raised.exception.close()

    def test_preview_mode_bypasses_normal_single_instance_startup(self):
        entrypoint = Path(__file__).resolve().parents[1] / "run_app.py"
        main = Mock()
        with patch.object(sys, "argv", [str(entrypoint), "--part-preview", self.url, "123", "Part"]), \
             patch.dict(sys.modules, {"kicad_parts_collectors.preview_window": types.SimpleNamespace(main=main)}):
            runpy.run_path(str(entrypoint), run_name="__main__")
        main.assert_called_once_with()
