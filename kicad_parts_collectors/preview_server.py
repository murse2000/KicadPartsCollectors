from __future__ import annotations

import base64
import json
import secrets
import threading
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .preview import KINDS, render_preview

ASSETS = Path(__file__).with_name("preview_assets")
_server = None
_sessions = {}
_lock = threading.Lock()


class PreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        # 로컬 미리보기 주소만 허용하고 파일 시스템 경로는 요청으로 받지 않는다.
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self.send_error(403)
            return
        parts = self.path.split("?")[0].strip("/").split("/")
        if len(parts) != 2 or parts[0] not in _sessions:
            self.send_error(404)
            return
        root, entry = _sessions[parts[0]]
        route = parts[1]
        if route in ("index.html", "viewer.js"):
            data = (ASSETS / route).read_bytes()
            content_type = "text/html; charset=utf-8" if route.endswith("html") else "text/javascript"
        elif route == "part":
            data = json.dumps({"symbol": entry.symbol, "footprint": entry.footprint}).encode()
            content_type = "application/json"
        elif route in ("symbol", "footprint", "model"):
            kind = KINDS[("symbol", "footprint", "model").index(route)]
            try:
                pages = render_preview(root, entry, kind)
                data = json.dumps({"pages": [{"name": name, "data": base64.b64encode(blob).decode()}
                                             for name, blob in pages]}).encode()
            except Exception as exc:
                data = json.dumps({"error": str(exc)}).encode()
            content_type = "application/json"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass


def preview_url(root, entry):
    global _server
    with _lock:
        if _server is None:
            _server = ThreadingHTTPServer(("127.0.0.1", 0), PreviewHandler)
            threading.Thread(target=_server.serve_forever, daemon=True).start()
        token = secrets.token_urlsafe(24)
        _sessions[token] = (root, entry)
        return f"http://127.0.0.1:{_server.server_port}/{token}/index.html"


def release_preview(url):
    token = url.rstrip("/").split("/")[-2]
    with _lock:
        _sessions.pop(token, None)


def open_preview(root, entry, parent):
    import ctypes
    from tkinter import messagebox

    # Tk와 Qt 이벤트 루프를 분리하고 미리보기 창의 소유자는 본창으로 지정한다.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    owner = user32.GetAncestor(parent.winfo_id(), 2)
    url = preview_url(root, entry)
    command = ([sys.executable] if getattr(sys, "frozen", False)
               else [sys.executable, "-m", "kicad_parts_collectors.preview_window"])
    command += ["--part-preview", url, str(owner), entry.symbol]
    environment = os.environ.copy()
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    try:
        process = subprocess.Popen(command, env=environment,
                                   cwd=str(Path(__file__).resolve().parent.parent),
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError as exc:
        release_preview(url)
        messagebox.showerror("미리보기 실행 실패", str(exc), parent=parent)
        return

    def poll():
        result = process.poll()
        if result is None:
            parent.after(300, poll)
        else:
            release_preview(url)
            if result:
                messagebox.showerror("미리보기 실행 실패", f"내장 뷰어가 종료되었습니다. (코드 {result})", parent=parent)

    parent.after(300, poll)
