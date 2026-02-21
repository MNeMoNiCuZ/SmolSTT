from PyQt6 import QtCore, QtGui, QtWidgets

from theme import normalize_theme, theme_colors

NOTIFICATION_ANCHORS = {
    "bottom_right",
    "bottom_left",
    "top_right",
    "top_left",
    "top_center",
    "bottom_center",
    "left_center",
    "right_center",
}


def normalize_anchor(anchor: str) -> str:
    key = str(anchor or "bottom_right").strip().lower()
    return key if key in NOTIFICATION_ANCHORS else "bottom_right"


def anchored_position(
    geo: QtCore.QRect,
    width: int,
    height: int,
    anchor: str,
    margin_x: int = 20,
    margin_y: int = 40,
) -> tuple[int, int]:
    a = normalize_anchor(anchor)
    w = max(1, int(width))
    h = max(1, int(height))
    mx = max(0, int(margin_x))
    my = max(0, int(margin_y))

    left = geo.x() + mx
    right = geo.x() + geo.width() - w - mx
    top = geo.y() + my
    bottom = geo.y() + geo.height() - h - my
    cx = geo.x() + (geo.width() - w) // 2
    cy = geo.y() + (geo.height() - h) // 2

    if a == "top_left":
        x, y = left, top
    elif a == "top_right":
        x, y = right, top
    elif a == "bottom_left":
        x, y = left, bottom
    elif a == "top_center":
        x, y = cx, top
    elif a == "bottom_center":
        x, y = cx, bottom
    elif a == "left_center":
        x, y = left, cy
    elif a == "right_center":
        x, y = right, cy
    else:
        x, y = right, bottom

    x = max(geo.x(), min(x, geo.x() + geo.width() - w))
    y = max(geo.y(), min(y, geo.y() + geo.height() - h))
    return int(x), int(y)


class _ToastWidget(QtWidgets.QWidget):
    def __init__(
        self,
        title: str,
        message: str,
        theme: str,
        font_size: int,
        width: int,
        anchor: str,
        speed_badge: str = "",
    ):
        super().__init__()
        colors = theme_colors(theme)
        self._content_width = max(50, int(width))
        self._anchor = normalize_anchor(anchor)
        self._full_text = message
        self._hovered = False
        self._font_size = max(9, font_size)
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
        body.setFont(QtGui.QFont("Segoe UI", self._font_size))
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

        self._card = card

        self.set_speed_badge(speed_badge)
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

    def set_speed_badge(self, text: str):
        # Speed badge is rendered as a separate floating widget by ToastNotification.
        self._reflow()

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
        self._card.setFixedWidth(self._content_width)
        margins = self._layout.contentsMargins()
        body_width = max(20, self._content_width - margins.left() - margins.right())
        self._body.setFixedWidth(body_width)
        self._body.adjustSize()
        self._card.adjustSize()
        self.setFixedSize(self._card.width(), self._card.height())
        self._card.move(0, 0)

class _SpeedBadgeWidget(QtWidgets.QWidget):
    def __init__(self, text: str, theme: str, font_size: int):
        super().__init__()
        colors = theme_colors(theme)
        self._hovered = False
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        label = QtWidgets.QLabel(text, self)
        f = QtGui.QFont("Segoe UI", max(8, int(font_size) - 1))
        f.setBold(True)
        label.setFont(f)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(
            "QLabel {"
            f"color: {colors['text']};"
            f"background: {colors['panel']};"
            f"border: 1px solid {colors['border']};"
            "border-radius: 7px;"
            "padding: 1px 7px;"
            "}"
        )
        fm = label.fontMetrics()
        w = max(56, fm.horizontalAdvance(text) + 20)
        h = max(20, fm.height() + 8)
        label.setGeometry(0, 0, w, h)
        self.setFixedSize(w, h)
        self._label = label
        self.setToolTip(
            "Speed stats badge:\n"
            "- cps = characters per second\n"
            "- s = total round-trip time\n"
            "Current request: latest transcription only.\n"
            "Average: combined throughput over recent requests."
        )

    def is_hovered(self) -> bool:
        return self._hovered

    def enterEvent(self, event):
        self._hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        super().leaveEvent(event)

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
        self._speed_badges: dict[_ToastWidget, _SpeedBadgeWidget] = {}
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
        speed_badge: str = "",
        anchor: str = "bottom_right",
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
        badge = (speed_badge or "").strip()
        pos_anchor = normalize_anchor(anchor)
        self._ui.call_soon(lambda: self._show_ui(title, message, vd, t, fs, w, mh, fid, fd, badge, pos_anchor))

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
        speed_badge: str,
        anchor: str,
    ):
        self._crossfade_existing_toasts(max(80, int(fade_in_duration_ms)))
        geo = self._ui.available_geometry()
        max_screen_width = max(50, geo.width() - 40)
        toast_width = min(width, max_screen_width)
        toast = _ToastWidget(title, message, theme, font_size, toast_width, anchor=anchor, speed_badge="")
        toast.set_full_text(message)
        if max_height > 0:
            self._fit_message_to_height(toast, message, geo, max_height)
        self._active_toasts.append(toast)
        toast.destroyed.connect(lambda *_: self._forget_toast(toast))
        x, y = anchored_position(geo, toast.width(), toast.height(), anchor, margin_x=20, margin_y=40)
        toast.move(x, y)
        badge_text = (speed_badge or "").strip()
        badge = None
        if badge_text:
            badge = _SpeedBadgeWidget(badge_text, theme, font_size)
            bx, by = self._badge_position(geo, QtCore.QRect(x, y, toast.width(), toast.height()), badge.width(), badge.height(), anchor)
            badge.move(bx, by)
            self._speed_badges[toast] = badge
        initial_opacity = 0.0 if fade_in_duration_ms > 0 else 1.0
        self._set_toast_opacity(toast, initial_opacity)
        toast.show()
        if badge is not None:
            badge.show()
        if fade_in_duration_ms > 0:
            self._start_fade_in(
                toast,
                fade_in_duration_ms,
                lambda: self._start_lifecycle(toast, visible_duration_ms, fade_duration_ms),
            )
        else:
            self._start_lifecycle(toast, visible_duration_ms, fade_duration_ms)

    def _crossfade_existing_toasts(self, duration_ms: int):
        if not self._active_toasts:
            return
        step_ms = 16
        total = max(step_ms, int(duration_ms))
        for old_toast in list(self._active_toasts):
            fade_timer = self._fade_in_timers.pop(old_toast, None)
            if fade_timer is not None:
                try:
                    fade_timer.stop()
                except RuntimeError:
                    pass
            life_timer = self._life_timers.pop(old_toast, None)
            if life_timer is not None:
                try:
                    life_timer.stop()
                except RuntimeError:
                    pass
            start_op = 1.0
            try:
                start_op = float(old_toast.windowOpacity())
            except RuntimeError:
                continue
            state = {"remain": total}
            timer = QtCore.QTimer()
            self._life_timers[old_toast] = timer

            def _tick(toast_ref=old_toast, t=timer, start=start_op, s=state):
                if toast_ref not in self._active_toasts:
                    t.stop()
                    return
                s["remain"] = max(0, int(s["remain"]) - step_ms)
                op = (float(s["remain"]) / float(total)) * start
                self._set_toast_opacity(toast_ref, op)
                if s["remain"] <= 0:
                    t.stop()
                    self._close_toast(toast_ref)

            timer.timeout.connect(_tick)
            timer.start(step_ms)

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
            self._set_toast_opacity(toast, 1.0)
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
            self._set_toast_opacity(toast, opacity)
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
            if self._is_pointer_over_toast_or_badge(toast):
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
            self._set_toast_opacity(toast, opacity)
            if remaining_fade <= 0:
                timer.stop()
                self._close_toast(toast)

        timer.timeout.connect(_tick)
        timer.start(step_ms)

    def _close_toast(self, toast: _ToastWidget):
        badge = self._speed_badges.pop(toast, None)
        if badge is not None:
            try:
                badge.close()
            except RuntimeError:
                pass
        if toast in self._active_toasts:
            toast.close()

    def _forget_toast(self, toast: _ToastWidget):
        timer = self._fade_in_timers.pop(toast, None)
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass
        timer = self._life_timers.pop(toast, None)
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass
        badge = self._speed_badges.pop(toast, None)
        if badge is not None:
            try:
                badge.close()
            except RuntimeError:
                pass
        if toast in self._active_toasts:
            self._active_toasts.remove(toast)

    def _badge_position(
        self,
        geo: QtCore.QRect,
        toast_rect: QtCore.QRect,
        badge_w: int,
        badge_h: int,
        anchor: str,
    ) -> tuple[int, int]:
        a = normalize_anchor(anchor)
        gap = 0
        if a == "bottom_right":
            x = toast_rect.x() + toast_rect.width() - badge_w
            y = toast_rect.y() - badge_h - gap
        elif a == "bottom_left":
            x = toast_rect.x()
            y = toast_rect.y() - badge_h - gap
        elif a == "top_left":
            x = toast_rect.x()
            y = toast_rect.y() + toast_rect.height() + gap
        elif a == "top_right":
            x = toast_rect.x() + toast_rect.width() - badge_w
            y = toast_rect.y() + toast_rect.height() + gap
        elif a == "left_center":
            x = toast_rect.x()
            y = toast_rect.y() - badge_h - gap
        elif a == "right_center":
            x = toast_rect.x() + toast_rect.width() - badge_w
            y = toast_rect.y() - badge_h - gap
        elif a == "top_center":
            x = toast_rect.x() + (toast_rect.width() - badge_w) // 2
            y = toast_rect.y() + toast_rect.height() + gap
        else:  # bottom_center
            x = toast_rect.x() + (toast_rect.width() - badge_w) // 2
            y = toast_rect.y() - badge_h - gap
        x = max(geo.x(), min(x, geo.x() + geo.width() - badge_w))
        y = max(geo.y(), min(y, geo.y() + geo.height() - badge_h))
        return int(x), int(y)

    def _set_toast_opacity(self, toast: _ToastWidget, opacity: float):
        op = max(0.0, min(1.0, float(opacity)))
        toast.setWindowOpacity(op)
        badge = self._speed_badges.get(toast)
        if badge is not None:
            badge.setWindowOpacity(op)

    def _is_pointer_over_toast_or_badge(self, toast: _ToastWidget) -> bool:
        try:
            pos = QtGui.QCursor.pos()
        except Exception:
            return False
        try:
            if toast.isVisible() and toast.frameGeometry().contains(pos):
                return True
        except Exception:
            pass
        badge = self._speed_badges.get(toast)
        if badge is not None:
            try:
                if badge.isVisible() and badge.frameGeometry().contains(pos):
                    return True
            except Exception:
                pass
        return False


class _SpinnerWidget(QtWidgets.QWidget):
    def __init__(self, theme: str, label: str, font_size: int):
        super().__init__()
        self._theme = normalize_theme(theme)
        self._label = label
        self._font_size = max(9, min(int(font_size), 24))
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(146, 112)
        self._angle = 0

    def tick(self):
        self._angle = (self._angle + 24) % 360
        self.update()

    def set_theme(self, theme: str):
        self._theme = normalize_theme(theme)
        self.update()

    def set_label(self, label: str):
        self._label = (label or "Transcribing").strip()
        self.update()

    def set_font_size(self, font_size: int):
        self._font_size = max(9, min(int(font_size), 24))
        self.update()

    def paintEvent(self, _event):
        colors = theme_colors(self._theme)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        rect = QtCore.QRectF(2, 2, 142, 108)
        painter.setBrush(QtGui.QColor(colors["panel"]))
        painter.setPen(QtGui.QPen(QtGui.QColor(colors["border"]), 1))
        painter.drawRoundedRect(rect, 16, 16)

        painter.setPen(QtGui.QPen(QtGui.QColor(colors["accent"]), 4))
        painter.drawArc(50, 24, 46, 46, -self._angle * 16, -300 * 16)

        painter.setPen(QtGui.QPen(QtGui.QColor(colors["text"]), 1))
        draw_rect = QtCore.QRect(8, 72, 130, 28)
        draw_font = QtGui.QFont("Segoe UI", self._font_size)
        for size in range(self._font_size, 7, -1):
            draw_font.setPointSize(size)
            metrics = QtGui.QFontMetrics(draw_font)
            if metrics.horizontalAdvance(self._label) <= draw_rect.width():
                break
        painter.setFont(draw_font)
        metrics = QtGui.QFontMetrics(draw_font)
        text = metrics.elidedText(self._label, QtCore.Qt.TextElideMode.ElideRight, draw_rect.width())
        painter.drawText(draw_rect, QtCore.Qt.AlignmentFlag.AlignCenter, text)


class ProcessingSpinner:
    def __init__(self, ui_host):
        self._ui = ui_host
        self._widget: _SpinnerWidget | None = None
        self._timer: QtCore.QTimer | None = None

    def show(
        self,
        theme: str = "dark",
        label: str = "Transcribing",
        font_size: int = 11,
        anchor: str = "bottom_right",
    ):
        t = normalize_theme(theme)
        text = (label or "Transcribing").strip()
        fs = max(9, min(int(font_size), 24))
        pos_anchor = normalize_anchor(anchor)
        self._ui.call_soon(lambda: self._show_ui(t, text, fs, pos_anchor))

    def hide(self):
        self._ui.call_soon(self._hide_ui)

    def _show_ui(self, theme: str, label: str, font_size: int, anchor: str):
        if self._widget is None:
            self._widget = _SpinnerWidget(theme, label, font_size)
        else:
            self._widget.set_theme(theme)
            self._widget.set_label(label)
            self._widget.set_font_size(font_size)

        geo = self._ui.available_geometry()
        x, y = anchored_position(geo, self._widget.width(), self._widget.height(), anchor, margin_x=20, margin_y=40)
        self._widget.move(x, y)
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
