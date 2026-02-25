import os
import sys
from typing import Callable

from PyQt6 import QtCore, QtGui, QtWidgets

from logger import log
from theme import normalize_theme


class _UiInvoker(QtCore.QObject):
    invoke = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.invoke.connect(self._run, QtCore.Qt.ConnectionType.QueuedConnection)

    @QtCore.pyqtSlot(object)
    def _run(self, fn):
        try:
            fn()
        except Exception as exc:
            log.exception("UI dispatch failed: %s", exc)


class UIHost:
    def __init__(self):
        self._configure_qt_boot_env()
        self._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)
        icon = self._resolve_app_icon()
        if icon is not None:
            self._app.setWindowIcon(icon)
        self._invoker = _UiInvoker()
        self._theme = "dark"

    def _configure_qt_boot_env(self):
        # On some Windows environments DPI awareness is already set by another
        # component before Qt initializes. Qt then logs:
        # "SetProcessDpiAwarenessContext() failed: Access is denied."
        # This is benign but noisy; suppress this specific Qt category.
        rules = os.environ.get("QT_LOGGING_RULES", "").strip()
        target = "qt.qpa.window=false"
        if target in rules:
            return
        if rules:
            os.environ["QT_LOGGING_RULES"] = f"{rules};{target}"
        else:
            os.environ["QT_LOGGING_RULES"] = target

    def _resolve_app_icon(self) -> QtGui.QIcon | None:
        runtime_root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(__file__)))
        candidates = [
            os.path.join(runtime_root, "assets", "smolstt.ico"),
            os.path.join(os.path.dirname(__file__), "assets", "smolstt.ico"),
            os.path.join(os.path.dirname(__file__), "smolstt.ico"),
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "src", "assets", "smolstt.ico"),
        ]
        for path in candidates:
            if os.path.exists(path):
                icon = QtGui.QIcon(path)
                if not icon.isNull():
                    return icon
        return None

    def call_soon(self, fn: Callable[[], None]) -> None:
        self._invoker.invoke.emit(fn)

    def run(self) -> int:
        return self._app.exec()

    def quit(self) -> None:
        self.call_soon(self._app.quit)

    def available_geometry(self) -> QtCore.QRect:
        screen = self._app.primaryScreen()
        if screen is None:
            return QtCore.QRect(0, 0, 1280, 720)
        return screen.availableGeometry()

    def set_theme(self, theme: str):
        self._theme = normalize_theme(theme)

    def get_theme(self) -> str:
        return self._theme
