from PyQt6 import QtCore, QtGui, QtWidgets

from theme import normalize_theme, theme_colors

class _OverlayDot(QtWidgets.QWidget):
    def __init__(self, theme: str):
        super().__init__()
        self._theme = normalize_theme(theme)
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(22, 22)
        self._bright = True

    def toggle_state(self) -> None:
        self._bright = not self._bright
        self.update()

    def set_theme(self, theme: str):
        self._theme = normalize_theme(theme)
        self.update()

    def paintEvent(self, _event):
        colors = theme_colors(self._theme)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        if self._bright:
            color = QtGui.QColor(colors["tray_record"])
        else:
            color = QtGui.QColor("#24262b")
        painter.setBrush(color)
        painter.setPen(QtGui.QPen(QtGui.QColor("#000000"), 2))
        painter.drawEllipse(1, 1, 20, 20)


class RecordingOverlay:
    def __init__(self, ui_host):
        self._ui = ui_host
        self._dot: _OverlayDot | None = None
        self._timer: QtCore.QTimer | None = None

    def show(self):
        self._ui.call_soon(self._show_ui)

    def hide(self):
        self._ui.call_soon(self._hide_ui)

    def _show_ui(self):
        if self._dot is None:
            self._dot = _OverlayDot(self._ui.get_theme())
        else:
            self._dot.set_theme(self._ui.get_theme())
        geo = self._ui.available_geometry()
        x = geo.x() + geo.width() - self._dot.width() - 24
        y = geo.y() + geo.height() - self._dot.height() - 40
        self._dot.move(x, y)
        self._dot.show()

        if self._timer is None:
            self._timer = QtCore.QTimer()
            self._timer.timeout.connect(self._dot.toggle_state)
        self._timer.start(500)

    def _hide_ui(self):
        if self._timer is not None:
            self._timer.stop()
        if self._dot is not None:
            self._dot.hide()
