from __future__ import annotations

import ctypes
import threading
import tkinter as tk
import sys
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw

from .autostart import AutostartError, is_autostart_enabled, set_autostart_enabled
from .collector import (
    CollectorError,
    build_install_plan,
    ensure_watch_folders,
    install_zip,
    install_zip_directory,
    process_watch_folder,
    remove_library_entries,
    scan_library,
    summarize_items,
    update_library_entry,
)
from .settings import AppSettings, load_settings, save_settings

try:
    import ttkbootstrap as tb
except ImportError:
    tb = None

try:
    from tkinterdnd2 import COPY, DND_FILES, TkinterDnD
except ImportError:
    COPY = None
    DND_FILES = None
    TkinterDnD = None

try:
    import pystray
except ImportError:
    pystray = None


ERROR_ALREADY_EXISTS = 183
INSTANCE_MUTEX_NAME = "Local\\KiCadPartsCollector"
INSTANCE_MUTEX_HANDLE = None


AVAILABLE_THEMES = ("flatly", "cosmo", "litera", "minty", "pulse", "darkly", "superhero", "cyborg", "solar")
THEME_PALETTES = {
    "flatly": {
        "page_bg": "#f4f7fb",
        "card_bg": "#ffffff",
        "soft_bg": "#eef6ff",
        "heading_bg": "#eef3fb",
        "text": "#172033",
        "muted": "#657084",
        "field": "#273247",
        "primary": "#2563eb",
        "primary_active": "#1d4ed8",
        "secondary": "#eef3fb",
        "secondary_active": "#e2eaf6",
        "selection": "#dbeafe",
        "entry_bg": "#ffffff",
    },
    "cosmo": {
        "page_bg": "#f5f7fb",
        "card_bg": "#ffffff",
        "soft_bg": "#edf4ff",
        "heading_bg": "#e8edf7",
        "text": "#1f2937",
        "muted": "#64748b",
        "field": "#263244",
        "primary": "#2780e3",
        "primary_active": "#1f6fc8",
        "secondary": "#edf2f7",
        "secondary_active": "#dde7f0",
        "selection": "#d7e9ff",
        "entry_bg": "#ffffff",
    },
    "litera": {
        "page_bg": "#f7f5f2",
        "card_bg": "#ffffff",
        "soft_bg": "#fff1f0",
        "heading_bg": "#f1ebe5",
        "text": "#2f2a26",
        "muted": "#756b63",
        "field": "#423833",
        "primary": "#d9534f",
        "primary_active": "#c64541",
        "secondary": "#eee8e2",
        "secondary_active": "#e4dbd2",
        "selection": "#ffd9d7",
        "entry_bg": "#ffffff",
    },
    "minty": {
        "page_bg": "#f1faf7",
        "card_bg": "#ffffff",
        "soft_bg": "#e4f8f1",
        "heading_bg": "#dff3ec",
        "text": "#14332b",
        "muted": "#527067",
        "field": "#1f4a40",
        "primary": "#20c997",
        "primary_active": "#16a67d",
        "secondary": "#e6f3ef",
        "secondary_active": "#d5e9e3",
        "selection": "#c6f2e4",
        "entry_bg": "#ffffff",
    },
    "pulse": {
        "page_bg": "#f8f5fb",
        "card_bg": "#ffffff",
        "soft_bg": "#f2e9fb",
        "heading_bg": "#eadff5",
        "text": "#2f243a",
        "muted": "#736280",
        "field": "#4a365b",
        "primary": "#593196",
        "primary_active": "#4b2a80",
        "secondary": "#efe7f6",
        "secondary_active": "#e2d6ee",
        "selection": "#dfccf4",
        "entry_bg": "#ffffff",
    },
    "darkly": {
        "page_bg": "#111827",
        "card_bg": "#1f2937",
        "soft_bg": "#263447",
        "heading_bg": "#303b4d",
        "text": "#f8fafc",
        "muted": "#b7c3d3",
        "field": "#dbeafe",
        "primary": "#38bdf8",
        "primary_active": "#0ea5e9",
        "secondary": "#334155",
        "secondary_active": "#475569",
        "selection": "#0f766e",
        "entry_bg": "#111827",
    },
    "superhero": {
        "page_bg": "#18202b",
        "card_bg": "#243242",
        "soft_bg": "#20384d",
        "heading_bg": "#31475e",
        "text": "#f3f7fb",
        "muted": "#b8c5d1",
        "field": "#e4eef8",
        "primary": "#df691a",
        "primary_active": "#c75c16",
        "secondary": "#3a4e63",
        "secondary_active": "#4a6178",
        "selection": "#4f6f8f",
        "entry_bg": "#17212c",
    },
    "cyborg": {
        "page_bg": "#060b10",
        "card_bg": "#111820",
        "soft_bg": "#10212a",
        "heading_bg": "#182733",
        "text": "#f7fbff",
        "muted": "#9fb4c8",
        "field": "#dffaff",
        "primary": "#2a9fd6",
        "primary_active": "#2088ba",
        "secondary": "#202f3a",
        "secondary_active": "#2d4050",
        "selection": "#155e75",
        "entry_bg": "#050a0f",
    },
    "solar": {
        "page_bg": "#1f2326",
        "card_bg": "#2b3035",
        "soft_bg": "#383733",
        "heading_bg": "#3a4247",
        "text": "#f6f0df",
        "muted": "#c6bfae",
        "field": "#fff4ce",
        "primary": "#b58900",
        "primary_active": "#9c7600",
        "secondary": "#3b4348",
        "secondary_active": "#4b545a",
        "selection": "#6b5a22",
        "entry_bg": "#202529",
    },
}


def dropped_zip_paths(paths) -> list[str]:
    return [str(path) for path in paths if Path(path).suffix.lower() == ".zip"]


def _resource_path(relative_path: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / relative_path

    return Path(__file__).resolve().parent.parent / relative_path


def _tray_image() -> Image.Image:
    icon_path = _resource_path("assets/app_icon.png")
    if icon_path.exists():
        return Image.open(icon_path).convert("RGBA")

    image = Image.new("RGBA", (64, 64), "#1f3349")
    draw = ImageDraw.Draw(image)
    colors = ["#ef4444", "#f59e0b", "#22c55e", "#3b82f6"]
    for index, color in enumerate(colors):
        x = 12 + (index % 2) * 24
        y = 12 + (index // 2) * 24
        draw.rounded_rectangle((x, y, x + 16, y + 16), radius=4, fill=color)
    return image


def _safe_autostart_enabled() -> bool:
    try:
        return is_autostart_enabled()
    except AutostartError:
        return False


def _acquire_single_instance() -> bool:
    global INSTANCE_MUTEX_HANDLE
    if sys.platform != "win32":
        return True

    handle = ctypes.windll.kernel32.CreateMutexW(None, True, INSTANCE_MUTEX_NAME)
    if not handle:
        return True

    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        ctypes.windll.kernel32.CloseHandle(handle)
        return False

    INSTANCE_MUTEX_HANDLE = handle
    return True


def _release_single_instance() -> None:
    global INSTANCE_MUTEX_HANDLE
    if sys.platform != "win32" or INSTANCE_MUTEX_HANDLE is None:
        return

    ctypes.windll.kernel32.ReleaseMutex(INSTANCE_MUTEX_HANDLE)
    ctypes.windll.kernel32.CloseHandle(INSTANCE_MUTEX_HANDLE)
    INSTANCE_MUTEX_HANDLE = None


def _show_already_running_message() -> None:
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("KiCad Parts Collector", "이미 실행 중입니다.")
    root.destroy()


class KicadPartsCollectorApp(tb.Window if tb else tk.Tk):
    def __init__(self) -> None:
        app_settings = load_settings()
        initial_theme = app_settings.theme if app_settings.theme in AVAILABLE_THEMES else "flatly"
        if tb:
            super().__init__(themename=initial_theme)
        else:
            super().__init__()
        self.title("KiCad Parts Collector")
        self.geometry("1180x760")
        self.minsize(1040, 640)

        self.app_settings = app_settings
        self.zip_path = tk.StringVar()
        self.library_root = tk.StringVar(value=self.app_settings.library_root)
        self.theme_name = tk.StringVar(value=initial_theme)
        self.status = tk.StringVar(value="ZIP 파일과 사내 라이브러리 위치를 선택하세요.")
        self.symbol_count = tk.StringVar(value="0")
        self.footprint_count = tk.StringVar(value="0")
        self.model_count = tk.StringVar(value="0")
        self.library_status = tk.StringVar(value="라이브러리 상태: -")
        self.selected_symbol = tk.StringVar(value="선택된 파츠 없음")
        self.detail_model = tk.StringVar()
        self.property_name = tk.StringVar()
        self.property_value = tk.StringVar()
        self.library_entries = {}
        self.current_properties = {}
        self.batch_directory = tk.StringVar()
        self.watch_status = tk.StringVar(value="감시 중지")
        self.autostart_enabled = tk.BooleanVar(value=_safe_autostart_enabled())
        self.watch_enabled = False
        self.watch_folders = ensure_watch_folders()
        self.tray_icon = None
        self.tray_hidden = False
        self.quitting = False

        self._set_window_icon()
        self.dnd_enabled = self._enable_drag_and_drop()
        self._configure_style()
        self._build_menu()
        self._build_ui()
        self._register_drop_targets()
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self.bind("<Unmap>", self._on_unmap)
        self._start_tray_icon()
        self.after(100, self._refresh_library_view)

    def _enable_drag_and_drop(self) -> bool:
        if TkinterDnD is None:
            return False

        try:
            TkinterDnD._require(self)
        except RuntimeError:
            return False

        return True

    def _set_window_icon(self) -> None:
        icon_path = _resource_path("assets/app_icon.ico")
        png_path = _resource_path("assets/app_icon.png")

        if icon_path.exists():
            try:
                self.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass

        if png_path.exists():
            try:
                self.window_icon_image = tk.PhotoImage(file=str(png_path))
                self.iconphoto(True, self.window_icon_image)
            except tk.TclError:
                pass

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if not tb:
            style.theme_use("clam")
        palette = THEME_PALETTES.get(self.theme_name.get(), THEME_PALETTES["flatly"])
        page_bg = palette["page_bg"]
        card_bg = palette["card_bg"]
        soft_bg = palette["soft_bg"]
        heading_bg = palette["heading_bg"]
        text = palette["text"]
        muted = palette["muted"]
        field = palette["field"]
        primary = palette["primary"]
        primary_active = palette["primary_active"]
        secondary = palette["secondary"]
        secondary_active = palette["secondary_active"]
        selection = palette["selection"]
        entry_bg = palette["entry_bg"]

        self.configure(bg=page_bg)
        style.configure(".", font=("Malgun Gothic", 10), background=page_bg, foreground=text)
        style.configure("TFrame", background=page_bg)
        style.configure("TLabel", background=page_bg, foreground=text)
        style.configure("Title.TLabel", font=("Malgun Gothic", 14, "bold"), background=page_bg, foreground=text)
        style.configure("Muted.TLabel", background=page_bg, foreground=muted)
        style.configure("Card.TFrame", background=card_bg, relief=tk.FLAT)
        style.configure("Drop.TFrame", background=soft_bg, relief=tk.FLAT)
        style.configure("CardTitle.TLabel", font=("Malgun Gothic", 10, "bold"), background=card_bg, foreground=muted)
        style.configure("Count.TLabel", font=("Malgun Gothic", 11, "bold"), background=card_bg, foreground=text)
        style.configure("Field.TLabel", font=("Malgun Gothic", 10, "bold"), background=card_bg, foreground=field)
        style.configure("DropTitle.TLabel", font=("Malgun Gothic", 12, "bold"), background=soft_bg, foreground=primary)
        style.configure("DropText.TLabel", background=soft_bg, foreground=muted)
        style.configure("TEntry", fieldbackground=entry_bg, foreground=text, bordercolor=heading_bg, lightcolor=heading_bg, darkcolor=heading_bg)
        style.configure("Primary.TButton", font=("Malgun Gothic", 10, "bold"), foreground="#ffffff", background=primary)
        style.map("Primary.TButton", background=[("active", primary_active), ("disabled", "#64748b")])
        style.configure("Secondary.TButton", foreground=text, background=secondary)
        style.map("Secondary.TButton", background=[("active", secondary_active), ("disabled", secondary)])
        style.configure("Treeview", rowheight=24, fieldbackground=card_bg, background=card_bg, foreground=text)
        style.configure("Treeview.Heading", font=("Malgun Gothic", 10, "bold"), background=heading_bg, foreground=field)
        style.map("Treeview", background=[("selected", selection)], foreground=[("selected", text)])

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self)

        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="ZIP 파일 선택", command=self._choose_zip)
        file_menu.add_command(label="미리보기", command=self._preview)
        file_menu.add_command(label="라이브러리에 추가", command=self._install)
        file_menu.add_separator()
        file_menu.add_command(label="폴더 일괄 추가", command=self._choose_and_install_directory)
        file_menu.add_separator()
        file_menu.add_command(label="종료", command=self._quit_app)
        menu_bar.add_cascade(label="파일", menu=file_menu)

        library_menu = tk.Menu(menu_bar, tearoff=0)
        library_menu.add_command(label="라이브러리 위치 선택", command=self._choose_library_root)
        library_menu.add_command(label="라이브러리 상태 새로고침", command=self._refresh_library_view)
        library_menu.add_command(label="선택 항목 삭제", command=self._delete_selected_library_entries)
        menu_bar.add_cascade(label="라이브러리", menu=library_menu)

        self.watch_menu = tk.Menu(menu_bar, tearoff=0)
        self.watch_menu.add_command(label="감시 시작", command=self._toggle_watch)
        self.watch_menu.add_separator()
        self.watch_menu.add_command(label=f"수신 폴더: {self.watch_folders.incoming}", state=tk.DISABLED)
        self.watch_menu.add_command(label=f"백업 폴더: {self.watch_folders.processed}", state=tk.DISABLED)
        menu_bar.add_cascade(label="감시", menu=self.watch_menu)

        settings_menu = tk.Menu(menu_bar, tearoff=0)
        theme_menu = tk.Menu(settings_menu, tearoff=0)
        for theme in AVAILABLE_THEMES:
            theme_menu.add_radiobutton(
                label=theme,
                value=theme,
                variable=self.theme_name,
                command=self._change_theme,
            )
        settings_menu.add_cascade(label="스킨", menu=theme_menu)
        settings_menu.add_separator()
        settings_menu.add_checkbutton(
            label="윈도우 시작 시 자동 실행",
            variable=self.autostart_enabled,
            command=self._toggle_autostart_from_menu,
            onvalue=True,
            offvalue=False,
        )
        menu_bar.add_cascade(label="설정", menu=settings_menu)

        self.config(menu=menu_bar)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=14)
        self.root_frame = root
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        form = ttk.Frame(root, style="Card.TFrame", padding=14)
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(0, weight=3)
        form.columnconfigure(1, weight=3)
        form.columnconfigure(2, weight=0)

        zip_group = ttk.Frame(form, style="Card.TFrame")
        zip_group.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        zip_group.columnconfigure(0, weight=1)
        ttk.Label(zip_group, text="ZIP 파일", style="Field.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        zip_row = ttk.Frame(zip_group, style="Card.TFrame")
        zip_row.grid(row=1, column=0, sticky="ew")
        zip_row.columnconfigure(0, weight=1)
        self.zip_entry = ttk.Entry(zip_row, textvariable=self.zip_path)
        self.zip_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8), ipady=5)
        self.zip_button = ttk.Button(zip_row, text="찾기", style="Secondary.TButton", command=self._choose_zip)
        self.zip_button.grid(row=0, column=1, ipadx=8)

        library_group = ttk.Frame(form, style="Card.TFrame")
        library_group.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        library_group.columnconfigure(0, weight=1)
        ttk.Label(library_group, text="라이브러리 위치", style="Field.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        library_row = ttk.Frame(library_group, style="Card.TFrame")
        library_row.grid(row=1, column=0, sticky="ew")
        library_row.columnconfigure(0, weight=1)
        self.library_entry = ttk.Entry(library_row, textvariable=self.library_root)
        self.library_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8), ipady=5)
        self.library_button = ttk.Button(library_row, text="찾기", style="Secondary.TButton", command=self._choose_library_root)
        self.library_button.grid(row=0, column=1, ipadx=8)

        actions = ttk.Frame(form, style="Card.TFrame")
        actions.grid(row=0, column=2, sticky="sew")
        self.preview_button = ttk.Button(actions, text="미리보기", style="Secondary.TButton", command=self._preview)
        self.preview_button.pack(side=tk.LEFT, ipadx=10)
        self.install_button = ttk.Button(actions, text="라이브러리에 추가", style="Primary.TButton", command=self._install)
        self.install_button.pack(side=tk.LEFT, padx=(8, 0), ipadx=10)

        content = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        content.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

        library_card = ttk.Frame(content, style="Card.TFrame", padding=10)
        library_card.rowconfigure(1, weight=1)
        library_card.columnconfigure(0, weight=1)
        content.add(library_card, weight=4)

        library_header = ttk.Frame(library_card, style="Card.TFrame")
        library_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        library_header.columnconfigure(0, weight=1)
        library_header.columnconfigure(1, weight=0)
        ttk.Label(library_header, text="라이브러리 연결 상태", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        self.refresh_button = ttk.Button(library_header, text="새로고침", style="Secondary.TButton", command=self._refresh_library_view)
        self.refresh_button.grid(row=0, column=1, padx=(0, 6))
        self.delete_button = ttk.Button(library_header, text="선택 삭제", style="Secondary.TButton", command=self._delete_selected_library_entries)
        self.delete_button.grid(row=0, column=2)
        ttk.Label(library_header, textvariable=self.library_status, style="Muted.TLabel").grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(4, 0),
        )

        library_columns = ("symbol", "value", "footprint", "fp_ok", "model_ok")
        self.library_table = ttk.Treeview(library_card, columns=library_columns, show="headings")
        self.library_table.heading("symbol", text="심볼")
        self.library_table.heading("value", text="Value")
        self.library_table.heading("footprint", text="Footprint")
        self.library_table.heading("fp_ok", text="FP")
        self.library_table.heading("model_ok", text="3D")
        self.library_table.column("symbol", width=120, minwidth=80, anchor=tk.W)
        self.library_table.column("value", width=120, minwidth=80, anchor=tk.W)
        self.library_table.column("footprint", width=170, minwidth=120, anchor=tk.W)
        self.library_table.column("fp_ok", width=42, minwidth=42, anchor=tk.CENTER, stretch=False)
        self.library_table.column("model_ok", width=42, minwidth=42, anchor=tk.CENTER, stretch=False)
        self.library_table.grid(row=1, column=0, sticky="nsew")
        self.library_table.bind("<<TreeviewSelect>>", self._show_selected_library_entry)
        library_scroll = ttk.Scrollbar(library_card, orient=tk.VERTICAL, command=self.library_table.yview)
        library_scroll.grid(row=1, column=1, sticky="ns")
        self.library_table.configure(yscrollcommand=library_scroll.set)

        preview_card = ttk.Frame(content, style="Card.TFrame", padding=10)
        preview_card.rowconfigure(1, weight=3)
        preview_card.rowconfigure(3, weight=1)
        preview_card.columnconfigure(0, weight=1)
        content.add(preview_card, weight=3)

        detail_header = ttk.Frame(preview_card, style="Card.TFrame")
        detail_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        detail_header.columnconfigure(0, weight=1)
        ttk.Label(detail_header, text="선택 파츠 상세", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        self.save_detail_button = ttk.Button(detail_header, text="저장", style="Primary.TButton", command=self._save_selected_library_entry)
        self.save_detail_button.grid(row=0, column=1)

        detail_body = ttk.Frame(preview_card, style="Card.TFrame")
        detail_body.grid(row=1, column=0, sticky="nsew")
        detail_body.rowconfigure(2, weight=1)
        detail_body.columnconfigure(1, weight=1)
        ttk.Label(detail_body, text="심볼", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
        symbol_row = ttk.Frame(detail_body, style="Card.TFrame")
        symbol_row.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        symbol_row.columnconfigure(0, weight=1)
        self.symbol_value_label = ttk.Label(symbol_row, textvariable=self.selected_symbol, style="Count.TLabel", cursor="hand2")
        self.symbol_value_label.grid(row=0, column=0, sticky="w")
        self.symbol_value_label.bind("<Button-1>", self._copy_selected_symbol)
        ttk.Label(detail_body, text="3D 모델", style="CardTitle.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 8))
        self.model_entry = ttk.Entry(detail_body, textvariable=self.detail_model)
        self.model_entry.grid(row=1, column=1, sticky="ew", pady=(0, 8), ipady=4)

        property_columns = ("name", "value")
        self.property_table = ttk.Treeview(detail_body, columns=property_columns, show="headings", height=10)
        self.property_table.heading("name", text="속성")
        self.property_table.heading("value", text="값")
        self.property_table.column("name", width=130, minwidth=90, anchor=tk.W, stretch=False)
        self.property_table.column("value", width=300, minwidth=160, anchor=tk.W)
        self.property_table.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.property_table.bind("<<TreeviewSelect>>", self._select_property)
        property_scroll = ttk.Scrollbar(detail_body, orient=tk.VERTICAL, command=self.property_table.yview)
        property_scroll.grid(row=2, column=2, sticky="ns")
        self.property_table.configure(yscrollcommand=property_scroll.set)

        property_editor = ttk.Frame(detail_body, style="Card.TFrame")
        property_editor.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        property_editor.columnconfigure(1, weight=1)
        ttk.Label(property_editor, text="속성", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=(0, 6))
        ttk.Entry(property_editor, textvariable=self.property_name, width=18).grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(0, 6), ipady=3)
        ttk.Button(property_editor, text="추가/수정", style="Secondary.TButton", command=self._upsert_property).grid(row=0, column=2, padx=(0, 6), pady=(0, 6))
        ttk.Button(property_editor, text="삭제", style="Secondary.TButton", command=self._delete_property).grid(row=0, column=3, pady=(0, 6))
        ttk.Label(property_editor, text="값", style="CardTitle.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(property_editor, textvariable=self.property_value).grid(row=1, column=1, columnspan=3, sticky="ew", ipady=3)

        ttk.Label(preview_card, text="ZIP 작업", style="Field.TLabel").grid(row=2, column=0, sticky="w", pady=(12, 6))
        work_tabs = ttk.Notebook(preview_card)
        work_tabs.grid(row=3, column=0, sticky="nsew")

        preview_tab = ttk.Frame(work_tabs, style="Card.TFrame", padding=8)
        preview_tab.rowconfigure(1, weight=1)
        preview_tab.columnconfigure(0, weight=1)
        work_tabs.add(preview_tab, text="미리보기")

        summary = ttk.Frame(preview_tab, style="Card.TFrame")
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for column in range(3):
            summary.columnconfigure(column, weight=1)
        self._build_summary_card(summary, 0, "심볼", self.symbol_count)
        self._build_summary_card(summary, 1, "풋프린트", self.footprint_count)
        self._build_summary_card(summary, 2, "3D 모델", self.model_count)

        columns = ("kind", "source", "destination")
        self.items_table = ttk.Treeview(preview_tab, columns=columns, show="headings", height=5)
        self.items_table.heading("kind", text="종류")
        self.items_table.heading("source", text="ZIP 내부 경로")
        self.items_table.heading("destination", text="추가될 위치")
        self.items_table.column("kind", width=78, anchor=tk.CENTER, stretch=False)
        self.items_table.column("source", width=260, anchor=tk.W)
        self.items_table.column("destination", width=380, anchor=tk.W)
        self.items_table.grid(row=1, column=0, sticky="nsew")
        self.drop_target = self.items_table

        y_scroll = ttk.Scrollbar(preview_tab, orient=tk.VERTICAL, command=self.items_table.yview)
        y_scroll.grid(row=1, column=1, sticky="ns")
        self.items_table.configure(yscrollcommand=y_scroll.set)

        batch_tab = ttk.Frame(work_tabs, style="Card.TFrame", padding=8)
        batch_tab.rowconfigure(0, weight=1)
        batch_tab.columnconfigure(0, weight=1)
        work_tabs.add(batch_tab, text="일괄 결과")

        batch_columns = ("zip", "status", "message")
        self.batch_table = ttk.Treeview(batch_tab, columns=batch_columns, show="headings", height=5)
        self.batch_table.heading("zip", text="ZIP")
        self.batch_table.heading("status", text="상태")
        self.batch_table.heading("message", text="메시지")
        self.batch_table.column("zip", width=220, anchor=tk.W)
        self.batch_table.column("status", width=70, anchor=tk.CENTER, stretch=False)
        self.batch_table.column("message", width=420, anchor=tk.W)
        self.batch_table.grid(row=0, column=0, sticky="nsew")
        batch_scroll = ttk.Scrollbar(batch_tab, orient=tk.VERTICAL, command=self.batch_table.yview)
        batch_scroll.grid(row=0, column=1, sticky="ns")
        self.batch_table.configure(yscrollcommand=batch_scroll.set)

        status_bar = ttk.Frame(root)
        status_bar.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        status_bar.columnconfigure(0, weight=1)
        status_bar.columnconfigure(1, weight=0)
        ttk.Label(status_bar, textvariable=self.status, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(status_bar, textvariable=self.watch_status, style="Muted.TLabel").grid(row=0, column=1, sticky="e")

    def _build_summary_card(self, parent: ttk.Frame, column: int, title: str, value: tk.StringVar) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=(8, 4))
        card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 6, 0 if column == 2 else 6))
        ttk.Label(card, text=title, style="CardTitle.TLabel").pack(side=tk.LEFT)
        ttk.Label(card, textvariable=value, style="Count.TLabel").pack(side=tk.RIGHT)

    def _choose_zip(self) -> None:
        path = filedialog.askopenfilename(
            title="KiCad 파일이 들어있는 ZIP 선택",
            filetypes=[("ZIP 파일", "*.zip"), ("모든 파일", "*.*")],
        )
        if path:
            self.zip_path.set(path)

    def _register_drop_targets(self) -> None:
        if not self.dnd_enabled or DND_FILES is None:
            return

        for widget in (self.root_frame, self.zip_entry, self.drop_target):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._drop_zip)

    def _drop_zip(self, event) -> str:
        paths = [Path(path) for path in self.tk.splitlist(event.data)]
        zip_paths = dropped_zip_paths(paths)

        if len(zip_paths) != 1:
            messagebox.showerror("확인 필요", "ZIP 파일 하나만 끌어서 놓아주세요.")
            return COPY

        self.zip_path.set(zip_paths[0])
        if self.library_root.get():
            self._preview()
        else:
            self.status.set("ZIP 파일을 받았습니다. 라이브러리 위치를 선택하세요.")

        return COPY

    def _choose_library_root(self) -> None:
        path = filedialog.askdirectory(title="사내 KiCad 라이브러리 위치 선택")
        if path:
            self.library_root.set(path)
            self._save_current_settings()
            self._refresh_library_view()

    def _preview(self) -> None:
        self._run_job(self._preview_job)

    def _install(self) -> None:
        if not messagebox.askyesno("추가 확인", "선택한 ZIP 파일의 KiCad 자산을 라이브러리에 추가할까요?"):
            return
        self._run_job(self._install_job)

    def _choose_and_install_directory(self) -> None:
        try:
            library_root = Path(self.library_root.get())
            if not library_root.exists() or not library_root.is_dir():
                raise CollectorError("존재하는 라이브러리 폴더를 선택하세요.")
            self._save_current_settings()
        except CollectorError as exc:
            messagebox.showerror("확인 필요", str(exc))
            return

        path = filedialog.askdirectory(title="ZIP 파일이 들어있는 폴더 선택")
        if not path:
            return

        if not messagebox.askyesno("일괄 추가 확인", "선택한 폴더의 ZIP 파일들을 순서대로 라이브러리에 추가할까요?"):
            return

        self.batch_directory.set(path)
        self.status.set("일괄 추가 처리 중입니다.")
        self._set_busy(True)
        thread = threading.Thread(target=self._batch_install_job, args=(Path(path), library_root), daemon=True)
        thread.start()

    def _toggle_watch(self) -> None:
        if self.watch_enabled:
            self.watch_enabled = False
            self._set_watch_menu_label()
            self.watch_status.set("감시 중지")
            return

        if not self.library_root.get().strip():
            messagebox.showerror("확인 필요", "감시를 시작하려면 먼저 라이브러리 폴더를 선택하세요.")
            return

        library_root = Path(self.library_root.get())
        if not library_root.exists() or not library_root.is_dir():
            messagebox.showerror("확인 필요", "감시를 시작하려면 먼저 라이브러리 폴더를 선택하세요.")
            return

        self._save_current_settings()
        self.watch_enabled = True
        self._set_watch_menu_label()
        self.watch_status.set(f"감시 중: {self.watch_folders.incoming}")
        self._poll_watch_folder()

    def _set_watch_menu_label(self) -> None:
        if hasattr(self, "watch_menu"):
            label = "감시 중지" if self.watch_enabled else "감시 시작"
            self.watch_menu.entryconfigure(0, label=label)

    def _toggle_watch_from_tray(self) -> None:
        self.after(0, self._toggle_watch)

    def _toggle_autostart_from_tray(self) -> None:
        def toggle() -> None:
            try:
                enabled = not is_autostart_enabled()
                set_autostart_enabled(enabled)
                self.autostart_enabled.set(enabled)
            except AutostartError as exc:
                messagebox.showerror("자동 실행 설정 실패", str(exc))
        self.after(0, toggle)

    def _toggle_autostart_from_menu(self) -> None:
        try:
            set_autostart_enabled(self.autostart_enabled.get())
        except AutostartError as exc:
            self.autostart_enabled.set(_safe_autostart_enabled())
            messagebox.showerror("자동 실행 설정 실패", str(exc))

    def _poll_watch_folder(self) -> None:
        if not self.watch_enabled:
            return

        library_root = Path(self.library_root.get())
        if library_root.exists() and library_root.is_dir():
            results = process_watch_folder(library_root, self.watch_folders)
            if results:
                self._show_batch_results(results)
                self._notify("KiCad Parts Collector", f"자동 추가 완료: {len(results)}개 ZIP 처리")
                self.watch_enabled = True
                self._set_watch_menu_label()
                self.watch_status.set(f"감시 중: {self.watch_folders.incoming}")

        self.after(2000, self._poll_watch_folder)

    def _run_job(self, job) -> None:
        try:
            zip_path, library_root = self._validated_paths()
        except CollectorError as exc:
            messagebox.showerror("확인 필요", str(exc))
            return

        self.status.set("처리 중입니다.")
        self._set_busy(True)
        thread = threading.Thread(target=job, args=(zip_path, library_root), daemon=True)
        thread.start()

    def _preview_job(self, zip_path: Path, library_root: Path) -> None:
        try:
            items = build_install_plan(zip_path, library_root)
            self.after(0, self._show_items, "미리보기 완료", items)
        except CollectorError as exc:
            self.after(0, self._show_error, exc)

    def _install_job(self, zip_path: Path, library_root: Path) -> None:
        try:
            items = install_zip(zip_path, library_root)
            self.after(0, self._show_items, "추가 완료", items)
        except CollectorError as exc:
            self.after(0, self._show_error, exc)

    def _batch_install_job(self, zip_directory: Path, library_root: Path) -> None:
        try:
            results = install_zip_directory(zip_directory, library_root)
            self.after(0, self._show_batch_results, results)
        except CollectorError as exc:
            self.after(0, self._show_error, exc)

    def _validated_paths(self) -> tuple[Path, Path]:
        zip_path = Path(self.zip_path.get())
        library_root = Path(self.library_root.get())

        if not zip_path.is_file():
            raise CollectorError("ZIP 파일을 선택하세요.")
        if zip_path.suffix.lower() != ".zip":
            raise CollectorError("ZIP 파일만 처리할 수 있습니다.")
        if not library_root.exists() or not library_root.is_dir():
            raise CollectorError("존재하는 라이브러리 폴더를 선택하세요.")

        self._save_current_settings()
        return zip_path, library_root

    def _show_items(self, title: str, items) -> None:
        counts = summarize_items(items)
        self.symbol_count.set(str(counts.get("symbol", 0)))
        self.footprint_count.set(str(counts.get("footprint", 0)))
        self.model_count.set(str(counts.get("3d_model", 0)))

        self.items_table.delete(*self.items_table.get_children())
        for item in items:
            self.items_table.insert("", tk.END, values=(self._kind_label(item.kind), item.source, item.destination))

        self.status.set(title)
        if title == "추가 완료":
            self._notify("KiCad Parts Collector", "라이브러리 추가가 완료되었습니다.")
        self._set_busy(False)
        self._refresh_library_view()

    def _show_error(self, error: Exception) -> None:
        self.status.set("처리 실패")
        self._set_busy(False)
        messagebox.showerror("처리 실패", str(error))

    def _show_batch_results(self, results) -> None:
        self.batch_table.delete(*self.batch_table.get_children())
        ok_count = 0
        for result in results:
            status = "OK" if result.ok else "실패"
            if result.ok:
                ok_count += 1
            self.batch_table.insert("", tk.END, values=(result.zip_path.name, status, result.message))

        self.status.set(f"일괄 추가 완료: 성공 {ok_count}개 / 실패 {len(results) - ok_count}개")
        if ok_count:
            self._notify("KiCad Parts Collector", f"라이브러리 추가 완료: 성공 {ok_count}개 / 실패 {len(results) - ok_count}개")
        self._set_busy(False)
        self._refresh_library_view()

    def _refresh_library_view(self) -> None:
        library_root = Path(self.library_root.get())
        if not library_root.exists() or not library_root.is_dir():
            return

        try:
            entries = scan_library(library_root)
        except CollectorError as exc:
            self.library_status.set(f"라이브러리 상태: {exc}")
            self.library_table.delete(*self.library_table.get_children())
            self.library_entries = {}
            self._clear_entry_detail()
            return

        self.library_table.delete(*self.library_table.get_children())
        self.library_entries = {entry.symbol: entry for entry in entries}
        broken = 0
        for entry in entries:
            fp_status = "OK" if entry.footprint_ok else "누락"
            model_status = "OK" if entry.model_ok else "누락"
            if not entry.footprint_ok or not entry.model_ok:
                broken += 1
            self.library_table.insert(
                "",
                tk.END,
                iid=entry.symbol,
                values=(entry.symbol, entry.value, entry.footprint, fp_status, model_status),
            )

        self.library_status.set(f"라이브러리 상태: {len(entries)}개 / 문제 {broken}개")

    def _show_selected_library_entry(self, _event=None) -> None:
        selected = self.library_table.selection()
        if not selected:
            self._clear_entry_detail()
            return

        symbol = self.library_table.item(selected[0], "values")[0]
        entry = self.library_entries.get(symbol)
        if entry is None:
            self._clear_entry_detail()
            return

        self.selected_symbol.set(entry.symbol)
        self.detail_model.set(entry.model)
        self.current_properties = dict(entry.properties)
        self._fill_property_table()

    def _clear_entry_detail(self) -> None:
        self.selected_symbol.set("선택된 파츠 없음")
        self.detail_model.set("")
        self.property_name.set("")
        self.property_value.set("")
        self.current_properties = {}
        if hasattr(self, "property_table"):
            self.property_table.delete(*self.property_table.get_children())

    def _copy_selected_symbol(self, _event=None) -> None:
        symbol = self.selected_symbol.get()
        if symbol == "선택된 파츠 없음":
            return

        self.clipboard_clear()
        self.clipboard_append(symbol)
        self.status.set(f"심볼명 복사 완료: {symbol}")

    def _fill_property_table(self) -> None:
        self.property_table.delete(*self.property_table.get_children())
        preferred = ["Reference", "Value", "Footprint", "Datasheet", "Description"]
        ordered_names = [name for name in preferred if name in self.current_properties]
        ordered_names.extend(sorted(name for name in self.current_properties if name not in ordered_names))
        for name in ordered_names:
            self.property_table.insert("", tk.END, iid=name, values=(name, self.current_properties[name]))

    def _select_property(self, _event=None) -> None:
        selected = self.property_table.selection()
        if not selected:
            return

        name = selected[0]
        self.property_name.set(name)
        self.property_value.set(self.current_properties.get(name, ""))

    def _upsert_property(self) -> None:
        name = self.property_name.get().strip()
        if not name:
            messagebox.showerror("확인 필요", "속성 이름을 입력하세요.")
            return

        self.current_properties[name] = self.property_value.get()
        self._fill_property_table()

    def _delete_property(self) -> None:
        name = self.property_name.get().strip()
        if not name:
            messagebox.showerror("확인 필요", "삭제할 속성을 선택하세요.")
            return
        if name not in self.current_properties:
            return
        if not messagebox.askyesno("속성 삭제", f"{name} 속성을 삭제할까요?"):
            return

        del self.current_properties[name]
        self.property_name.set("")
        self.property_value.set("")
        self._fill_property_table()

    def _save_selected_library_entry(self) -> None:
        symbol = self.selected_symbol.get()
        if symbol == "선택된 파츠 없음":
            messagebox.showerror("확인 필요", "수정할 파츠를 선택하세요.")
            return
        if "Value" not in self.current_properties:
            messagebox.showerror("확인 필요", "Value 속성은 필요합니다.")
            return

        try:
            entry = update_library_entry(
                Path(self.library_root.get()),
                symbol,
                dict(self.current_properties),
                self.detail_model.get().strip(),
            )
        except CollectorError as exc:
            messagebox.showerror("저장 실패", str(exc))
            return

        self.status.set(f"저장 완료: {entry.symbol}")
        self._refresh_library_view()
        if self.library_table.exists(entry.symbol):
            self.library_table.selection_set(entry.symbol)
            self.library_table.focus(entry.symbol)
            self._show_selected_library_entry()

    def _delete_selected_library_entries(self) -> None:
        selected = list(self.library_table.selection())
        if not selected:
            messagebox.showerror("확인 필요", "삭제할 라이브러리 항목을 선택하세요.")
            return

        symbols = [self.library_table.item(item_id, "values")[0] for item_id in selected]
        if not messagebox.askyesno("삭제 확인", f"선택한 {len(symbols)}개 심볼과 연결된 라이브러리 내부 파일을 삭제할까요?"):
            return

        try:
            result = remove_library_entries(Path(self.library_root.get()), symbols)
        except CollectorError as exc:
            messagebox.showerror("삭제 실패", str(exc))
            return

        self.status.set(f"삭제 완료: 심볼 {result.symbols}개, 풋프린트 {result.footprints}개, 3D 모델 {result.models}개")
        self._refresh_library_view()
        self._clear_entry_detail()

    def _change_theme(self, _event=None) -> None:
        theme = self.theme_name.get()
        if theme not in AVAILABLE_THEMES:
            return

        if tb:
            self.style.theme_use(theme)
        self._configure_style()
        self._save_current_settings()
        self.update_idletasks()

    def _save_current_settings(self) -> None:
        save_settings(AppSettings(library_root=self.library_root.get().strip(), theme=self.theme_name.get()))

    def _set_busy(self, busy: bool) -> None:
        state = tk.DISABLED if busy else tk.NORMAL
        self.zip_button.configure(state=state)
        self.zip_entry.configure(state=state)
        self.library_entry.configure(state=state)
        self.library_button.configure(state=state)
        self.preview_button.configure(state=state)
        self.install_button.configure(state=state)
        self.refresh_button.configure(state=state)
        self.delete_button.configure(state=state)
        self.save_detail_button.configure(state=state)
        self.model_entry.configure(state=state)

    def _on_unmap(self, _event) -> None:
        if self.state() == "iconic" and not self.quitting:
            self.after(0, self._hide_to_tray)

    def _hide_to_tray(self) -> None:
        if pystray is None:
            self.iconify()
            return

        if self.tray_hidden:
            return

        self.tray_hidden = True
        self.withdraw()
        self._notify("KiCad Parts Collector", "시스템 트레이에서 계속 실행 중입니다.")

    def _show_window(self) -> None:
        self.tray_hidden = False
        self.deiconify()
        self.state("normal")
        self.lift()
        self.focus_force()

    def _quit_app(self) -> None:
        self.quitting = True
        self.watch_enabled = False
        if self.tray_icon is not None:
            self.tray_icon.stop()
        _release_single_instance()
        self.destroy()

    def _start_tray_icon(self) -> None:
        if pystray is None:
            return

        image = _tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("열기", lambda _icon, _item: self.after(0, self._show_window), default=True),
            pystray.MenuItem(
                "감시 시작/중지",
                lambda _icon, _item: self._toggle_watch_from_tray(),
                checked=lambda _item: self.watch_enabled,
            ),
            pystray.MenuItem(
                "시작 시 자동 실행",
                lambda _icon, _item: self._toggle_autostart_from_tray(),
                checked=lambda _item: _safe_autostart_enabled(),
            ),
            pystray.MenuItem("종료", lambda _icon, _item: self.after(0, self._quit_app)),
        )
        self.tray_icon = pystray.Icon("KiCadPartsCollector", image, "KiCad Parts Collector", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _notify(self, title: str, message: str) -> None:
        if self.tray_icon is None:
            return

        try:
            self.tray_icon.notify(message, title)
        except Exception:
            pass

    def _kind_label(self, kind: str) -> str:
        labels = {
            "symbol": "심볼",
            "footprint": "풋프린트",
            "3d_model": "3D 모델",
        }
        return labels.get(kind, kind)


def main() -> None:
    if not _acquire_single_instance():
        _show_already_running_message()
        return

    try:
        app = KicadPartsCollectorApp()
        app.mainloop()
    finally:
        _release_single_instance()
