from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
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
    QTabWidget,
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
    import_easyeda_component,
    install_zip,
    install_zip_directory,
    process_watch_folder,
    remove_library_entries,
    scan_library,
    summarize_items,
    update_library_entry,
)
from .settings import AppSettings, load_settings, save_settings
from .preview_window import PreviewWindow
from .parts_search import PAGE_SIZE, search_parts
from .updater import UpdateError, download_release_asset, fetch_latest_release, install_downloaded_update, is_newer_version
from .version import APP_VERSION


APP_QSS = """
QMainWindow {
    background: #f5f7fb;
}
QWidget {
    color: #172033;
    font-family: "Apple SD Gothic Neo";
    font-size: 12px;
}
QFrame#topBar, QFrame#panel {
    background: #ffffff;
    border: 1px solid #e5e9f2;
    border-radius: 0;
}
QLabel#title {
    font-size: 20px;
    font-weight: 700;
}
QLabel#muted {
    color: #667085;
}
QLabel#sectionTitle {
    font-size: 12px;
    font-weight: 700;
}
QLineEdit {
    background: #f8fafc;
    border: 1px solid #d8dee9;
    border-radius: 3px;
    padding: 3px 5px;
    selection-background-color: #c7d2fe;
}
QPushButton {
    background: #eef2f7;
    border: 1px solid #d8dee9;
    border-radius: 3px;
    padding: 3px 7px;
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
    border-radius: 0;
    gridline-color: #edf1f7;
    selection-background-color: #dbeafe;
    selection-color: #172033;
}
QHeaderView::section {
    background: #f1f5f9;
    border: 0;
    border-right: 1px solid #e5e9f2;
    padding: 4px;
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
    update_error = Signal(str)
    update_release_ready = Signal(object)
    update_download_ready = Signal(Path)
    parts_search_ready = Signal(object)
    parts_download_ready = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.setWindowTitle(f"KiCad Parts Collector {APP_VERSION}")
        self.resize(940, 580)
        self.setMinimumSize(800, 500)

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
        self.update_error.connect(lambda message: self._error("업데이트 실패", message))
        self.update_release_ready.connect(self._handle_update_release)
        self.update_download_ready.connect(self._install_update)
        self.parts_search_ready.connect(self._finish_parts_search)
        self.parts_download_ready.connect(self._finish_parts_download)
        self.parts_download_busy = False
        self.parts_search_page = 1
        self.parts_search_total = 0
        self.parts_search_query = ""
        self.parts_search_busy = False

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
        help_menu.addAction("업데이트 확인", self.check_for_update)
        help_menu.addAction("버전 정보", self.show_version)

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 4, 6, 0)
        root.setSpacing(4)

        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_layout = QGridLayout(top_bar)
        top_layout.setContentsMargins(4, 4, 4, 4)
        top_layout.setHorizontalSpacing(4)
        top_layout.setVerticalSpacing(4)

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
        install_button = QPushButton("라이브러리 추가")
        install_button.setObjectName("primary")
        install_button.clicked.connect(self.install_current_zip)
        top_layout.addWidget(preview_button, 2, 3)
        top_layout.addWidget(install_button, 3, 3)
        top_layout.addWidget(QLabel("EasyEDA"), 4, 0)
        top_layout.addWidget(self.easyeda_edit, 4, 1)
        easyeda_button = QPushButton("EasyEDA 가져오기")
        easyeda_button.clicked.connect(self.import_easyeda)
        top_layout.addWidget(easyeda_button, 4, 2, 1, 2)
        top_layout.setColumnStretch(1, 1)
        root.addWidget(top_bar)

        self.watch_button = QPushButton("감시 시작")
        self.watch_button.clicked.connect(self.toggle_watch)
        self.statusBar().addPermanentWidget(self.watch_status_label)
        self.statusBar().addPermanentWidget(self.watch_button)

        zip_panel = self._panel("ZIP 추가 대상", self.preview_table, ("종류", "ZIP 내부 경로", "추가될 위치"))
        stats = QHBoxLayout()
        stats.setSpacing(8)
        for key, label in (("symbol", "심볼"), ("footprint", "풋프린트"), ("3d_model", "3D 모델")):
            label_widget = QLabel(label)
            label_widget.setObjectName("muted")
            value_widget = QLabel("0")
            stats.addWidget(label_widget)
            stats.addWidget(value_widget)
            stats.addStretch()
            self.summary_labels[key] = value_widget
        zip_panel.layout().insertLayout(1, stats)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._panel("라이브러리 연결 상태", self.library_table, ("심볼", "Value", "Footprint", "FP", "3D")))
        self.work_tabs = QTabWidget()
        self.work_tabs.addTab(self._detail_panel(), "파트 상세")
        self.work_tabs.addTab(zip_panel, "ZIP 작업")
        self.work_tabs.addTab(self._parts_search_panel(), "부품찾기")
        splitter.addWidget(self.work_tabs)
        splitter.setSizes([410, 510])
        root.addWidget(splitter, 1)

        self.setCentralWidget(central)
        self.library_table.itemSelectionChanged.connect(self.show_selected_entry)

    def _panel(self, title: str, table: QTableWidget, headers: tuple[str, ...]) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(22)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        if table is self.library_table:
            table.horizontalHeader().setStretchLastSection(False)
            for column in (3, 4):
                table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Fixed)
                table.setColumnWidth(column, 36)
        layout.addWidget(table)
        return panel

    def _parts_search_panel(self) -> QFrame:
        self.parts_table = QTableWidget(0, 6)
        panel = self._panel("JLCPCB 부품 검색", self.parts_table,
                            ("LCSC", "부품명", "제조사", "패키지", "카테고리", "재고"))
        self.parts_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for column, width in enumerate((85, 160, 120, 95, 130, 75)):
            self.parts_table.setColumnWidth(column, width)
        self.parts_keyword = QLineEdit()
        self.parts_keyword.setPlaceholderText("카테고리 · 부품명 · 키워드")
        self.parts_keyword.setClearButtonEnabled(True)
        self.parts_keyword.returnPressed.connect(lambda: self._start_parts_search(1))
        self.parts_search_button = QPushButton("검색")
        self.parts_search_button.setObjectName("primary")
        self.parts_search_button.clicked.connect(lambda: self._start_parts_search(1))
        search_row = QHBoxLayout()
        search_row.addWidget(self.parts_keyword, 1)
        search_row.addWidget(self.parts_search_button)
        panel.layout().insertLayout(1, search_row)
        self.parts_search_status = QLabel("0개")
        self.parts_search_status.setWordWrap(True)
        panel.layout().addWidget(self.parts_search_status)
        paging = QHBoxLayout()
        self.parts_previous = QPushButton("이전")
        self.parts_next = QPushButton("다음")
        self.parts_previous.setEnabled(False)
        self.parts_next.setEnabled(False)
        self.parts_previous.clicked.connect(lambda: self._start_parts_search(self.parts_search_page - 1))
        self.parts_next.clicked.connect(lambda: self._start_parts_search(self.parts_search_page + 1))
        self.parts_download_button = QPushButton("다운로드")
        self.parts_download_button.setToolTip("선택한 부품을 라이브러리에 추가")
        self.parts_download_button.setEnabled(False)
        self.parts_download_button.clicked.connect(self._download_selected_part)
        self.parts_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.parts_table.itemSelectionChanged.connect(
            lambda: self.parts_download_button.setEnabled(
                bool(self.parts_table.selectedItems()) and not self.parts_download_busy))
        self.parts_table.cellDoubleClicked.connect(self._show_part_specs)
        paging.addWidget(self.parts_download_button)
        paging.addStretch()
        paging.addWidget(self.parts_previous)
        paging.addWidget(self.parts_next)
        panel.layout().addLayout(paging)
        return panel

    def _start_parts_search(self, page: int) -> None:
        if self.parts_search_busy or self.parts_download_busy:
            return
        query = self.parts_keyword.text().strip() if page == 1 else self.parts_search_query
        if not query:
            self.parts_search_status.setText("검색어를 입력하세요.")
            self.parts_keyword.setFocus()
            return
        self.parts_search_busy = True
        self.parts_keyword.setEnabled(False)
        self.parts_search_button.setEnabled(False)
        self.parts_previous.setEnabled(False)
        self.parts_next.setEnabled(False)
        self.parts_table.setRowCount(0)
        self.parts_search_status.setText(f"검색 중: {query}")
        threading.Thread(target=self._parts_search_job, args=(query, page), daemon=True).start()

    def _parts_search_job(self, query: str, page: int) -> None:
        try:
            result = search_parts(query, page)
            self.parts_search_ready.emit((query, page, result, ""))
        except Exception as exc:
            self.parts_search_ready.emit((query, page, None, str(exc)))

    def _finish_parts_search(self, response) -> None:
        query, page, result, error = response
        self.parts_search_busy = False
        self.parts_keyword.setEnabled(True)
        self.parts_search_button.setEnabled(True)
        if error:
            self.parts_search_status.setText(f"검색 실패: {error}")
            return
        self.parts_search_query = query
        self.parts_search_page = page
        self.parts_search_total = result["total"]
        rows = result["results"]
        self.parts_table.setRowCount(len(rows))
        fields = ("componentCode", "componentModelEn", "componentBrandEn",
                  "componentSpecificationEn", "componentTypeEn", "stockCount")
        for row, part in enumerate(rows):
            for column, field in enumerate(fields):
                value = part.get(field)
                item = QTableWidgetItem(str(value) if value is not None else "—")
                item.setToolTip(str(part.get("describe") or item.text()))
                if column == 0:
                    item.setData(Qt.UserRole, part)
                self.parts_table.setItem(row, column, item)
        pages = max(1, (self.parts_search_total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.parts_search_status.setText(
            f"{query} · {self.parts_search_total:,}개 · {page}/{pages} 페이지"
            if rows else f"검색 결과 없음: {query}")
        self.parts_previous.setEnabled(page > 1)
        self.parts_next.setEnabled(bool(rows) and page < pages)

    def _show_part_specs(self, row: int, column: int) -> None:
        if self.parts_download_busy or self.parts_search_busy:
            return
        item = self.parts_table.item(row, 0)
        part = item.data(Qt.UserRole) if item is not None else None
        if not part:
            return
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.setWindowTitle(f"부품 상세 스펙 · {part.get('componentModelEn') or item.text()}")
        dialog.resize(620, 520)
        dialog.setMinimumSize(400, 300)
        layout = QVBoxLayout(dialog)
        fields = (("LCSC", "componentCode"), ("부품명", "componentModelEn"),
                  ("제조사", "componentBrandEn"), ("패키지", "componentSpecificationEn"),
                  ("카테고리", "componentTypeEn"), ("재고", "stockCount"),
                  ("설명", "describe"), ("데이터시트", "dataManualUrl"))
        specs = [(label, str(part[key])) for label, key in fields
                 if part.get(key) is not None and part.get(key) != ""]
        attributes = [(str(attribute.get("attribute_name_en") or "사양"),
                       str(attribute["attribute_value_name"]))
                      for attribute in (part.get("attributes") or [])
                      if attribute.get("attribute_value_name") not in (None, "", "-")]
        specs.extend(attributes or [("상세 사양", "제공된 상세 사양 없음")])
        table = QTableWidget(len(specs), 2, dialog)
        table.setObjectName("partsSpecTable")
        table.setHorizontalHeaderLabels(("항목", "값"))
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for index, (name, value) in enumerate(specs):
            table.setItem(index, 0, QTableWidgetItem(name))
            cell = QTableWidgetItem(value)
            cell.setToolTip(value)
            table.setItem(index, 1, cell)
        table.horizontalHeader().sectionResized.connect(lambda: table.resizeRowsToContents())
        layout.addWidget(table)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, alignment=Qt.AlignRight)
        dialog.open()
        table.resizeRowsToContents()

    def _download_selected_part(self) -> None:
        if self.parts_download_busy or self.parts_search_busy:
            return
        row = self.parts_table.currentRow()
        code = self.parts_table.item(row, 0)
        if not self.parts_table.selectedItems() or code is None:
            self.parts_search_status.setText("다운로드할 부품을 선택하세요.")
            return
        root_text = self.library_edit.text().strip()
        library_root = Path(root_text)
        if not root_text or not library_root.is_dir():
            self._error("확인 필요", "먼저 라이브러리 폴더를 선택하세요.")
            return
        lcsc_id = code.text().strip()
        self.parts_download_busy = True
        # 가져오기 중 감시·수정 작업이 같은 라이브러리 파일에 동시에 쓰지 않도록 한다.
        self.watch_timer.stop()
        self.centralWidget().setEnabled(False)
        self.menuBar().setEnabled(False)
        self.watch_button.setEnabled(False)
        self.parts_search_status.setText(f"다운로드 및 라이브러리 추가 중: {lcsc_id}")
        threading.Thread(target=self._parts_download_job,
                         args=(lcsc_id, library_root), daemon=True).start()

    def _parts_download_job(self, lcsc_id: str, library_root: Path) -> None:
        try:
            items = import_easyeda_component(lcsc_id, library_root)
            self.parts_download_ready.emit((lcsc_id, items, ""))
        except Exception as exc:
            self.parts_download_ready.emit((lcsc_id, [], str(exc)))

    def _finish_parts_download(self, response) -> None:
        lcsc_id, items, error = response
        self.parts_download_busy = False
        self.centralWidget().setEnabled(True)
        self.menuBar().setEnabled(True)
        self.watch_button.setEnabled(True)
        if self.watch_enabled:
            self.watch_timer.start()
        self.refresh_library()
        if error:
            self.parts_search_status.setText(f"가져오기 실패: {lcsc_id} · {error}")
            self._error("부품 다운로드 실패", error)
            return
        self._fill_preview(items)
        self.work_tabs.setCurrentIndex(2)
        counts = summarize_items(items)
        models = counts.get("3d_model", 0)
        model_status = f"3D 모델 {models}개" if models else "새 3D 모델 없음 (미제공 또는 기존 파일)"
        message = f"{lcsc_id} · 심볼·풋프린트 추가/확인 완료 · {model_status}"
        self.parts_search_status.setText(message)
        self.statusBar().showMessage(message)

    def closeEvent(self, event) -> None:
        if self.parts_download_busy:
            self.statusBar().showMessage("부품 다운로드가 완료된 후 종료할 수 있습니다.")
            event.ignore()
            return
        super().closeEvent(event)

    def _detail_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        heading_row = QHBoxLayout()
        self.selected_symbol_label.setObjectName("muted")
        self.selected_symbol_label.setWordWrap(True)
        heading_row.addWidget(self.selected_symbol_label, 1)
        preview_button = QPushButton("파트 미리보기")
        preview_button.clicked.connect(self.preview_selected_part)
        heading_row.addWidget(preview_button)
        layout.addLayout(heading_row)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("3D 모델"))
        model_row.addWidget(self.model_edit, 1)
        layout.addLayout(model_row)

        self.property_table.setHorizontalHeaderLabels(("속성", "값"))
        self.property_table.setAlternatingRowColors(True)
        self.property_table.verticalHeader().setVisible(False)
        self.property_table.verticalHeader().setDefaultSectionSize(22)
        self.property_table.horizontalHeader().setStretchLastSection(True)
        self.property_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.property_table, 1)

        buttons = QHBoxLayout()
        add_button = QPushButton("속성 추가")
        add_button.clicked.connect(self.add_property_row)
        remove_button = QPushButton("속성 삭제")
        remove_button.clicked.connect(self.remove_property_row)
        save_button = QPushButton("저장")
        save_button.setObjectName("primary")
        save_button.clicked.connect(self.save_selected_entry)
        delete_button = QPushButton("파트 삭제")
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
        self.statusBar().showMessage(f"라이브러리 상태: {len(entries)}개 / 문제 {broken}개")

    def preview_selected_part(self) -> None:
        entry = self.library_entries.get(self.current_symbol)
        if entry is None:
            QMessageBox.information(self, "파트 미리보기", "라이브러리에서 파트를 선택해 주세요.")
            return
        from .preview_server import preview_url, release_preview
        url = preview_url(Path(self.library_edit.text()), entry)
        dialog = PreviewWindow(url, entry.symbol, self)
        dialog.finished.connect(lambda: release_preview(url))
        dialog.show()

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
        self.work_tabs.setCurrentIndex(0)
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

    def check_for_update(self) -> None:
        self.statusBar().showMessage("업데이트 확인 중입니다.")
        threading.Thread(target=self._check_for_update_job, daemon=True).start()

    def _check_for_update_job(self) -> None:
        try:
            release = fetch_latest_release()
        except UpdateError as exc:
            self.update_error.emit(str(exc))
            return

        self.update_release_ready.emit(release)

    def _handle_update_release(self, release) -> None:
        if not is_newer_version(release.version, APP_VERSION):
            self.statusBar().showMessage("최신 버전입니다.")
            QMessageBox.information(self, "업데이트 확인", f"현재 최신 버전입니다.\n현재 버전: {APP_VERSION}")
            return

        notes = release.body.strip()
        if len(notes) > 400:
            notes = notes[:400] + "..."
        message = f"새 버전이 있습니다.\n\n현재 버전: {APP_VERSION}\n최신 버전: {release.version}"
        if notes:
            message += f"\n\n{notes}"
        message += "\n\n다운로드하고 설치할까요?"
        if QMessageBox.question(self, "업데이트 확인", message) != QMessageBox.Yes:
            self.statusBar().showMessage("업데이트 취소")
            return

        self.statusBar().showMessage("업데이트 다운로드 중입니다.")
        threading.Thread(target=self._download_update_job, args=(release,), daemon=True).start()

    def _download_update_job(self, release) -> None:
        try:
            downloaded_asset = download_release_asset(release.asset)
        except UpdateError as exc:
            self.update_error.emit(str(exc))
            return

        self.update_download_ready.emit(downloaded_asset)

    def _install_update(self, downloaded_asset: Path) -> None:
        if not getattr(sys, "frozen", False):
            self.statusBar().showMessage("업데이트 다운로드 완료")
            QMessageBox.information(self, "업데이트 다운로드 완료", f"개발 실행 중에는 자동 교체를 건너뜁니다.\n다운로드 위치: {downloaded_asset}")
            return

        install_message = "업데이트 설치 파일을 열고 앱을 종료할까요?" if sys.platform == "darwin" else "업데이트 설치를 위해 앱을 종료하고 다시 시작할까요?"
        if QMessageBox.question(self, "업데이트 설치", install_message) != QMessageBox.Yes:
            self.statusBar().showMessage("업데이트 설치 대기")
            return

        try:
            install_downloaded_update(downloaded_asset, Path(sys.executable))
        except UpdateError as exc:
            self._error("업데이트 실패", str(exc))
            self.statusBar().showMessage("업데이트 실패")
            return

        QApplication.quit()

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
        self.work_tabs.setCurrentIndex(1)
        counts = summarize_items(items)
        for key, label in self.summary_labels.items():
            label.setText(str(counts.get(key, 0)))
        self.preview_table.setColumnCount(3)
        self.preview_table.setHorizontalHeaderLabels(("종류", "ZIP 내부 경로", "추가될 위치"))
        self.preview_table.setRowCount(len(items))
        for row, item in enumerate(items):
            self._set_table_row(self.preview_table, row, (self._kind_label(item.kind), item.source, str(item.destination)))

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
