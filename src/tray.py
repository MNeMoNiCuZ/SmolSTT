from PyQt6 import QtCore, QtGui, QtWidgets

from logger import log
from theme import menu_stylesheet, normalize_theme, theme_colors

TRAY_TOOLTIP = "SmolSTT - Minimalistic Speech To Text"


class TrayIcon:
    def __init__(self, app):
        self._app = app
        self._tray: QtWidgets.QSystemTrayIcon | None = None
        self._menu: QtWidgets.QMenu | None = None
        self._capture_action: QtGui.QAction | None = None
        self._recording = False

    def start(self):
        log.info("Starting system tray icon")
        self._app._ui.call_soon(self._start_ui)

    def _start_ui(self):
        if self._tray is not None:
            return

        self._tray = QtWidgets.QSystemTrayIcon()
        self._tray.setToolTip(TRAY_TOOLTIP)
        self._tray.setIcon(self._make_icon(recording=False))

        self._menu = QtWidgets.QMenu()
        self._capture_action = self._menu.addAction("Capture")
        self._capture_action.triggered.connect(self._on_capture)

        self._menu.addSeparator()
        settings_action = self._menu.addAction("Settings")
        settings_action.triggered.connect(self._on_settings)
        self._menu.addSeparator()
        quit_action = self._menu.addAction("Quit")
        quit_action.triggered.connect(self._on_quit)

        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)

        self.refresh_theme()
        self._tray.show()
        log.info("Tray icon running")

    def refresh_theme(self):
        def _apply():
            if self._menu is None or self._tray is None:
                return
            theme = normalize_theme(self._app.current_theme())
            self._menu.setStyleSheet(menu_stylesheet(theme))
            self._tray.setIcon(self._make_icon(self._recording, theme))

        self._app._ui.call_soon(_apply)

    def set_recording(self, recording: bool):
        self._recording = recording

        def _apply():
            if self._tray is None:
                return
            theme = normalize_theme(self._app.current_theme())
            self._tray.setIcon(self._make_icon(recording, theme))
            self._tray.setToolTip(TRAY_TOOLTIP)
            if self._capture_action is not None:
                self._capture_action.setText("Stop Capture" if recording else "Capture")

        self._app._ui.call_soon(_apply)

    def set_processing(self):
        self._app._ui.call_soon(lambda: self._tray and self._tray.setToolTip(TRAY_TOOLTIP))

    def set_status(self, text: str):
        self._app._ui.call_soon(lambda: self._tray and self._tray.setToolTip(TRAY_TOOLTIP))

    def stop(self):
        log.info("Stopping tray icon")

        def _stop():
            if self._tray:
                self._tray.hide()

        self._app._ui.call_soon(_stop)

    def _on_capture(self):
        log.debug("Tray toggle clicked (recording=%s)", self._recording)
        self._app.toggle()

    def _on_settings(self):
        log.debug("Tray: Settings clicked")
        self._app.open_settings()

    def _on_quit(self):
        log.info("Tray: Quit clicked")
        self._app.quit()

    def _on_activated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason):
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
            self._on_capture()
        elif reason == QtWidgets.QSystemTrayIcon.ActivationReason.MiddleClick:
            self._on_settings()

    def _make_icon(self, recording: bool, theme: str | None = None) -> QtGui.QIcon:
        theme = normalize_theme(theme or self._app.current_theme())
        colors = theme_colors(theme)

        pix = QtGui.QPixmap(64, 64)
        pix.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pix)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        bg = QtGui.QColor(colors["tray_record"] if recording else colors["tray_idle"])
        painter.setBrush(bg)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, 60, 60)

        fg = QtGui.QColor("#ffffff")
        painter.setPen(QtGui.QPen(fg, 4, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        painter.setBrush(QtGui.QBrush(fg))

        # Mic capsule
        painter.drawRoundedRect(22, 10, 20, 30, 10, 10)

        # Thicker straight stand + base (no arc)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(fg))
        painter.drawRoundedRect(27, 40, 10, 14, 3, 3)
        painter.drawRoundedRect(20, 55, 24, 6, 3, 3)
        painter.end()

        return QtGui.QIcon(pix)
