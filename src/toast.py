from PyQt6 import QtCore, QtGui, QtWidgets

from theme import normalize_theme, theme_colors


class _ToastWidget(QtWidgets.QWidget):
    def __init__(self, title: str, message: str, theme: str, font_size: int, width: int):
        super().__init__()
        colors = theme_colors(theme)
        self._content_width = max(50, int(width))
        self._full_text = message
        self._hovered = False
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

        card = QtWidgets.QFrame(self)
        card.setObjectName("card")
        card.setStyleSheet(
            "QFrame#card {"
            f"background: {colors['panel']};"
            f"border: 1px solid {colors['border']};"
            "border-radius: 12px;"
            "}"
            f"QLabel {{ color: {colors['text']}; }}"
        )

        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        self._layout = layout

        body = QtWidgets.QLabel(message)
        self._body = body
        body.setFont(QtGui.QFont("Segoe UI", max(9, font_size)))
        body.setWordWrap(True)
        body.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop
        )
        body.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
            | QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        body.setCursor(QtCore.Qt.CursorShape.IBeamCursor)
        body.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        body.customContextMenuRequested.connect(
            lambda pos: self._show_context_menu(body.mapToGlobal(pos))
        )
        layout.addWidget(body)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)
        self._card = card

        self._reflow()
        self._copy_shortcut = QtGui.QShortcut(
            QtGui.QKeySequence.StandardKey.Copy, self
        )
        self._copy_shortcut.activated.connect(self.copy_text)

    def set_message(self, message: str):
        self._body.setText(message)
        self._reflow()

    def set_full_text(self, message: str):
        self._full_text = message

    def is_hovered(self) -> bool:
        return self._hovered

    def copy_text(self):
        selected = self._body.selectedText().strip()
        text = selected if selected else self._full_text
        if text:
            QtWidgets.QApplication.clipboard().setText(text)

    def _show_context_menu(self, global_pos):
        menu = QtWidgets.QMenu(self)
        copy_action = menu.addAction("Copy Text")
        chosen = menu.exec(global_pos)
        if chosen == copy_action:
            self.copy_text()

    def _reflow(self):
        self.setFixedWidth(self._content_width)
        margins = self._layout.contentsMargins()
        body_width = max(20, self._content_width - margins.left() - margins.right())
        self._body.setFixedWidth(body_width)
        self._body.adjustSize()
        self._card.adjustSize()
        self.adjustSize()

    def enterEvent(self, event):
        self._hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        super().leaveEvent(event)

    def contextMenuEvent(self, event):
        self._show_context_menu(event.globalPos())
        event.accept()

    def mousePressEvent(self, event):
        self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)


class ToastNotification:
    def __init__(self, ui_host):
        self._ui = ui_host
        self._active_toasts: list[_ToastWidget] = []
        self._fade_in_timers: dict[_ToastWidget, QtCore.QTimer] = {}
        self._life_timers: dict[_ToastWidget, QtCore.QTimer] = {}

    def show(
        self,
        title: str,
        message: str,
        duration_ms: int = 4000,
        theme: str = "dark",
        font_size: int = 11,
        width: int = 390,
        max_height: int = 0,
        fade_in_duration_ms: int = 100,
        visible_duration_ms: int = 4000,
        fade_duration_ms: int = 220,
    ):
        t = normalize_theme(theme)
        fs = max(9, min(int(font_size), 24))
        try:
            w = int(width)
        except (TypeError, ValueError):
            w = 390
        w = max(50, min(w, 2400))
        try:
            mh = int(max_height)
        except (TypeError, ValueError):
            mh = 0
        mh = max(0, min(mh, 2400))
        try:
            fid = int(fade_in_duration_ms)
        except (TypeError, ValueError):
            fid = 100
        fid = max(0, min(fid, 10000))
        try:
            vd = int(visible_duration_ms)
        except (TypeError, ValueError):
            vd = duration_ms
        vd = max(300, min(vd, 60000))
        try:
            fd = int(fade_duration_ms)
        except (TypeError, ValueError):
            fd = 220
        fd = max(0, min(fd, 10000))
        self._ui.call_soon(lambda: self._show_ui(title, message, vd, t, fs, w, mh, fid, fd))

    def _show_ui(
        self,
        title: str,
        message: str,
        visible_duration_ms: int,
        theme: str,
        font_size: int,
        width: int,
        max_height: int,
        fade_in_duration_ms: int,
        fade_duration_ms: int,
    ):
        geo = self._ui.available_geometry()
        max_screen_width = max(50, geo.width() - 40)
        toast_width = min(width, max_screen_width)
        toast = _ToastWidget(title, message, theme, font_size, toast_width)
        toast.set_full_text(message)
        if max_height > 0:
            self._fit_message_to_height(toast, message, geo, max_height)
        self._active_toasts.append(toast)
        toast.destroyed.connect(lambda *_: self._forget_toast(toast))
        x = geo.x() + geo.width() - toast.width() - 20
        y = geo.y() + geo.height() - toast.height() - 40
        y = min(y, geo.y() + geo.height() - toast.height() - 20)
        y = max(y, geo.y() + 20)
        toast.move(x, y)
        toast.setWindowOpacity(0.0 if fade_in_duration_ms > 0 else 1.0)
        toast.show()
        if fade_in_duration_ms > 0:
            self._start_fade_in(
                toast,
                fade_in_duration_ms,
                lambda: self._start_lifecycle(toast, visible_duration_ms, fade_duration_ms),
            )
        else:
            self._start_lifecycle(toast, visible_duration_ms, fade_duration_ms)

    def _fit_message_to_height(self, toast: _ToastWidget, message: str, geo, user_max_height: int):
        screen_limit = max(60, geo.height() - 40)
        limit = max(20, min(screen_limit, int(user_max_height)))
        if toast.height() <= limit:
            return

        lo = 0
        hi = len(message)
        best = "..."
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = (message[:mid].rstrip() + "...") if mid < len(message) else message
            toast.set_message(candidate)
            if toast.height() <= limit:
                best = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        toast.set_message(best)

    def _start_fade_in(self, toast: _ToastWidget, fade_in_duration_ms: int, on_done):
        if toast not in self._active_toasts:
            return
        if fade_in_duration_ms <= 0:
            toast.setWindowOpacity(1.0)
            on_done()
            return

        fade_step_ms = 16
        steps = max(1, int(fade_in_duration_ms / fade_step_ms))
        delta = 1.0 / float(steps)
        timer = QtCore.QTimer()
        self._fade_in_timers[toast] = timer

        def _tick():
            if toast not in self._active_toasts:
                timer.stop()
                return
            opacity = min(1.0, toast.windowOpacity() + delta)
            toast.setWindowOpacity(opacity)
            if opacity >= 1.0:
                timer.stop()
                self._fade_in_timers.pop(toast, None)
                on_done()

        timer.timeout.connect(_tick)
        timer.start(fade_step_ms)

    def _start_lifecycle(self, toast: _ToastWidget, visible_duration_ms: int, fade_duration_ms: int):
        if toast not in self._active_toasts:
            return
        step_ms = 16
        remaining_visible = max(0, int(visible_duration_ms))
        remaining_fade = max(0, int(fade_duration_ms))
        total_fade = max(1, remaining_fade)
        timer = QtCore.QTimer()
        self._life_timers[toast] = timer

        def _tick():
            if toast not in self._active_toasts:
                timer.stop()
                return
            if toast.is_hovered():
                return

            nonlocal remaining_visible, remaining_fade
            if remaining_visible > 0:
                remaining_visible = max(0, remaining_visible - step_ms)
                return

            if remaining_fade <= 0:
                timer.stop()
                self._close_toast(toast)
                return

            remaining_fade = max(0, remaining_fade - step_ms)
            opacity = max(0.0, float(remaining_fade) / float(total_fade))
            toast.setWindowOpacity(opacity)
            if remaining_fade <= 0:
                timer.stop()
                self._close_toast(toast)

        timer.timeout.connect(_tick)
        timer.start(step_ms)

    def _close_toast(self, toast: _ToastWidget):
        if toast in self._active_toasts:
            toast.close()

    def _forget_toast(self, toast: _ToastWidget):
        timer = self._fade_in_timers.pop(toast, None)
        if timer is not None:
            timer.stop()
        timer = self._life_timers.pop(toast, None)
        if timer is not None:
            timer.stop()
        if toast in self._active_toasts:
            self._active_toasts.remove(toast)


class _SpinnerWidget(QtWidgets.QWidget):
    def __init__(self, theme: str):
        super().__init__()
        self._theme = normalize_theme(theme)
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(110, 110)
        self._angle = 0

    def tick(self):
        self._angle = (self._angle + 24) % 360
        self.update()

    def set_theme(self, theme: str):
        self._theme = normalize_theme(theme)
        self.update()

    def paintEvent(self, _event):
        colors = theme_colors(self._theme)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        rect = QtCore.QRectF(2, 2, 106, 106)
        painter.setBrush(QtGui.QColor(colors["panel"]))
        painter.setPen(QtGui.QPen(QtGui.QColor(colors["border"]), 1))
        painter.drawRoundedRect(rect, 16, 16)

        painter.setPen(QtGui.QPen(QtGui.QColor(colors["accent"]), 4))
        painter.drawArc(32, 24, 46, 46, -self._angle * 16, -300 * 16)

        painter.setPen(QtGui.QPen(QtGui.QColor(colors["text"]), 1))
        painter.drawText(QtCore.QRect(0, 72, 110, 24), QtCore.Qt.AlignmentFlag.AlignCenter, "Transcribing")


class ProcessingSpinner:
    def __init__(self, ui_host):
        self._ui = ui_host
        self._widget: _SpinnerWidget | None = None
        self._timer: QtCore.QTimer | None = None

    def show(self, theme: str = "dark"):
        t = normalize_theme(theme)
        self._ui.call_soon(lambda: self._show_ui(t))

    def hide(self):
        self._ui.call_soon(self._hide_ui)

    def _show_ui(self, theme: str):
        if self._widget is None:
            self._widget = _SpinnerWidget(theme)
        else:
            self._widget.set_theme(theme)

        geo = self._ui.available_geometry()
        self._widget.move(geo.x() + geo.width() - self._widget.width() - 22, geo.y() + geo.height() - self._widget.height() - 48)
        self._widget.show()

        if self._timer is None:
            self._timer = QtCore.QTimer()
            self._timer.timeout.connect(self._widget.tick)
        self._timer.start(55)

    def _hide_ui(self):
        if self._timer is not None:
            self._timer.stop()
        if self._widget is not None:
            self._widget.hide()
