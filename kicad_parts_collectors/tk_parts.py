from concurrent.futures import Future
import threading
import tkinter as tk
from tkinter import ttk

from .parts_search import PAGE_SIZE, part_specs, search_parts


def show_specs(parent, title, specs):
    dialog = tk.Toplevel(parent)
    dialog.title(f"부품 상세 스펙 · {title}")
    dialog.geometry("620x460")
    dialog.minsize(400, 300)
    dialog.transient(parent.winfo_toplevel())
    body = ttk.Frame(dialog, padding=6)
    body.pack(fill="both", expand=True)
    body.columnconfigure(0, weight=1)
    body.rowconfigure(0, weight=1)
    table = ttk.Treeview(body, columns=("name", "value"), show="headings")
    table.heading("name", text="항목")
    table.heading("value", text="값")
    table.column("name", width=160, minwidth=80, stretch=False)
    table.column("value", width=380, minwidth=160)
    table.grid(row=0, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(body, command=table.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    table.configure(yscrollcommand=scroll.set)
    value = tk.Text(body, height=4, wrap="word", state="disabled")
    value.grid(row=1, column=0, columnspan=2, sticky="ew", pady=4)
    for name, text in specs:
        table.insert("", "end", values=(name, text))

    def selected(_event):
        selection = table.selection()
        if selection:
            value.configure(state="normal")
            value.delete("1.0", "end")
            value.insert("1.0", table.item(selection[0], "values")[1])
            value.configure(state="disabled")

    table.bind("<<TreeviewSelect>>", selected)
    ttk.Button(body, text="닫기", command=dialog.destroy).grid(row=2, column=0, columnspan=2, sticky="e")
    return dialog


class PartsPanel(ttk.Frame):
    def __init__(self, parent, on_import):
        super().__init__(parent, padding=4)
        self.on_import = on_import
        self.query = tk.StringVar()
        self.status = tk.StringVar(value="JLCPCB 부품 검색")
        self.page, self.total = 1, 0
        self.last_query = ""
        self.rows = []
        self.future = None
        self.external_busy = False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        row = ttk.Frame(self)
        row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        row.columnconfigure(0, weight=1)
        self.entry = ttk.Entry(row, textvariable=self.query)
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.entry.bind("<Return>", lambda _: self.search(1))
        self.search_button = ttk.Button(row, text="검색", command=lambda: self.search(1))
        self.search_button.grid(row=0, column=1)
        columns = ("componentCode", "componentModelEn", "componentBrandEn",
                   "componentSpecificationEn", "componentTypeEn", "stockCount")
        self.table = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        for key, label, width in zip(columns, ("LCSC", "부품명", "제조사", "패키지", "카테고리", "재고"),
                                     (85, 160, 120, 95, 130, 75)):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=60, stretch=False)
        self.table.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(self, command=self.table.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.table.xview)
        horizontal.grid(row=2, column=0, sticky="ew")
        self.table.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.table.bind("<<TreeviewSelect>>", lambda _: self.controls())
        self.table.bind("<Double-1>", self.details)
        label = ttk.Label(self, textvariable=self.status, wraplength=350)
        label.grid(row=3, column=0, sticky="ew", pady=4)
        self.bind("<Configure>", lambda e: label.configure(wraplength=max(100, e.width-12)))
        actions = ttk.Frame(self)
        actions.grid(row=4, column=0, sticky="ew")
        actions.columnconfigure(1, weight=1)
        self.download = ttk.Button(actions, text="다운로드", command=self.import_part)
        self.download.grid(row=0, column=0)
        self.previous = ttk.Button(actions, text="이전", command=lambda: self.search(self.page-1))
        self.previous.grid(row=0, column=2)
        self.next = ttk.Button(actions, text="다음", command=lambda: self.search(self.page+1))
        self.next.grid(row=0, column=3)
        self.controls()

    def set_busy(self, busy):
        self.external_busy = busy
        self.controls()

    def controls(self):
        busy = self.external_busy or self.future is not None
        for widget in (self.entry, self.search_button):
            widget.configure(state="disabled" if busy else "normal")
        for widget, enabled in ((self.previous, self.page > 1),
                                (self.next, self.page * PAGE_SIZE < self.total),
                                (self.download, bool(self.table.selection()))):
            widget.configure(state="normal" if enabled and not busy else "disabled")

    def search(self, page):
        if self.external_busy or self.future is not None:
            return
        query = self.query.get().strip() if page == 1 else self.last_query
        if not query:
            self.status.set("검색어를 입력하세요.")
            return
        self.status.set(f"검색 중: {query}")
        self.rows = []
        self.table.delete(*self.table.get_children())
        self.future = Future()
        future = self.future
        self.controls()

        def work():
            try:
                future.set_result(search_parts(query, page))
            except Exception as exc:
                future.set_exception(exc)

        threading.Thread(target=work, daemon=True).start()
        self.after(100, self.finish, query, page)

    def finish(self, query, page):
        if not self.future.done():
            self.after(100, self.finish, query, page)
            return
        try:
            result = self.future.result()
            self.last_query, self.page, self.total = query, page, result["total"]
            self.rows = result["results"]
            for i, part in enumerate(self.rows):
                self.table.insert("", "end", iid=str(i), values=tuple(
                    "—" if part.get(key) is None else str(part[key]) for key in self.table["columns"]))
            pages = max(1, (self.total + PAGE_SIZE - 1) // PAGE_SIZE)
            self.status.set(f"{query} · {self.total:,}개 · {page}/{pages} 페이지" if self.rows else f"검색 결과 없음: {query}")
        except Exception as exc:
            self.total = 0
            self.page = 1
            self.status.set(f"검색 실패: {exc}")
        finally:
            self.future = None
            self.controls()

    def details(self, event):
        row = self.table.identify_row(event.y)
        if row and not self.external_busy:
            part = self.rows[int(row)]
            show_specs(self, part.get("componentModelEn") or part.get("componentCode", ""), part_specs(part))

    def import_part(self):
        selection = self.table.selection()
        if selection and not self.external_busy and self.future is None:
            self.on_import(self.rows[int(selection[0])]["componentCode"])
