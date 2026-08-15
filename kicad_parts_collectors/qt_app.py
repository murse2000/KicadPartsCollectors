from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .autostart import AutostartError, is_autostart_enabled, set_autostart_enabled
from .collector import (
    CollectorError,
    WatchFolders,
    build_install_plan,
    ensure_watch_folders,
    import_easyeda_query,
    install_zip,
    install_zip_directory,
    process_watch_folder,
    remove_library_entries,
    scan_library,
    summarize_items,
    update_library_entry,
)
from .settings import AppSettings, load_settings, save_settings
from .version import APP_VERSION


APP_QSS = """
QMainWindow {
    background: #f5f7fb;
}
QWidget {
    color: #172033;
    font-family: "Apple SD Gothic Neo";
    font-size: 13px;
}
QFrame#topBar, QFrame#panel {
    background: #ffffff;
    border: 1px solid #e5e9f2;
    border-radius: 10px;
}
QLabel#title {
    font-size: 20px;
    font-weight: 700;
}
QLabel#muted {
    color: #667085;
}
QLabel#sectionTitle {
    font-size: 14px;
    font-weight: 700;
}
QLineEdit {
    background: #f8fafc;
    border: 1px solid #d8dee9;
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: #c7d2fe;
}
QPushButton {
    background: #eef2f7;
    border: 1px solid #d8dee9;
    border-radius: 8px;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton:hover {
    background: #e6edf7;
}
QPushButton#primary {
    background: #2563eb;
    color: #ffffff;
    border-color: #2563eb;
}
QPushButton#primary:hover {
    background: #1d4ed8;
}
QPushButton#danger {
    color: #b42318;
}
QPushButton#watching {
    background: #dcfce7;
    color: #166534;
    border-color: #86efac;
}
QTableWidget {
    background: #ffffff;
    alternate-background-color: #f8fafc;
    border: 1px solid #e5e9f2;
    border-radius: 8px;
    gridline-color: #edf1f7;
    selection-background-color: #dbeafe;
    selection-color: #172033;
}
QHeaderView::section {
    background: #f1f5f9;
    border: 0;
    border-right: 1px solid #e5e9f2;
    padding: 8px;
    font-weight: 700;
}
QStatusBar {
    background: #ffffff;
    border-top: 1px solid #e5e9f2;
}
"""


def _resource_path(relative_path: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).resolve().parent.parent / relative_path


class KicadPartsCollectorQtApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.setWindowTitle(f"KiCad Parts Collector {APP_VERSION}")
        self.resize(1180, 760)
        self.setMinimumSize(1040, 640)

        icon_path = _resource_path("assets/app_icon.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.zip_edit = QLineEdit()
        self.zip_edit.setPlaceholderText("ZIP 파일을 선택하세요")
        self.easyeda_edit = QLineEdit()
        self.easyeda_edit.setPlaceholderText("마우저/제조사 부품번호 또는 LCSC ID 예: STM32L432KBU6")
        self.library_edit = QLineEdit(self.settings.library_root)
        self.library_edit.setPlaceholderText("KiCad 라이브러리 루트 폴더")
        self.preview_table = QTableWidget(0, 3)
        self.library_table = QTableWidget(0, 5)
        self.property_table = QTableWidget(0, 2)
        self.model_edit = QLineEdit()
        self.selected_symbol_label = QLabel("선택된 파츠 없음")
        self.watch_status_label = QLabel("감시 중지")
        self.watch_status_label.setObjectName("muted")
        self.summary_labels: dict[str, QLabel] = {}
        self.library_entries = {}
        self.current_symbol = ""
        self.watch_enabled = False
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(2000)
        self.watch_timer.timeout.connect(self.poll_watch_folder)
        default_watch_folders = ensure_watch_folders()
        self.incoming_edit = QLineEdit(self._watch_folder_text(self.settings.incoming_folder, default_watch_folders.incoming))
        self.processed_edit = QLineEdit(self._watch_folder_text(self.settings.processed_folder, default_watch_folders.processed))
        self.autostart_action: QAction | None = None

        self._build_menu()
        self._build_ui()
        self.statusBar().showMessage("ZIP 파일과 KiCad 라이브러리 위치를 선택하세요.")
        self.refresh_library()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("파일")
        choose_zip = QAction("ZIP 파일 선택", self)
        choose_zip.triggered.connect(self.choose_zip)
        file_menu.addAction(choose_zip)
        file_menu.addAction("미리보기", self.preview_zip)
        file_menu.addAction("라이브러리에 추가", self.install_current_zip)
        file_menu.addSeparator()
        file_menu.addAction("폴더 일괄 추가", self.install_directory)
        file_menu.addSeparator()
        file_menu.addAction("종료", self.close)

        library_menu = self.menuBar().addMenu("라이브러리")
        library_menu.addAction("라이브러리 위치 선택", self.choose_library)
        library_menu.addAction("라이브러리 상태 새로고침", self.refresh_library)
        library_menu.addAction("선택 항목 삭제", self.delete_selected_entry)

        watch_menu = self.menuBar().addMenu("감시")
        watch_menu.addAction("감시 시작/중지", self.toggle_watch)
        watch_menu.addAction("수신폴더 설정", self.choose_incoming_folder)
        watch_menu.addAction("백업폴더 설정", self.choose_processed_folder)
        watch_menu.addSeparator()
        self.autostart_action = QAction("로그인 시 자동 실행", self)
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(self._safe_autostart_enabled())
        self.autostart_action.triggered.connect(self.toggle_autostart)
        watch_menu.addAction(self.autostart_action)

        help_menu = self.menuBar().addMenu("도움말")
        help_menu.addAction("버전 정보", self.show_version)

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 10)
        root.setSpacing(12)

        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_layout = QGridLayout(top_bar)
        top_layout.setContentsMargins(14, 12, 14, 12)
        top_layout.setHorizontalSpacing(10)
        top_layout.setVerticalSpacing(8)

        title = QLabel("KiCad Parts Collector")
        title.setObjectName("title")
        subtitle = QLabel("ZIP으로 받은 심볼, 풋프린트, 3D 모델을 KiCad 라이브러리에 정리합니다.")
        subtitle.setObjectName("muted")
        top_layout.addWidget(title, 0, 0, 1, 4)
        top_layout.addWidget(subtitle, 1, 0, 1, 4)

        top_layout.addWidget(QLabel("ZIP"), 2, 0)
        top_layout.addWidget(self.zip_edit, 2, 1)
        zip_button = QPushButton("찾기")
        zip_button.clicked.connect(self.choose_zip)
        top_layout.addWidget(zip_button, 2, 2)

        top_layout.addWidget(QLabel("라이브러리"), 3, 0)
        top_layout.addWidget(self.library_edit, 3, 1)
        library_button = QPushButton("찾기")
        library_button.clicked.connect(self.choose_library)
        top_layout.addWidget(library_button, 3, 2)

        preview_button = QPushButton("미리보기")
        preview_button.clicked.connect(self.preview_zip)
        install_button = QPushButton("라이브러리에 추가")
        install_button.setObjectName("primary")
        install_button.clicked.connect(self.install_current_zip)
        batch_button = QPushButton("폴더 일괄 추가")
        batch_button.clicked.connect(self.install_directory)
        top_layout.addWidget(preview_button, 2, 3)
        top_layout.addWidget(install_button, 3, 3)
        top_layout.addWidget(batch_button, 2, 4, 2, 1)
        top_layout.addWidget(QLabel("EasyEDA"), 4, 0)
        top_layout.addWidget(self.easyeda_edit, 4, 1)
        easyeda_button = QPushButton("EasyEDA에서 가져오기")
        easyeda_button.clicked.connect(self.import_easyeda)
        top_layout.addWidget(easyeda_button, 4, 2, 1, 2)
        top_layout.setColumnStretch(1, 1)
        root.addWidget(top_bar)

        watch_bar = QFrame()
        watch_bar.setObjectName("topBar")
        watch_layout = QGridLayout(watch_bar)
        watch_layout.setContentsMargins(14, 10, 14, 10)
        watch_layout.setHorizontalSpacing(10)
        watch_layout.addWidget(QLabel("수신폴더"), 0, 0)
        watch_layout.addWidget(self.incoming_edit, 0, 1)
        incoming_button = QPushButton("찾기")
        incoming_button.clicked.connect(self.choose_incoming_folder)
        watch_layout.addWidget(incoming_button, 0, 2)
        watch_layout.addWidget(QLabel("백업폴더"), 1, 0)
        watch_layout.addWidget(self.processed_edit, 1, 1)
        processed_button = QPushButton("찾기")
        processed_button.clicked.connect(self.choose_processed_folder)
        watch_layout.addWidget(processed_button, 1, 2)
        self.watch_button = QPushButton("감시 시작")
        self.watch_button.clicked.connect(self.toggle_watch)
        watch_layout.addWidget(self.watch_button, 0, 3)
        watch_layout.addWidget(self.watch_status_label, 1, 3)
        watch_layout.setColumnStretch(1, 1)
        root.addWidget(watch_bar)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        for key, label in (("symbol", "심볼"), ("footprint", "풋프린트"), ("3d_model", "3D 모델")):
            card = QFrame()
            card.setObjectName("panel")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(14, 10, 14, 10)
            label_widget = QLabel(label)
            label_widget.setObjectName("muted")
            value_widget = QLabel("0")
            value_widget.setObjectName("title")
            layout.addWidget(label_widget)
            layout.addWidget(value_widget)
            stats.addWidget(card)
            self.summary_labels[key] = value_widget
        root.addLayout(stats)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._panel("미리보기", self.preview_table, ("종류", "ZIP 내부 경로", "추가될 위치")))
        library_detail_splitter = QSplitter(Qt.Vertical)
        library_detail_splitter.addWidget(self._panel("라이브러리 연결 상태", self.library_table, ("심볼", "Value", "Footprint", "FP", "3D")))
        library_detail_splitter.addWidget(self._detail_panel())
        library_detail_splitter.setSizes([380, 260])
        splitter.addWidget(library_detail_splitter)
        splitter.setSizes([520, 620])
        root.addWidget(splitter, 1)

        self.setCentralWidget(central)
        self.library_table.itemSelectionChanged.connect(self.show_selected_entry)

    def _panel(self, title: str, table: QTableWidget, headers: tuple[str, ...]) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        layout.addWidget(table)
        return panel

    def _detail_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)

        heading_row = QHBoxLayout()
        title = QLabel("선택 파츠 상세")
        title.setObjectName("sectionTitle")
        self.selected_symbol_label.setObjectName("muted")
        heading_row.addWidget(title)
        heading_row.addStretch(1)
        heading_row.addWidget(self.selected_symbol_label)
        layout.addLayout(heading_row)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("3D 모델"))
        model_row.addWidget(self.model_edit, 1)
        layout.addLayout(model_row)

        self.property_table.setHorizontalHeaderLabels(("속성", "값"))
        self.property_table.setAlternatingRowColors(True)
        self.property_table.verticalHeader().setVisible(False)
        self.property_table.horizontalHeader().setStretchLastSection(True)
        self.property_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        layout.addWidget(self.property_table, 1)

        buttons = QHBoxLayout()
        add_button = QPushButton("속성 추가")
        add_button.clicked.connect(self.add_property_row)
        remove_button = QPushButton("속성 삭제")
        remove_button.clicked.connect(self.remove_property_row)
        save_button = QPushButton("상세 저장")
        save_button.setObjectName("primary")
        save_button.clicked.connect(self.save_selected_entry)
        delete_button = QPushButton("선택 파츠 삭제")
        delete_button.setObjectName("danger")
        delete_button.clicked.connect(self.delete_selected_entry)
        buttons.addWidget(add_button)
        buttons.addWidget(remove_button)
        buttons.addStretch(1)
        buttons.addWidget(delete_button)
        buttons.addWidget(save_button)
        layout.addLayout(buttons)
        return panel

    def choose_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "KiCad 파일이 들어있는 ZIP 선택", "", "ZIP 파일 (*.zip);;모든 파일 (*)")
        if path:
            self.zip_edit.setText(path)
            self.statusBar().showMessage("ZIP 파일을 선택했습니다.")

    def choose_library(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "KiCad 라이브러리 위치 선택", self.library_edit.text())
        if path:
            self.library_edit.setText(path)
            self._save_settings()
            self.refresh_library()

    def choose_incoming_folder(self) -> None:
        if self.watch_enabled:
            self._error("확인 필요", "감시 중에는 수신폴더를 변경할 수 없습니다.")
            return
        path = QFileDialog.getExistingDirectory(self, "수신폴더 선택", self.incoming_edit.text())
        if path:
            self.incoming_edit.setText(path)
            self._save_settings()

    def choose_processed_folder(self) -> None:
        if self.watch_enabled:
            self._error("확인 필요", "감시 중에는 백업폴더를 변경할 수 없습니다.")
            return
        path = QFileDialog.getExistingDirectory(self, "백업폴더 선택", self.processed_edit.text())
        if path:
            self.processed_edit.setText(path)
            self._save_settings()

    def preview_zip(self) -> None:
        try:
            zip_path, library_root = self._validated_paths()
            items = build_install_plan(zip_path, library_root)
        except CollectorError as exc:
            self._error("미리보기 실패", str(exc))
            return

        self._fill_preview(items)
        self.statusBar().showMessage("미리보기 완료")

    def install_current_zip(self) -> None:
        if QMessageBox.question(self, "추가 확인", "선택한 ZIP 파일의 KiCad 자산을 라이브러리에 추가할까요?") != QMessageBox.Yes:
            return
        try:
            zip_path, library_root = self._validated_paths()
            items = install_zip(zip_path, library_root)
        except CollectorError as exc:
            self._error("추가 실패", str(exc))
            return

        self._fill_preview(items)
        self.refresh_library()
        self.statusBar().showMessage("라이브러리에 추가했습니다.")

    def install_directory(self) -> None:
        library_root = Path(self.library_edit.text())
        if not library_root.exists() or not library_root.is_dir():
            self._error("확인 필요", "먼저 라이브러리 폴더를 선택하세요.")
            return
        directory = QFileDialog.getExistingDirectory(self, "ZIP 파일이 들어있는 폴더 선택", "")
        if not directory:
            return
        if QMessageBox.question(self, "일괄 추가 확인", "선택한 폴더의 ZIP 파일들을 순서대로 라이브러리에 추가할까요?") != QMessageBox.Yes:
            return
        try:
            results = install_zip_directory(Path(directory), library_root)
        except CollectorError as exc:
            self._error("일괄 추가 실패", str(exc))
            return

        self.preview_table.setRowCount(len(results))
        self.preview_table.setColumnCount(3)
        self.preview_table.setHorizontalHeaderLabels(("ZIP", "상태", "메시지"))
        ok_count = 0
        for row, result in enumerate(results):
            if result.ok:
                ok_count += 1
            self._set_table_row(self.preview_table, row, (result.zip_path.name, "OK" if result.ok else "실패", result.message))
        self.refresh_library()
        self.statusBar().showMessage(f"일괄 추가 완료: 성공 {ok_count} / 실패 {len(results) - ok_count}")

    def import_easyeda(self) -> None:
        part_number = self.easyeda_edit.text().strip()
        if not part_number:
            self._error("확인 필요", "마우저/제조사 부품번호 또는 LCSC ID를 입력하세요.")
            return
        library_root = Path(self.library_edit.text())
        if not library_root.exists() or not library_root.is_dir():
            self._error("확인 필요", "먼저 라이브러리 폴더를 선택하세요.")
            return
        self.statusBar().showMessage(f"EasyEDA 검색 중: {part_number}")
        QApplication.processEvents()
        try:
            items = import_easyeda_query(part_number, library_root)
        except CollectorError as exc:
            self._error("EasyEDA 가져오기 실패", str(exc))
            return

        self._fill_preview(items)
        self.refresh_library()
        self.statusBar().showMessage(f"EasyEDA 가져오기 완료: {part_number}")

    def refresh_library(self) -> None:
        library_root = Path(self.library_edit.text())
        if not library_root.exists() or not library_root.is_dir():
            self.library_table.setRowCount(0)
            return
        try:
            entries = scan_library(library_root)
        except CollectorError as exc:
            self.library_table.setRowCount(0)
            self.statusBar().showMessage(f"라이브러리 상태 오류: {exc}")
            return

        self.library_table.setRowCount(len(entries))
        self.library_entries = {entry.symbol: entry for entry in entries}
        broken = 0
        for row, entry in enumerate(entries):
            fp_status = "OK" if entry.footprint_ok else "누락"
            model_status = "OK" if entry.model_ok else "누락"
            if not entry.footprint_ok or not entry.model_ok:
                broken += 1
            self._set_table_row(self.library_table, row, (entry.symbol, entry.value, entry.footprint, fp_status, model_status))
        self.library_table.resizeColumnsToContents()
        self.statusBar().showMessage(f"라이브러리 상태: {len(entries)}개 / 문제 {broken}개")

    def show_selected_entry(self) -> None:
        selected = self.library_table.selectedItems()
        if not selected:
            self.current_symbol = ""
            self.selected_symbol_label.setText("선택된 파츠 없음")
            self.model_edit.clear()
            self.property_table.setRowCount(0)
            return

        symbol = self.library_table.item(selected[0].row(), 0).text()
        entry = self.library_entries.get(symbol)
        if entry is None:
            return
        self.current_symbol = entry.symbol
        self.selected_symbol_label.setText(entry.symbol)
        self.model_edit.setText(entry.model)
        self.property_table.setRowCount(0)
        preferred = ["Reference", "Value", "Footprint", "Datasheet", "Description"]
        ordered_names = [name for name in preferred if name in entry.properties]
        ordered_names.extend(sorted(name for name in entry.properties if name not in ordered_names))
        for name in ordered_names:
            self._append_property(name, entry.properties[name])

    def add_property_row(self) -> None:
        self._append_property("", "")
        self.property_table.setCurrentCell(self.property_table.rowCount() - 1, 0)

    def remove_property_row(self) -> None:
        row = self.property_table.currentRow()
        if row >= 0:
            self.property_table.removeRow(row)

    def save_selected_entry(self) -> None:
        if not self.current_symbol:
            self._error("확인 필요", "수정할 파츠를 선택하세요.")
            return

        properties: dict[str, str] = {}
        for row in range(self.property_table.rowCount()):
            name_item = self.property_table.item(row, 0)
            value_item = self.property_table.item(row, 1)
            name = name_item.text().strip() if name_item else ""
            if not name:
                continue
            properties[name] = value_item.text() if value_item else ""

        if "Value" not in properties:
            self._error("확인 필요", "Value 속성은 필요합니다.")
            return

        try:
            entry = update_library_entry(Path(self.library_edit.text()), self.current_symbol, properties, self.model_edit.text().strip())
        except CollectorError as exc:
            self._error("저장 실패", str(exc))
            return
        self.statusBar().showMessage(f"저장 완료: {entry.symbol}")
        self.refresh_library()
        self._select_symbol(entry.symbol)

    def delete_selected_entry(self) -> None:
        if not self.current_symbol:
            self._error("확인 필요", "삭제할 파츠를 선택하세요.")
            return
        if QMessageBox.question(self, "삭제 확인", f"{self.current_symbol} 심볼과 연결된 내부 파일을 삭제할까요?") != QMessageBox.Yes:
            return
        try:
            result = remove_library_entries(Path(self.library_edit.text()), [self.current_symbol])
        except CollectorError as exc:
            self._error("삭제 실패", str(exc))
            return
        self.current_symbol = ""
        self.property_table.setRowCount(0)
        self.model_edit.clear()
        self.selected_symbol_label.setText("선택된 파츠 없음")
        self.refresh_library()
        self.statusBar().showMessage(f"삭제 완료: 심볼 {result.symbols}개, 풋프린트 {result.footprints}개, 3D 모델 {result.models}개")

    def toggle_watch(self) -> None:
        if self.watch_enabled:
            self.watch_enabled = False
            self.watch_timer.stop()
            self.watch_button.setText("감시 시작")
            self.watch_button.setObjectName("")
            self.watch_button.style().unpolish(self.watch_button)
            self.watch_button.style().polish(self.watch_button)
            self.watch_status_label.setText("감시 중지")
            self.statusBar().showMessage("감시 중지")
            return

        library_root = Path(self.library_edit.text())
        if not library_root.exists() or not library_root.is_dir():
            self._error("확인 필요", "감시를 시작하려면 먼저 라이브러리 폴더를 선택하세요.")
            return
        incoming = Path(self.incoming_edit.text())
        processed = Path(self.processed_edit.text())
        incoming.mkdir(parents=True, exist_ok=True)
        processed.mkdir(parents=True, exist_ok=True)
        self._save_settings()
        self.watch_enabled = True
        self.watch_button.setText("감시 중지")
        self.watch_button.setObjectName("watching")
        self.watch_button.style().unpolish(self.watch_button)
        self.watch_button.style().polish(self.watch_button)
        self.watch_status_label.setText("감시 중")
        self.watch_timer.start()
        self.statusBar().showMessage("수신폴더 감시를 시작했습니다.")

    def poll_watch_folder(self) -> None:
        if not self.watch_enabled:
            return
        library_root = Path(self.library_edit.text())
        if not library_root.exists() or not library_root.is_dir():
            return
        folders = WatchFolders(Path(self.incoming_edit.text()), Path(self.processed_edit.text()))
        results = process_watch_folder(library_root, folders)
        if not results:
            return
        ok_count = sum(1 for result in results if result.ok)
        self.preview_table.setColumnCount(3)
        self.preview_table.setHorizontalHeaderLabels(("항목", "상태", "메시지"))
        self.preview_table.setRowCount(len(results))
        for row, result in enumerate(results):
            self._set_table_row(self.preview_table, row, (result.zip_path.name, "OK" if result.ok else "실패", result.message))
        self.refresh_library()
        self.statusBar().showMessage(f"자동 추가 완료: 성공 {ok_count} / 실패 {len(results) - ok_count}")

    def toggle_autostart(self) -> None:
        if self.autostart_action is None:
            return

        try:
            set_autostart_enabled(self.autostart_action.isChecked())
        except AutostartError as exc:
            self.autostart_action.setChecked(self._safe_autostart_enabled())
            self._error("자동 실행 설정 실패", str(exc))
            return

        status = "켜짐" if self.autostart_action.isChecked() else "꺼짐"
        self.statusBar().showMessage(f"로그인 시 자동 실행: {status}")

    def show_version(self) -> None:
        QMessageBox.information(self, "버전 정보", f"KiCad Parts Collector\n현재 버전: {APP_VERSION}")

    def _validated_paths(self) -> tuple[Path, Path]:
        zip_path = Path(self.zip_edit.text())
        library_root = Path(self.library_edit.text())
        if not zip_path.is_file():
            raise CollectorError("ZIP 파일을 선택하세요.")
        if zip_path.suffix.lower() != ".zip":
            raise CollectorError("ZIP 파일만 처리할 수 있습니다.")
        if not library_root.exists() or not library_root.is_dir():
            raise CollectorError("존재하는 라이브러리 폴더를 선택하세요.")
        self._save_settings()
        return zip_path, library_root

    def _fill_preview(self, items) -> None:
        counts = summarize_items(items)
        for key, label in self.summary_labels.items():
            label.setText(str(counts.get(key, 0)))
        self.preview_table.setColumnCount(3)
        self.preview_table.setHorizontalHeaderLabels(("종류", "ZIP 내부 경로", "추가될 위치"))
        self.preview_table.setRowCount(len(items))
        for row, item in enumerate(items):
            self._set_table_row(self.preview_table, row, (self._kind_label(item.kind), item.source, str(item.destination)))
        self.preview_table.resizeColumnsToContents()

    def _save_settings(self) -> None:
        save_settings(
            AppSettings(
                library_root=self.library_edit.text().strip(),
                theme=self.settings.theme,
                incoming_folder=self.incoming_edit.text().strip(),
                processed_folder=self.processed_edit.text().strip(),
            )
        )

    def _watch_folder_text(self, saved_path: str, default_path: Path) -> str:
        if not saved_path:
            return str(default_path)

        path = Path(saved_path)
        if path.name == "incomming" or self._is_packaged_watch_path(path):
            return str(default_path)

        return str(path)

    def _is_packaged_watch_path(self, path: Path) -> bool:
        path_text = path.as_posix()
        return "/dist/KiCadPartsCollector/" in path_text or ".app/Contents/MacOS/" in path_text

    def _safe_autostart_enabled(self) -> bool:
        try:
            return is_autostart_enabled()
        except AutostartError:
            return False

    def _set_table_row(self, table: QTableWidget, row: int, values: tuple[str, ...]) -> None:
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            table.setItem(row, column, item)

    def _append_property(self, name: str, value: str) -> None:
        row = self.property_table.rowCount()
        self.property_table.insertRow(row)
        self.property_table.setItem(row, 0, QTableWidgetItem(name))
        self.property_table.setItem(row, 1, QTableWidgetItem(value))

    def _select_symbol(self, symbol: str) -> None:
        for row in range(self.library_table.rowCount()):
            item = self.library_table.item(row, 0)
            if item is not None and item.text() == symbol:
                self.library_table.selectRow(row)
                return

    def _kind_label(self, kind: str) -> str:
        labels = {
            "symbol": "심볼",
            "footprint": "풋프린트",
            "3d_model": "3D 모델",
        }
        return labels.get(kind, kind)

    def _error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)
        self.statusBar().showMessage(title)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("KiCad Parts Collector")
    app.setStyleSheet(APP_QSS)
    window = KicadPartsCollectorQtApp()
    window.show()
    sys.exit(app.exec())
