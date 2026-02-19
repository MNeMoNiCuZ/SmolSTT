import sys
from typing import Callable

from PyQt6 import QtCore, QtWidgets

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
        self._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)
        self._invoker = _UiInvoker()
        self._theme = "dark"

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
