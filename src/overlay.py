from PyQt6 import QtCore, QtGui, QtWidgets

from theme import normalize_theme, theme_colors
from toast import anchored_position, normalize_anchor

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
        self._base_diameter = 20
        self.setFixedSize(46, 46)
        self._bright = True
        self._scale = 0.5

    def toggle_state(self) -> None:
        self._bright = not self._bright
        self.update()

    def set_theme(self, theme: str):
        self._theme = normalize_theme(theme)
        self.update()

    def set_scale(self, scale: float):
        target = max(0.5, min(2.0, float(scale)))
        # Smooth motion to avoid jitter from chunk-to-chunk level changes.
        self._scale = (self._scale * 0.88) + (target * 0.12)
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
        diameter = int(round(self._base_diameter * self._scale))
        diameter = max(int(round(self._base_diameter * 0.5)), min(self._base_diameter * 2, diameter))
        x = (self.width() - diameter) // 2
        y = (self.height() - diameter) // 2
        painter.drawEllipse(x, y, diameter, diameter)


class RecordingOverlay:
    def __init__(self, ui_host, anchor_getter=None):
        self._ui = ui_host
        self._anchor_getter = anchor_getter
        self._dot: _OverlayDot | None = None
        self._timer: QtCore.QTimer | None = None
        self._preview_timer: QtCore.QTimer | None = None
        self._preview_phase = 0.0
        self._preview_active = False
        self._preview_anchor: str | None = None

    def show(self):
        self._ui.call_soon(self._show_ui)

    def hide(self):
        self._ui.call_soon(self._hide_ui)

    def set_rms(self, rms_value: float):
        self._ui.call_soon(lambda: self._set_rms_ui(rms_value))

    def preview_pulse(self, duration_ms: int = 1000, anchor: str | None = None):
        self._ui.call_soon(lambda: self._start_preview_ui(duration_ms, anchor))

    def _show_ui(self):
        if self._dot is None:
            self._dot = _OverlayDot(self._ui.get_theme())
        else:
            self._dot.set_theme(self._ui.get_theme())
        geo = self._ui.available_geometry()
        anchor = "bottom_right"
        if self._preview_anchor:
            anchor = normalize_anchor(self._preview_anchor)
        elif callable(self._anchor_getter):
            try:
                anchor = normalize_anchor(self._anchor_getter())
            except Exception:
                anchor = "bottom_right"
        x, y = anchored_position(geo, self._dot.width(), self._dot.height(), anchor, margin_x=20, margin_y=40)
        # Move inward from anchored edges by half size (away from the edge/corner).
        dx = self._dot.width() // 2
        dy = self._dot.height() // 2
        if "right" in anchor:
            x -= dx
        elif "left" in anchor:
            x += dx
            if anchor == "bottom_left":
                x += max(6, self._dot.width() // 6)
        if "bottom" in anchor:
            y -= dy
        elif "top" in anchor:
            y += dy
        # Move one full max-dot size toward the anchored edge/corner.
        max_dot = int(round(self._dot._base_diameter * 2))
        if "right" in anchor:
            x += max_dot
        elif "left" in anchor:
            x -= max_dot
        if "bottom" in anchor:
            y += max_dot
        elif "top" in anchor:
            y -= max_dot
        # Keep fully onscreen.
        x = max(geo.x(), min(x, geo.x() + geo.width() - self._dot.width()))
        y = max(geo.y(), min(y, geo.y() + geo.height() - self._dot.height()))
        self._dot.move(x, y)
        self._dot.show()
        self._dot.set_scale(0.5)

        if self._timer is None:
            self._timer = QtCore.QTimer()
            self._timer.timeout.connect(self._dot.toggle_state)
        self._timer.start(500)

    def _hide_ui(self):
        if self._timer is not None:
            self._timer.stop()
        if self._preview_timer is not None:
            self._preview_timer.stop()
        self._preview_active = False
        if self._dot is not None:
            self._dot.hide()
            self._dot.set_scale(0.5)

    def _set_rms_ui(self, rms_value: float):
        if self._dot is None or not self._dot.isVisible():
            return
        if self._preview_active:
            return
        try:
            rms = max(0.0, float(rms_value))
        except (TypeError, ValueError):
            return
        # Map RMS roughly to dBFS and normalize into [0.5, 2.0].
        # int16 full scale is 32768; clamp floor to avoid log(0).
        import math
        dbfs = 20.0 * math.log10(max(rms, 1.0) / 32768.0)
        normalized = (dbfs + 65.0) / 53.0  # about -65dBFS..-12dBFS
        normalized = max(0.0, min(1.0, normalized))
        scale = 0.5 + (normalized * 1.5)
        self._dot.set_scale(scale)

    def _start_preview_ui(self, duration_ms: int, anchor: str | None = None):
        self._preview_anchor = normalize_anchor(anchor) if anchor else None
        self._show_ui()
        self._preview_active = True
        self._preview_phase = 0.0
        if self._preview_timer is None:
            self._preview_timer = QtCore.QTimer()
            self._preview_timer.timeout.connect(self._tick_preview)
        self._preview_timer.start(33)
        stop_ms = max(250, int(duration_ms))
        QtCore.QTimer.singleShot(stop_ms, self._stop_preview_ui)

    def _tick_preview(self):
        if self._dot is None or not self._dot.isVisible():
            return
        import math
        self._preview_phase += 0.22
        s = 0.5 + ((math.sin(self._preview_phase) + 1.0) * 0.5) * 1.5
        self._dot.set_scale(s)

    def _stop_preview_ui(self):
        if self._preview_timer is not None:
            self._preview_timer.stop()
        self._preview_active = False
        self._preview_anchor = None
        self._hide_ui()
