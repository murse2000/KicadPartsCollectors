from __future__ import annotations

import threading
import tkinter as tk
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


AVAILABLE_THEMES = ("flatly", "cosmo", "litera", "minty", "pulse", "darkly", "superhero", "cyborg", "solar")
DARK_THEMES = {"darkly", "superhero", "cyborg", "solar"}


def dropped_zip_paths(paths) -> list[str]:
    return [str(path) for path in paths if Path(path).suffix.lower() == ".zip"]


def _tray_image() -> Image.Image:
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
        self.batch_directory = tk.StringVar()
        self.watch_status = tk.StringVar(value="감시 중지")
        self.watch_enabled = False
        self.watch_folders = ensure_watch_folders()
        self.tray_icon = None
        self.tray_hidden = False
        self.quitting = False

        self.dnd_enabled = self._enable_drag_and_drop()
        self._configure_style()
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

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if not tb:
            style.theme_use("clam")
        dark = self.theme_name.get() in DARK_THEMES
        page_bg = "#111827" if dark else "#f4f7fb"
        card_bg = "#1f2937" if dark else "#ffffff"
        soft_bg = "#263447" if dark else "#eef6ff"
        heading_bg = "#303b4d" if dark else "#eef3fb"
        text = "#f8fafc" if dark else "#172033"
        muted = "#b7c3d3" if dark else "#657084"
        field = "#dbeafe" if dark else "#273247"
        primary = "#38bdf8" if dark else "#2563eb"
        primary_active = "#0ea5e9" if dark else "#1d4ed8"
        secondary = "#334155" if dark else "#eef3fb"
        secondary_active = "#475569" if dark else "#e2eaf6"
        selection = "#0f766e" if dark else "#dbeafe"
        entry_bg = "#111827" if dark else "#ffffff"

        self.configure(bg=page_bg)
        style.configure(".", font=("Malgun Gothic", 10), background=page_bg, foreground=text)
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

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=14)
        self.root_frame = root
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="KiCad Parts Collector", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="심볼은 단일 라이브러리 파일에 병합하고, 풋프린트는 단일 .pretty 폴더에 추가합니다.",
            style="Muted.TLabel",
        ).grid(row=0, column=1, sticky="e")
        skin_bar = ttk.Frame(header)
        skin_bar.grid(row=1, column=1, sticky="e", pady=(6, 0))
        ttk.Label(skin_bar, text="스킨", style="Muted.TLabel").pack(side=tk.LEFT, padx=(0, 6))
        self.theme_combo = ttk.Combobox(skin_bar, textvariable=self.theme_name, values=AVAILABLE_THEMES, state="readonly", width=12)
        self.theme_combo.pack(side=tk.LEFT)
        self.theme_combo.bind("<<ComboboxSelected>>", self._change_theme)

        form = ttk.Frame(root, style="Card.TFrame", padding=10)
        form.grid(row=1, column=0, sticky="ew")
        form.columnconfigure(1, weight=3)
        form.columnconfigure(4, weight=2)

        ttk.Label(form, text="ZIP", style="Field.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.zip_entry = ttk.Entry(form, textvariable=self.zip_path)
        self.zip_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), ipady=4)
        self.zip_button = ttk.Button(form, text="찾기", style="Secondary.TButton", command=self._choose_zip)
        self.zip_button.grid(row=0, column=2, padx=(0, 12), ipadx=8)

        ttk.Label(form, text="라이브러리", style="Field.TLabel").grid(row=0, column=3, sticky="w", padx=(0, 8))
        self.library_entry = ttk.Entry(form, textvariable=self.library_root)
        self.library_entry.grid(row=0, column=4, sticky="ew", padx=(0, 8), ipady=4)
        self.library_button = ttk.Button(form, text="찾기", style="Secondary.TButton", command=self._choose_library_root)
        self.library_button.grid(row=0, column=5, padx=(0, 8), ipadx=8)

        actions = ttk.Frame(form, style="Card.TFrame")
        actions.grid(row=0, column=6, sticky="e")
        self.preview_button = ttk.Button(actions, text="미리보기", style="Secondary.TButton", command=self._preview)
        self.preview_button.pack(side=tk.LEFT, ipadx=8)
        self.install_button = ttk.Button(actions, text="라이브러리에 추가", style="Primary.TButton", command=self._install)
        self.install_button.pack(side=tk.LEFT, padx=(6, 0), ipadx=8)
        self.batch_button = ttk.Button(actions, text="폴더 일괄 추가", style="Secondary.TButton", command=self._choose_and_install_directory)
        self.batch_button.pack(side=tk.LEFT, padx=(6, 0), ipadx=8)
        self.watch_button = ttk.Button(actions, text="감시 시작", style="Secondary.TButton", command=self._toggle_watch)
        self.watch_button.pack(side=tk.LEFT, padx=(6, 0), ipadx=8)

        content = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        content.grid(row=2, column=0, sticky="nsew", pady=(10, 0))

        library_card = ttk.Frame(content, style="Card.TFrame", padding=10)
        library_card.rowconfigure(1, weight=1)
        library_card.columnconfigure(0, weight=1)
        content.add(library_card, weight=3)

        library_header = ttk.Frame(library_card, style="Card.TFrame")
        library_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        library_header.columnconfigure(0, weight=1)
        ttk.Label(library_header, text="라이브러리 연결 상태", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(library_header, textvariable=self.library_status, style="Muted.TLabel").grid(row=0, column=1, sticky="e", padx=(0, 8))
        self.refresh_button = ttk.Button(library_header, text="새로고침", style="Secondary.TButton", command=self._refresh_library_view)
        self.refresh_button.grid(row=0, column=2, padx=(0, 6))
        self.delete_button = ttk.Button(library_header, text="선택 삭제", style="Secondary.TButton", command=self._delete_selected_library_entries)
        self.delete_button.grid(row=0, column=3)

        library_columns = ("symbol", "value", "footprint", "fp_ok", "model_ok")
        self.library_table = ttk.Treeview(library_card, columns=library_columns, show="headings")
        self.library_table.heading("symbol", text="심볼")
        self.library_table.heading("value", text="Value")
        self.library_table.heading("footprint", text="Footprint")
        self.library_table.heading("fp_ok", text="FP")
        self.library_table.heading("model_ok", text="3D")
        self.library_table.column("symbol", width=150, anchor=tk.W)
        self.library_table.column("value", width=150, anchor=tk.W)
        self.library_table.column("footprint", width=230, anchor=tk.W)
        self.library_table.column("fp_ok", width=48, anchor=tk.CENTER, stretch=False)
        self.library_table.column("model_ok", width=48, anchor=tk.CENTER, stretch=False)
        self.library_table.grid(row=1, column=0, sticky="nsew")
        library_scroll = ttk.Scrollbar(library_card, orient=tk.VERTICAL, command=self.library_table.yview)
        library_scroll.grid(row=1, column=1, sticky="ns")
        self.library_table.configure(yscrollcommand=library_scroll.set)

        preview_card = ttk.Frame(content, style="Card.TFrame", padding=10)
        preview_card.rowconfigure(2, weight=3)
        preview_card.rowconfigure(4, weight=2)
        preview_card.columnconfigure(0, weight=1)
        content.add(preview_card, weight=2)

        preview_header = ttk.Frame(preview_card, style="Card.TFrame")
        preview_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        preview_header.columnconfigure(0, weight=1)
        ttk.Label(preview_header, text="ZIP 추가 대상", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(preview_header, text="표 위에 ZIP 파일을 드롭할 수 있습니다.", style="Muted.TLabel").grid(row=0, column=1, sticky="e")

        summary = ttk.Frame(preview_card, style="Card.TFrame")
        summary.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for column in range(3):
            summary.columnconfigure(column, weight=1)
        self._build_summary_card(summary, 0, "심볼", self.symbol_count)
        self._build_summary_card(summary, 1, "풋프린트", self.footprint_count)
        self._build_summary_card(summary, 2, "3D 모델", self.model_count)

        columns = ("kind", "source", "destination")
        self.items_table = ttk.Treeview(preview_card, columns=columns, show="headings")
        self.items_table.heading("kind", text="종류")
        self.items_table.heading("source", text="ZIP 내부 경로")
        self.items_table.heading("destination", text="추가될 위치")
        self.items_table.column("kind", width=78, anchor=tk.CENTER, stretch=False)
        self.items_table.column("source", width=260, anchor=tk.W)
        self.items_table.column("destination", width=380, anchor=tk.W)
        self.items_table.grid(row=2, column=0, sticky="nsew")
        self.drop_target = self.items_table

        y_scroll = ttk.Scrollbar(preview_card, orient=tk.VERTICAL, command=self.items_table.yview)
        y_scroll.grid(row=2, column=1, sticky="ns")
        self.items_table.configure(yscrollcommand=y_scroll.set)

        ttk.Label(preview_card, text="일괄 추가 결과", style="Field.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 6))
        batch_columns = ("zip", "status", "message")
        self.batch_table = ttk.Treeview(preview_card, columns=batch_columns, show="headings")
        self.batch_table.heading("zip", text="ZIP")
        self.batch_table.heading("status", text="상태")
        self.batch_table.heading("message", text="메시지")
        self.batch_table.column("zip", width=220, anchor=tk.W)
        self.batch_table.column("status", width=70, anchor=tk.CENTER, stretch=False)
        self.batch_table.column("message", width=420, anchor=tk.W)
        self.batch_table.grid(row=4, column=0, sticky="nsew")
        batch_scroll = ttk.Scrollbar(preview_card, orient=tk.VERTICAL, command=self.batch_table.yview)
        batch_scroll.grid(row=4, column=1, sticky="ns")
        self.batch_table.configure(yscrollcommand=batch_scroll.set)

        status_bar = ttk.Frame(root)
        status_bar.grid(row=3, column=0, sticky="ew", pady=(8, 0))
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
            self.watch_button.configure(text="감시 시작")
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
        self.watch_button.configure(text="감시 중지")
        self.watch_status.set(f"감시 중: {self.watch_folders.incoming}")
        self._poll_watch_folder()

    def _toggle_watch_from_tray(self) -> None:
        self.after(0, self._toggle_watch)

    def _toggle_autostart_from_tray(self) -> None:
        def toggle() -> None:
            try:
                set_autostart_enabled(not is_autostart_enabled())
            except AutostartError as exc:
                messagebox.showerror("자동 실행 설정 실패", str(exc))
        self.after(0, toggle)

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
                self.watch_button.configure(text="감시 중지")
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
            return

        self.library_table.delete(*self.library_table.get_children())
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

    def _change_theme(self, _event=None) -> None:
        theme = self.theme_name.get()
        if theme not in AVAILABLE_THEMES:
            return

        if tb:
            ttk.Style(self).theme_use(theme)
        self._configure_style()
        self._save_current_settings()

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
        self.batch_button.configure(state=state)
        self.watch_button.configure(state=state)
        self.refresh_button.configure(state=state)
        self.delete_button.configure(state=state)
        self.theme_combo.configure(state="disabled" if busy else "readonly")

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
    app = KicadPartsCollectorApp()
    app.mainloop()
