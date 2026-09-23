from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QVBoxLayout


class PreviewWindow(QDialog):
    def __init__(self, url: str, symbol: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(f"{symbol} - 파트 미리보기")
        self.resize(740, 540)
        self.setMinimumSize(460, 360)
        icon = Path(__file__).resolve().parent.parent / "assets/app_icon.png"
        self.setWindowIcon(QIcon(str(icon)))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.error = QLabel("미리보기 화면을 불러올 수 없습니다. 창을 닫고 다시 열어 주세요.")
        self.error.setWordWrap(True)
        self.error.setContentsMargins(12, 8, 12, 8)
        self.error.hide()
        layout.addWidget(self.error)
        self.view = QWebEngineView(self)
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        self.view.loadFinished.connect(lambda ok: self.error.setVisible(not ok))
        layout.addWidget(self.view, 1)
        self.view.load(QUrl(url))


def attach_owner(dialog: PreviewWindow, owner: int):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.IsWindow.argtypes = [ctypes.c_void_p]
    user32.IsWindow.restype = ctypes.c_bool
    if not user32.IsWindow(owner):
        raise RuntimeError("미리보기의 본창을 찾을 수 없습니다.")
    ctypes.set_last_error(0)
    user32.SetWindowLongPtrW(int(dialog.winId()), -8, owner)
    if ctypes.get_last_error():
        raise ctypes.WinError(ctypes.get_last_error())
    # 본창이 종료되면 미리보기 프로세스도 함께 종료한다.
    timer = QTimer(dialog)
    timer.timeout.connect(lambda: None if user32.IsWindow(owner) else dialog.close())
    timer.start(500)


def main():
    index = sys.argv.index("--part-preview")
    url, owner, symbol = sys.argv[index + 1:index + 4]
    app = QApplication([sys.argv[0]])
    dialog = PreviewWindow(url, symbol)
    attach_owner(dialog, int(owner))
    dialog.show()
    app.exec()


if __name__ == "__main__":
    main()
