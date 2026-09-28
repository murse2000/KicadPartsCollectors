import sys
import unittest
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock, patch

if sys.platform == "win32":
    import tkinter as tk
    from kicad_parts_collectors.tk_parts import PartsPanel, show_specs


@unittest.skipUnless(sys.platform == "win32", "Windows Tk UI")
class TkPartsTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.on_import = Mock()
        self.panel = PartsPanel(self.root, self.on_import)

    def populate(self):
        self.panel.future = Future()
        self.panel.future.set_result({"total": 21, "results": [{
            "componentCode": "C2557", "componentModelEn": "IRF1010EPBF", "stockCount": 0,
            "attributes": [{"attribute_name_en": "Voltage", "attribute_value_name": "60V"}]}]})
        self.panel.finish("IRF1010", 1)

    def test_results_keep_zero_stock_and_enable_pagination(self):
        self.populate()
        self.assertEqual(self.panel.table.item("0", "values")[-1], "0")
        self.assertEqual(str(self.panel.next["state"]), "normal")
        self.assertEqual(str(self.panel.previous["state"]), "disabled")

    def test_search_error_restores_controls(self):
        self.panel.future = Future()
        self.panel.future.set_exception(ValueError("network error"))
        self.panel.finish("part", 1)
        self.assertIn("network error", self.panel.status.get())
        self.assertEqual(str(self.panel.search_button["state"]), "normal")
        self.assertEqual(str(self.panel.next["state"]), "disabled")

    @patch("kicad_parts_collectors.tk_parts.show_specs")
    def test_double_click_only_shows_specs_and_button_imports(self, specs):
        self.populate()
        with patch.object(self.panel.table, "identify_row", return_value="0"):
            self.panel.details(SimpleNamespace(y=10))
        self.assertIn(("Voltage", "60V"), specs.call_args.args[2])
        self.on_import.assert_not_called()
        self.panel.table.selection_set("0")
        self.panel.import_part()
        self.on_import.assert_called_once_with("C2557")
        self.panel.set_busy(True)
        self.panel.import_part()
        self.on_import.assert_called_once()

    def test_detail_window_has_full_value(self):
        dialog = show_specs(self.root, "part", [("Datasheet", "https://example.com/long")])
        body = dialog.winfo_children()[0]
        table, _, value = body.winfo_children()[:3]
        table.selection_set(table.get_children()[0])
        table.event_generate("<<TreeviewSelect>>")
        self.root.update()
        self.assertIn("https://example.com/long", value.get("1.0", "end"))

    def test_library_double_click_opens_saved_properties(self):
        from kicad_parts_collectors.app import KicadPartsCollectorApp
        from kicad_parts_collectors.collector import LibraryEntry
        entry = LibraryEntry("SS14", "SS14", "parts:SS14", "", "", {"Voltage": "40V"}, True, "SS14.step", True)
        app = SimpleNamespace(library_table=Mock(), library_entries={"SS14": entry})
        app.library_table.identify_column.return_value = "#1"
        app.library_table.identify_row.return_value = "SS14"
        with patch("kicad_parts_collectors.tk_parts.show_specs") as specs:
            KicadPartsCollectorApp._show_library_part_specs(app, SimpleNamespace(x=1, y=1))
            self.assertIn(("Voltage", "40V"), specs.call_args.args[2])
