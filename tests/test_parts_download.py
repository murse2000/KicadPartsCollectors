import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableWidgetItem, QDialog, QTableWidget
from kicad_parts_collectors.collector import InstallItem, WatchFolders
from kicad_parts_collectors.qt_app import KicadPartsCollectorQtApp
from kicad_parts_collectors.settings import AppSettings


class PartsDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with patch("kicad_parts_collectors.qt_app.load_settings", return_value=AppSettings(library_root=str(self.root))), \
             patch("kicad_parts_collectors.qt_app.ensure_watch_folders", return_value=WatchFolders(self.root, self.root)), \
             patch.object(KicadPartsCollectorQtApp, "_safe_autostart_enabled", return_value=False):
            self.window = KicadPartsCollectorQtApp()
        self.addCleanup(self.window.deleteLater)
        self.window.parts_table.setRowCount(1)
        self.window.parts_table.setItem(0, 0, QTableWidgetItem("C2557"))
        self.window.parts_table.item(0, 0).setData(Qt.UserRole, {
            "componentCode": "C2557", "componentModelEn": "IRF1010EPBF", "stockCount": 0,
            "attributes": [{"attribute_name_en": "Drain to Source Voltage",
                            "attribute_value_name": "60V"}]})

    @patch("kicad_parts_collectors.qt_app.threading.Thread")
    def test_button_uses_exact_id_once(self, thread):
        self.window.parts_table.selectRow(0)
        self.window.parts_download_button.click()
        self.window.parts_table.cellDoubleClicked.emit(0, 0)
        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["args"], ("C2557", self.root))
        self.assertFalse(self.window.centralWidget().isEnabled())
        self.assertTrue(self.window.parts_download_busy)

    @patch("kicad_parts_collectors.qt_app.threading.Thread")
    def test_double_click_shows_specs_without_download(self, thread):
        self.window.parts_table.selectRow(0)
        self.window.parts_table.cellDoubleClicked.emit(0, 0)
        thread.assert_not_called()
        dialog = self.window.findChild(QDialog)
        table = dialog.findChild(QTableWidget, "partsSpecTable")
        specs = {table.item(row, 0).text(): table.item(row, 1).text()
                 for row in range(table.rowCount())}
        self.assertEqual(specs["Drain to Source Voltage"], "60V")
        self.assertEqual(specs["재고"], "0")
        dialog.accept()

    def test_missing_specs_are_explicit(self):
        self.window.parts_table.item(0, 0).setData(Qt.UserRole, {"componentCode": "C2557"})
        self.window.parts_table.cellDoubleClicked.emit(0, 0)
        dialog = self.window.findChild(QDialog)
        table = dialog.findChild(QTableWidget, "partsSpecTable")
        self.assertEqual(table.item(table.rowCount() - 1, 1).text(), "제공된 상세 사양 없음")
        dialog.accept()

    @patch("kicad_parts_collectors.qt_app.threading.Thread")
    def test_no_selection_does_not_start_download(self, thread):
        self.window._download_selected_part()
        thread.assert_not_called()

    def test_success_refreshes_and_reports_missing_model(self):
        self.window.parts_download_busy = True
        self.window.watch_enabled = True
        items = [InstallItem("C2557", self.root / "part.kicad_sym", "symbol"),
                 InstallItem("C2557", self.root / "part.kicad_mod", "footprint")]
        with patch.object(self.window, "refresh_library") as refresh:
            self.window._finish_parts_download(("C2557", items, ""))
        refresh.assert_called_once()
        self.assertTrue(self.window.centralWidget().isEnabled())
        self.assertTrue(self.window.watch_timer.isActive())
        self.window.watch_timer.stop()
        self.assertIn("새 3D 모델 없음", self.window.parts_search_status.text())
        self.assertEqual(self.window.work_tabs.currentIndex(), 2)

    def test_worker_failure_restores_controls(self):
        self.window.parts_download_busy = True
        with patch("kicad_parts_collectors.qt_app.import_easyeda_component", side_effect=RuntimeError("offline")), \
             patch.object(self.window, "_error") as error:
            self.window._parts_download_job("C2557", self.root)
        self.assertFalse(self.window.parts_download_busy)
        self.assertTrue(self.window.centralWidget().isEnabled())
        error.assert_called_once_with("부품 다운로드 실패", "offline")
