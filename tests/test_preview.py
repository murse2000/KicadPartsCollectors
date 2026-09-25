import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kicad_parts_collectors.collector import CollectorError, LibraryEntry
from kicad_parts_collectors.preview import _preview_board, render_preview


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.library = self.root / "parts.pretty"
        self.library.mkdir()
        self.footprint = self.library / "Part.kicad_mod"
        self.model = self.root / "part.step"
        self.model.write_text("STEP")
        self.source = ('(footprint "Part" (layer "F.Cu") '
                       '(model "../part.step" (offset (xyz 1 2 3)) '
                       '(scale (xyz 1 1 1)) (rotate (xyz 0 0 90))))')
        self.footprint.write_text(self.source)
        self.entry = LibraryEntry("Part", "Part", "parts:Part", "", "", {}, True, "../part.step", True)

    def test_relative_model_is_resolved_without_changing_original(self):
        board = _preview_board(self.footprint, self.root, Path("kicad-cli"))
        self.assertIn(self.model.as_posix(), board)
        self.assertIn("(offset (xyz 1 2 3))", board)
        self.assertIn("(rotate (xyz 0 0 90))", board)
        self.assertEqual(self.footprint.read_text(), self.source)

    def test_missing_model_is_reported_before_rendering(self):
        self.model.unlink()
        with self.assertRaisesRegex(CollectorError, "3D 모델 파일"):
            _preview_board(self.footprint, self.root, Path("kicad-cli"))

    def test_project_variable_is_resolved(self):
        self.footprint.write_text(self.source.replace("../part.step", "${KIPRJMOD}/part.step"))
        self.assertIn(self.model.as_posix(), _preview_board(self.footprint, self.root, Path("kicad-cli")))

    def test_vrml_only_is_reported_instead_of_blank_model(self):
        self.model.unlink()
        self.model.with_suffix(".wrl").write_text("VRML")
        self.footprint.write_text(self.source.replace("part.step", "part.wrl"))
        with self.assertRaisesRegex(CollectorError, "STEP 모델"):
            _preview_board(self.footprint, self.root, Path("kicad-cli"))

    def test_kicad8_reports_3d_requirement(self):
        with patch("kicad_parts_collectors.preview.find_kicad_cli", return_value=Path("kicad-cli")), \
             patch("kicad_parts_collectors.preview._run", return_value="8.0.9"):
            with self.assertRaisesRegex(CollectorError, "KiCad 9"):
                render_preview(self.root, self.entry, "3D")

    def test_glb_export_uses_temporary_board_and_no_board_body(self):
        calls = []

        def run(cli, *args):
            calls.append(args)
            if args == ("version",):
                return "9.0.7"
            self.assertEqual(args[:3], ("pcb", "export", "glb"))
            self.assertIn("--no-board-body", args)
            self.assertIn(self.model.as_posix(), Path(args[-1]).read_text())
            Path(args[args.index("--output") + 1]).write_bytes(b"glTF")
            return ""

        with patch("kicad_parts_collectors.preview.find_kicad_cli", return_value=Path("kicad-cli")), \
             patch("kicad_parts_collectors.preview._run", side_effect=run):
            self.assertEqual(render_preview(self.root, self.entry, "3D"), [("Part", b"glTF")])
        self.assertFalse(Path(calls[-1][-1]).exists())
        self.assertEqual(self.footprint.read_text(), self.source)

    def test_missing_footprint_has_clear_error(self):
        self.footprint.unlink()
        with patch("kicad_parts_collectors.preview.find_kicad_cli", return_value=Path("kicad-cli")):
            with self.assertRaisesRegex(CollectorError, "풋프린트 파일"):
                render_preview(self.root, self.entry, "풋프린트")

    def test_symbol_preview_omits_url_fields_only_in_temporary_copy(self):
        source = '(kicad_symbol_lib (symbol "Part" (property "Value" "Part") (property "Datasheet" "https://example.com/long-url")))'
        library = self.root / "parts.kicad_sym"
        library.write_text(source)

        def run(cli, *args):
            copied = Path(args[-1]).read_text()
            self.assertIn('(property "Value" "Part")', copied)
            self.assertNotIn('https://', copied)
            destination = Path(args[args.index("--output") + 1])
            (destination / "Part.svg").write_text('<svg/>')
            return ""

        with patch("kicad_parts_collectors.preview.find_kicad_cli", return_value=Path("kicad-cli")), \
             patch("kicad_parts_collectors.preview._run", side_effect=run):
            self.assertEqual(render_preview(self.root, self.entry, "심볼"), [("Part", b'<svg/>')])
        self.assertEqual(library.read_text(), source)
