"""
HotkeyManager — register global hotkeys in toggle or hold mode.
Keyboard-only hotkeys use the `keyboard` library.
Hotkeys that include mouse buttons (mouse1-5) use pynput.
"""

import keyboard

from logger import log

try:
    from pynput import mouse as _pm
    _PYNPUT_OK = True
except ImportError:
    _PYNPUT_OK = False
    log.warning("pynput not installed — mouse button hotkeys unavailable")

_MOUSE_NAMES = {"mouse1", "mouse2", "mouse3", "mouse4", "mouse5"}
_MOUSE_BUTTON_MAP = {
    "mouse1": "_pm.Button.left",    # resolved at runtime
    "mouse2": "_pm.Button.right",
    "mouse3": "_pm.Button.middle",
    "mouse4": "_pm.Button.x1",
    "mouse5": "_pm.Button.x2",
}


def _resolve_mouse_button(name: str):
    return {
        "mouse1": _pm.Button.left,
        "mouse2": _pm.Button.right,
        "mouse3": _pm.Button.middle,
        "mouse4": _pm.Button.x1,
        "mouse5": _pm.Button.x2,
    }.get(name)


class HotkeyManager:
    def __init__(self):
        self._hotkey: str | None = None
        self._release_hook = None
        self._mouse_listener = None
        self._held = False

    # ── Public API ────────────────────────────────────────────────────

    def register(
        self,
        hotkey: str,
        on_activate,
        on_deactivate=None,
        mode: str = "toggle",
    ):
        """
        Register a global hotkey.

        mode="toggle"  — on_activate fires on every press.
        mode="hold"    — on_activate fires on press, on_deactivate on release.
        """
        self.unregister()
        self._hotkey = hotkey
        self._held = False

        parts = [p.strip().lower() for p in hotkey.split("+")]
        has_mouse = any(p in _MOUSE_NAMES for p in parts)

        if has_mouse:
            if _PYNPUT_OK:
                self._register_mouse(parts, on_activate, on_deactivate, mode)
            else:
                log.error(
                    "Cannot register mouse hotkey %r — pynput not installed", hotkey
                )
        elif mode == "hold" and on_deactivate is not None:
            self._register_keyboard_hold(hotkey, parts, on_activate, on_deactivate)
        else:
            self._register_keyboard_toggle(hotkey, on_activate)

    def unregister(self):
        if self._hotkey:
            try:
                keyboard.remove_hotkey(self._hotkey)
            except Exception:
                pass
            self._hotkey = None

        if self._release_hook:
            try:
                keyboard.unhook(self._release_hook)
            except Exception:
                pass
            self._release_hook = None

        if self._mouse_listener:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None

        self._held = False

    def stop(self):
        self.unregister()
        try:
            keyboard.unhook_all()
        except Exception:
            pass

    # ── Keyboard-only registration ────────────────────────────────────

    def _register_keyboard_toggle(self, hotkey: str, callback):
        log.debug("Registering keyboard toggle: %s", hotkey)
        try:
            keyboard.add_hotkey(hotkey, callback, suppress=True)
        except Exception:
            keyboard.add_hotkey(hotkey, callback, suppress=False)

    def _register_keyboard_hold(
        self, hotkey: str, parts: list[str], on_press, on_release
    ):
        log.debug("Registering keyboard hold: %s", hotkey)
        trigger = parts[-1]   # last token is the main key

        def _activate():
            if not self._held:
                self._held = True
                log.debug("Hold hotkey pressed: %s", hotkey)
                on_press()

        def _check_release(event):
            if self._held and event.name and event.name.lower() == trigger:
                self._held = False
                log.debug("Hold hotkey released: %s", hotkey)
                on_release()

        try:
            keyboard.add_hotkey(hotkey, _activate, suppress=True)
        except Exception:
            keyboard.add_hotkey(hotkey, _activate, suppress=False)

        self._release_hook = keyboard.on_release(_check_release)

    # ── Mouse-button hotkey registration ─────────────────────────────

    def _register_mouse(
        self, parts: list[str], on_activate, on_deactivate, mode: str
    ):
        modifiers = [p for p in parts if p not in _MOUSE_NAMES]
        mouse_name = next(p for p in parts if p in _MOUSE_NAMES)
        target_btn = _resolve_mouse_button(mouse_name)

        log.debug(
            "Registering mouse hotkey: button=%s modifiers=%s mode=%s",
            mouse_name, modifiers, mode,
        )

        def _mods_ok():
            return all(keyboard.is_pressed(m) for m in modifiers)

        def _on_click(x, y, button, pressed):
            if button != target_btn or not _mods_ok():
                return

            if mode == "toggle":
                if pressed:
                    if not self._held:
                        self._held = True
                        log.debug("Mouse toggle ON: %s", mouse_name)
                        on_activate()
                    else:
                        self._held = False
                        log.debug("Mouse toggle OFF: %s", mouse_name)
                        if on_deactivate:
                            on_deactivate()
            elif mode == "hold":
                if pressed and not self._held:
                    self._held = True
                    log.debug("Mouse hold START: %s", mouse_name)
                    on_activate()
                elif not pressed and self._held:
                    self._held = False
                    log.debug("Mouse hold END: %s", mouse_name)
                    if on_deactivate:
                        on_deactivate()

        self._mouse_listener = _pm.Listener(on_click=_on_click)
        self._mouse_listener.start()
