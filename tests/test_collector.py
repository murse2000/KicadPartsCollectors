from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

import kicad_parts_collectors.collector as collector
from kicad_parts_collectors.collector import (
    CollectorError,
    add_missing_lcsc_properties,
    build_install_plan,
    install_zip,
    install_zip_directory,
    process_watch_folder,
    remove_library_entries,
    scan_library,
    summarize_items,
    update_library_entry,
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
            self.assertIn('(property "LCSC" ""', merged_symbol)
            footprint = (footprint_library / "Vendor.kicad_mod").read_text()
            self.assertIn('(footprint "Vendor"', footprint)
            self.assertIn(f'(model "{(library_root / "3dmodels" / "Vendor.step").resolve().as_posix()}"', footprint)
            self.assertEqual("step", (library_root / "3dmodels" / "Vendor.step").read_text())

    def test_add_missing_lcsc_properties_updates_existing_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "library"
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            symbol_library.write_text(
                '(kicad_symbol_lib (version 20211014) (generator test)\n'
                '  (symbol "MissingLcsc" (in_bom yes) (on_board yes)\n'
                '    (property "Value" "MissingLcsc" (at 0 0 0))\n'
                '  )\n'
                '  (symbol "ExistingLcsc" (in_bom yes) (on_board yes)\n'
                '    (property "Value" "ExistingLcsc" (at 0 0 0))\n'
                '    (property "LCSC" "C123" (at 0 0 0))\n'
                '  )\n'
                ')\n'
            )

            count = add_missing_lcsc_properties(library_root)

            updated = symbol_library.read_text()
            self.assertEqual(1, count)
            self.assertIn('(property "LCSC" ""', updated)
            self.assertEqual(1, updated.count('(property "LCSC" "C123"'))

    def test_fill_missing_lcsc_properties_uses_exact_match_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "library"
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            symbol_library.write_text(
                '(kicad_symbol_lib (version 20211014) (generator test)\n'
                '  (symbol "STM32L432KBU6" (in_bom yes) (on_board yes)\n'
                '    (property "Value" "STM32L432KBU6" (at 0 0 0))\n'
                '  )\n'
                '  (symbol "Ambiguous" (in_bom yes) (on_board yes)\n'
                '    (property "Value" "AMBIGUOUS" (at 0 0 0))\n'
                '  )\n'
                ')\n'
            )
            original_resolver = collector.resolve_easyeda_lcsc_id_exact

            def fake_resolver(query: str) -> str | None:
                return "C94784" if query == "STM32L432KBU6" else None

            try:
                collector.resolve_easyeda_lcsc_id_exact = fake_resolver
                result = collector.fill_missing_lcsc_properties(library_root)
            finally:
                collector.resolve_easyeda_lcsc_id_exact = original_resolver

            updated = symbol_library.read_text()
            self.assertEqual(2, result.added)
            self.assertEqual(1, result.filled)
            self.assertIn('(property "LCSC" "C94784"', updated)
            self.assertEqual(1, updated.count('(property "LCSC" ""'))

    def test_install_zip_can_fill_lcsc_for_new_symbol(self) -> None:
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
            original_resolver = collector.resolve_easyeda_lcsc_id_exact

            def fake_resolver(query: str) -> str | None:
                return "C12345" if query == "Vendor" else None

            try:
                collector.resolve_easyeda_lcsc_id_exact = fake_resolver
                install_zip(zip_path, library_root, fill_lcsc=True)
            finally:
                collector.resolve_easyeda_lcsc_id_exact = original_resolver

            self.assertIn('(property "LCSC" "C12345"', symbol_library.read_text())

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

    def test_scan_library_reads_easyeda_multiline_properties(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "library"
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            footprint_library = library_root / "hrobotics.pretty"
            model_path = library_root / "3dmodels" / "SOIC.step"
            footprint_library.mkdir()
            model_path.parent.mkdir()
            model_path.write_text("step")
            symbol_library.write_text(
                '(kicad_symbol_lib (version 20211014) (generator test)\n'
                '  (symbol "EasyEdaPart" (in_bom yes) (on_board yes)\n'
                '    (property\n'
                '      "Value"\n'
                '      "ADM3055EBRIZ-RL"\n'
                '      (at 0 -16.51 0)\n'
                '    )\n'
                '    (property\n'
                '      "Footprint"\n'
                '      "hrobotics:SOIC-20_L15.4-W7.5-P1.27-LS10.3-BL"\n'
                '      (at 0 -19.05 0)\n'
                '    )\n'
                '  )\n'
                ')\n'
            )
            (footprint_library / "SOIC-20_L15.4-W7.5-P1.27-LS10.3-BL.kicad_mod").write_text(
                f'(module easyeda2kicad:SOIC-20_L15.4-W7.5-P1.27-LS10.3-BL (layer F.Cu)\n'
                f'  (model "{model_path.resolve().as_posix()}")\n'
                f')\n'
            )

            entries = scan_library(library_root)

            self.assertEqual(1, len(entries))
            self.assertEqual("ADM3055EBRIZ-RL", entries[0].value)
            self.assertEqual("hrobotics:SOIC-20_L15.4-W7.5-P1.27-LS10.3-BL", entries[0].footprint)
            self.assertTrue(entries[0].footprint_ok)
            self.assertTrue(entries[0].model_ok)

    def test_update_library_entry_edits_properties_and_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "library"
            library_root.mkdir()
            symbol_library = library_root / "hrobotics_symbol_library.kicad_sym"
            footprint_library = library_root / "hrobotics.pretty"
            model_path = library_root / "3dmodels" / "Old.step"
            new_model_path = library_root / "3dmodels" / "New.step"
            footprint_library.mkdir()
            model_path.parent.mkdir()
            model_path.write_text("old")
            new_model_path.write_text("new")
            symbol_library.write_text(
                '(kicad_symbol_lib (version 20211014) (generator test)\n'
                '  (symbol "EditMe" (in_bom yes) (on_board yes)\n'
                '    (property "Value" "EditMe" (at 0 0 0))\n'
                '    (property "Footprint" "hrobotics:EditMe" (at 0 0 0))\n'
                '    (property "OldOnly" "remove" (at 0 0 0))\n'
                '  )\n'
                ')\n'
            )
            footprint_path = footprint_library / "EditMe.kicad_mod"
            footprint_path.write_text(
                f'(module "EditMe" (layer F.Cu)\n'
                f'  (model "{model_path.resolve().as_posix()}")\n'
                f')\n'
            )

            entry = update_library_entry(
                library_root,
                "EditMe",
                {
                    "Value": "EditedValue",
                    "Footprint": "hrobotics:EditMe",
                    "Datasheet": "https://example.com/ds.pdf",
                    "CustomField": "CustomValue",
                },
                new_model_path.resolve().as_posix(),
            )

            symbol_text = symbol_library.read_text()
            footprint_text = footprint_path.read_text()
            self.assertEqual("EditedValue", entry.value)
            self.assertEqual("CustomValue", entry.properties["CustomField"])
            self.assertNotIn("OldOnly", symbol_text)
            self.assertIn('(property "Datasheet" "https://example.com/ds.pdf"', symbol_text)
            self.assertIn(new_model_path.resolve().as_posix(), footprint_text)

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

    def test_process_watch_folder_imports_easyeda_id_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            incoming = root / "incoming_zips"
            processed = root / "processed_zips"
            library_root = root / "library"
            incoming.mkdir()
            processed.mkdir()
            library_root.mkdir()
            id_file = incoming / "mouser_parts.txt"
            id_file.write_text("C2040\n# ignored\n511-STM32L432KBU6\n")
            calls: list[str] = []
            original_import = collector.import_easyeda_query

            def fake_import(query: str, target_library: Path) -> list[collector.InstallItem]:
                calls.append(query)
                return [collector.InstallItem(query, target_library / f"{query}.kicad_sym", "symbol")]

            try:
                collector.import_easyeda_query = fake_import
                results = process_watch_folder(library_root, WatchFolders(incoming, processed))
            finally:
                collector.import_easyeda_query = original_import

            self.assertEqual(["C2040", "511-STM32L432KBU6"], calls)
            self.assertEqual(1, len(results))
            self.assertTrue(results[0].ok)
            self.assertFalse(id_file.exists())
            self.assertTrue((processed / "mouser_parts.txt").exists())

    def test_part_number_candidates_include_mouser_tail(self) -> None:
        self.assertEqual(
            ["511-STM32L432KBU6", "STM32L432KBU6"],
            collector._part_number_candidates("511-STM32L432KBU6"),
        )

    def test_best_lcsc_match_prefers_exact_model(self) -> None:
        results = [
            {"lcsc": "C111", "model": "STM32L432KCU6", "name": "near match"},
            {"lcsc": "C94784", "model": "STM32L432KBU6", "name": "exact match"},
        ]

        self.assertEqual("C94784", collector._best_lcsc_match("STM32L432KBU6", results))

    def test_exact_lcsc_match_rejects_partial_match(self) -> None:
        results = [
            {"lcsc": "C111", "model": "STM32L432KCU6", "name": "near match"},
            {"lcsc": "C222", "model": "STM32L432KBU6TR", "name": "partial match"},
        ]

        self.assertIsNone(collector._exact_lcsc_match("STM32L432KBU6", results))

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
