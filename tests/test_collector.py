from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from kicad_parts_collectors.collector import (
    CollectorError,
    build_install_plan,
    install_zip,
    install_zip_directory,
    process_watch_folder,
    remove_library_entries,
    scan_library,
    summarize_items,
    WatchFolders,
)


def symbol_library_text(name: str, value: str | None = None) -> str:
    if value is None:
        value = name
    return (
        f'(kicad_symbol_lib (version 20211014) (generator test)\n'
        f'  (symbol "{name}" (in_bom yes) (on_board yes)\n'
        f'    (property "Footprint" "{name}" (at 0 0 0))\n'
        f'    (property "Value" "{value}" (at 0 0 0))\n'
        f'  )\n'
        f')\n'
    )


def symbol_library_with_footprint_text(name: str, value: str, footprint: str) -> str:
    return (
        f'(kicad_symbol_lib (version 20211014) (generator test)\n'
        f'  (symbol "{name}" (in_bom yes) (on_board yes)\n'
        f'    (property "Footprint" "{footprint}" (at 0 0 0))\n'
        f'    (property "Value" "{value}" (at 0 0 0))\n'
        f'  )\n'
        f')\n'
    )


def footprint_text(model_name: str) -> str:
    return (
        f'(footprint "OriginalFootprint"\n'
        f'  (model {model_name}\n'
        f'    (at (xyz 0 0 0))\n'
        f'    (scale (xyz 1 1 1))\n'
        f'    (rotate (xyz 0 0 0))\n'
        f'  )\n'
        f')\n'
    )


def module_text(model_name: str) -> str:
    return (
        f'(module "OriginalModule" (layer F.Cu)\n'
        f'  (fp_text value "OriginalModule" (at 0 0) (layer F.SilkS))\n'
        f'  (model {model_name}\n'
        f'    (at (xyz 0 0 0))\n'
        f'  )\n'
        f')\n'
    )


class CollectorTests(unittest.TestCase):
    def test_install_zip_sorts_kicad_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            zip_path = root / "VendorPart.zip"
            library_root = root / "library"
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            footprint_library = library_root / "hrobotics_decal_library.pretty"
            symbol_library.write_text('(kicad_symbol_lib (version 20211014) (generator test)\n)\n')
            footprint_library.mkdir()

            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("symbols/Vendor.kicad_sym", symbol_library_text("Vendor"))
                archive.writestr("Vendor.pretty/Part.kicad_mod", footprint_text("Part.step"))
                archive.writestr("models/Part.step", "step")
                archive.writestr("notes.txt", "ignored")

            items = install_zip(zip_path, library_root)

            self.assertEqual({"symbol": 1, "footprint": 1, "3d_model": 1}, summarize_items(items))
            merged_symbol = symbol_library.read_text()
            self.assertIn('(symbol "Vendor"', merged_symbol)
            self.assertIn('(property "Footprint" "hrobotics_decal_library:Vendor"', merged_symbol)
            footprint = (footprint_library / "Vendor.kicad_mod").read_text()
            self.assertIn('(footprint "Vendor"', footprint)
            self.assertIn(f'(model "{(library_root / "3dmodels" / "Vendor.step").resolve().as_posix()}"', footprint)
            self.assertEqual("step", (library_root / "3dmodels" / "Vendor.step").read_text())

    def test_ultra_librarian_package_uses_part_folder_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            zip_path = root / "LIB_53261-0271.zip"
            library_root = root / "library"
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            footprint_library = library_root / "hrobotics_decal_library.pretty"
            symbol_library.write_text('(kicad_symbol_lib (version 20211014) (generator test)\n)\n')
            footprint_library.mkdir()

            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("53261-0271/KiCad/53261-0271.kicad_sym", symbol_library_text("53261-0271"))
                archive.writestr("53261-0271/KiCad/532610271.kicad_mod", module_text("53261-0271.stp"))
                archive.writestr("53261-0271/3D/53261-0271.stp", "step")
                archive.writestr("53261-0271/EAGLE/53261-0271.lbr", "ignored")

            items = install_zip(zip_path, library_root)

            self.assertEqual({"symbol": 1, "footprint": 1, "3d_model": 1}, summarize_items(items))
            merged_symbol = symbol_library.read_text()
            self.assertIn('(symbol "53261-0271"', merged_symbol)
            self.assertIn('(property "Footprint" "hrobotics_decal_library:53261-0271"', merged_symbol)
            footprint = (footprint_library / "53261-0271.kicad_mod").read_text()
            self.assertIn('(module "53261-0271"', footprint)
            self.assertIn('(fp_text value "53261-0271"', footprint)
            self.assertIn(f'(model "{(library_root / "3dmodels" / "53261-0271.stp").resolve().as_posix()}"', footprint)
            self.assertEqual("step", (library_root / "3dmodels" / "53261-0271.stp").read_text())

    def test_multiple_step_files_require_matching_model_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            zip_path = root / "Ambiguous3d.zip"
            library_root = root / "library"
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            footprint_library = library_root / "hrobotics_decal_library.pretty"
            symbol_library.write_text('(kicad_symbol_lib (version 20211014) (generator test)\n)\n')
            footprint_library.mkdir()

            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("Part.kicad_sym", symbol_library_text("Part"))
                archive.writestr("Part.kicad_mod", footprint_text("Unknown.step"))
                archive.writestr("First.step", "first")
                archive.writestr("Second.step", "second")

            with self.assertRaises(CollectorError):
                install_zip(zip_path, library_root)

    def test_multiple_footprints_require_matching_symbol_property(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            zip_path = root / "Ambiguous.zip"
            library_root = root / "library"
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            footprint_library = library_root / "hrobotics_decal_library.pretty"
            symbol_library.write_text('(kicad_symbol_lib (version 20211014) (generator test)\n)\n')
            footprint_library.mkdir()

            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("Ambiguous.kicad_sym", symbol_library_text("Unknown"))
                archive.writestr("First.kicad_mod", "first")
                archive.writestr("Second.kicad_mod", "second")

            with self.assertRaises(CollectorError):
                install_zip(zip_path, library_root)

    def test_value_property_is_used_for_normalized_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            zip_path = root / "ValueName.zip"
            library_root = root / "library"
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            footprint_library = library_root / "hrobotics_decal_library.pretty"
            symbol_library.write_text('(kicad_symbol_lib (version 20211014) (generator test)\n)\n')
            footprint_library.mkdir()

            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("ValueName.kicad_sym", symbol_library_text("W25Q128JVSJQ", "W25Q128JVSIQ"))
                archive.writestr("DifferentName.kicad_mod", module_text("DifferentStep.stp"))
                archive.writestr("DifferentStep.stp", "step")

            install_zip(zip_path, library_root)

            merged_symbol = symbol_library.read_text()
            footprint = (footprint_library / "W25Q128JVSIQ.kicad_mod").read_text()
            self.assertIn('(property "Footprint" "hrobotics_decal_library:W25Q128JVSIQ"', merged_symbol)
            self.assertIn('(module "W25Q128JVSIQ"', footprint)
            self.assertTrue((library_root / "3dmodels" / "W25Q128JVSIQ.stp").exists())

    def test_single_footprint_package_links_wildcard_symbol_footprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            zip_path = root / "Wildcard.zip"
            library_root = root / "library"
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            footprint_library = library_root / "hrobotics.pretty"
            symbol_library.write_text('(kicad_symbol_lib (version 20211014) (generator test)\n)\n')
            footprint_library.mkdir()

            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("CLF7045.kicad_sym", symbol_library_with_footprint_text("CLF7045NIT-220M-D", "CLF7045NIT-220M-D", "CLF7045_*"))
                archive.writestr("CLF7045__.kicad_mod", module_text("CLF7045NIT-220M-D.stp"))
                archive.writestr("CLF7045NIT-220M-D.stp", "step")

            install_zip(zip_path, library_root)

            merged_symbol = symbol_library.read_text()
            self.assertIn('(property "Footprint" "hrobotics:CLF7045NIT-220M-D"', merged_symbol)
            self.assertTrue((footprint_library / "CLF7045NIT-220M-D.kicad_mod").exists())

    def test_model_path_with_spaces_is_quoted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="path with spaces ") as temp_dir:
            root = Path(temp_dir)
            zip_path = root / "SpacedPath.zip"
            library_root = root / "library"
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            footprint_library = library_root / "hrobotics.pretty"
            symbol_library.write_text('(kicad_symbol_lib (version 20211014) (generator test)\n)\n')
            footprint_library.mkdir()

            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("Part.kicad_sym", symbol_library_text("Part"))
                archive.writestr("Part.kicad_mod", module_text("Part.step"))
                archive.writestr("Part.step", "step")

            install_zip(zip_path, library_root)

            footprint = (footprint_library / "Part.kicad_mod").read_text()
            model_path = (library_root / "3dmodels" / "Part.step").resolve().as_posix()
            self.assertIn(f'(model "{model_path}"', footprint)

    def test_scan_library_reports_link_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "library"
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            footprint_library = library_root / "hrobotics.pretty"
            model_path = library_root / "3dmodels" / "Linked.step"
            footprint_library.mkdir()
            model_path.parent.mkdir()
            model_path.write_text("step")
            symbol_library.write_text(
                '(kicad_symbol_lib (version 20211014) (generator test)\n'
                '  (symbol "Linked" (in_bom yes) (on_board yes)\n'
                '    (property "Value" "Linked" (at 0 0 0))\n'
                '    (property "Footprint" "hrobotics:Linked" (at 0 0 0))\n'
                '  )\n'
                ')\n'
            )
            (footprint_library / "Linked.kicad_mod").write_text(
                f'(module "Linked" (layer F.Cu)\n'
                f'  (model "{model_path.resolve().as_posix()}")\n'
                f')\n'
            )

            entries = scan_library(library_root)

            self.assertEqual(1, len(entries))
            self.assertEqual("Linked", entries[0].symbol)
            self.assertTrue(entries[0].footprint_ok)
            self.assertTrue(entries[0].model_ok)

    def test_remove_library_entries_deletes_symbol_and_internal_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "library"
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            footprint_library = library_root / "hrobotics.pretty"
            model_path = library_root / "3dmodels" / "RemoveMe.step"
            footprint_library.mkdir()
            model_path.parent.mkdir()
            model_path.write_text("step")
            symbol_library.write_text(
                '(kicad_symbol_lib (version 20211014) (generator test)\n'
                '  (symbol "RemoveMe" (in_bom yes) (on_board yes)\n'
                '    (property "Value" "RemoveMe" (at 0 0 0))\n'
                '    (property "Footprint" "hrobotics:RemoveMe" (at 0 0 0))\n'
                '  )\n'
                ')\n'
            )
            footprint_path = footprint_library / "RemoveMe.kicad_mod"
            footprint_path.write_text(
                f'(module "RemoveMe" (layer F.Cu)\n'
                f'  (model "{model_path.resolve().as_posix()}")\n'
                f')\n'
            )

            result = remove_library_entries(library_root, ["RemoveMe"])

            self.assertEqual(1, result.symbols)
            self.assertEqual(1, result.footprints)
            self.assertEqual(1, result.models)
            self.assertNotIn("RemoveMe", symbol_library.read_text())
            self.assertFalse(footprint_path.exists())
            self.assertFalse(model_path.exists())

    def test_remove_library_entries_deletes_orphan_assets_by_symbol_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "library"
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            footprint_library = library_root / "hrobotics.pretty"
            model_path = library_root / "3dmodels" / "53261-0271.stp"
            footprint_library.mkdir()
            model_path.parent.mkdir()
            model_path.write_text("step")
            symbol_library.write_text(
                '(kicad_symbol_lib (version 20211014) (generator test)\n'
                '  (symbol "53261-0271" (in_bom yes) (on_board yes)\n'
                '    (property "Value" "53261-0271" (at 0 0 0))\n'
                '    (property "Footprint" "532610271" (at 0 0 0))\n'
                '  )\n'
                ')\n'
            )

            result = remove_library_entries(library_root, ["53261-0271"])

            self.assertEqual(1, result.symbols)
            self.assertEqual(1, result.models)
            self.assertFalse(model_path.exists())

    def test_install_zip_directory_continues_after_failed_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            zip_dir = root / "zips"
            library_root = root / "library"
            zip_dir.mkdir()
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            footprint_library = library_root / "hrobotics.pretty"
            symbol_library.write_text('(kicad_symbol_lib (version 20211014) (generator test)\n)\n')
            footprint_library.mkdir()

            with zipfile.ZipFile(zip_dir / "A_OK.zip", "w") as archive:
                archive.writestr("A.kicad_sym", symbol_library_text("A"))
                archive.writestr("A.kicad_mod", module_text("A.step"))
                archive.writestr("A.step", "step")

            with zipfile.ZipFile(zip_dir / "B_FAIL.zip", "w") as archive:
                archive.writestr("readme.txt", "ignored")

            results = install_zip_directory(zip_dir, library_root)

            self.assertEqual(2, len(results))
            self.assertTrue(results[0].ok)
            self.assertFalse(results[1].ok)
            self.assertTrue((footprint_library / "A.kicad_mod").exists())

    def test_process_watch_folder_installs_and_moves_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            incoming = root / "incoming_zips"
            processed = root / "processed_zips"
            library_root = root / "library"
            incoming.mkdir()
            processed.mkdir()
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            footprint_library = library_root / "hrobotics.pretty"
            symbol_library.write_text('(kicad_symbol_lib (version 20211014) (generator test)\n)\n')
            footprint_library.mkdir()

            zip_path = incoming / "Auto.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("Auto.kicad_sym", symbol_library_text("Auto"))
                archive.writestr("Auto.kicad_mod", module_text("Auto.step"))
                archive.writestr("Auto.step", "step")

            results = process_watch_folder(library_root, WatchFolders(incoming, processed))

            self.assertEqual(1, len(results))
            self.assertTrue(results[0].ok)
            self.assertFalse(zip_path.exists())
            self.assertTrue((processed / "Auto.zip").exists())
            self.assertTrue((footprint_library / "Auto.kicad_mod").exists())

    def test_existing_file_blocks_install(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            zip_path = root / "Part.zip"
            library_root = root / "library"
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            footprint_library = library_root / "hrobotics_decal_library.pretty"
            symbol_library.parent.mkdir(parents=True)
            symbol_library.write_text('(kicad_symbol_lib (version 20211014) (generator test)\n)\n')
            footprint_library.mkdir()
            (footprint_library / "Part.kicad_mod").write_text("existing")

            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("Part.kicad_sym", symbol_library_text("Part"))
                archive.writestr("Part.kicad_mod", "new")

            with self.assertRaises(CollectorError):
                build_install_plan(zip_path, library_root)

            self.assertEqual("existing", (footprint_library / "Part.kicad_mod").read_text())

    def test_zip_slip_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            zip_path = root / "Unsafe.zip"
            library_root = root / "library"
            library_root.mkdir()
            (library_root / "hrobotics_symbol_library.kicad_sym").write_text('(kicad_symbol_lib (version 20211014) (generator test)\n)\n')
            (library_root / "hrobotics_decal_library.pretty").mkdir()

            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("../Unsafe.kicad_sym", "bad")

            with self.assertRaises(CollectorError):
                build_install_plan(zip_path, library_root)


if __name__ == "__main__":
    unittest.main()
