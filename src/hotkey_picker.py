import keyboard
from PyQt6 import QtCore, QtWidgets

from logger import log

try:
    from pynput import keyboard as _pk
    from pynput import mouse as _pm

    _PYNPUT_OK = True
except ImportError:
    _PYNPUT_OK = False
    _pk = None
    _pm = None

_MOD_ORDER = ["ctrl", "shift", "alt", "windows"]

_MAIN_KEYS = [
    "space",
    "enter",
    "tab",
    "esc",
    "backspace",
    "delete",
    "insert",
    "home",
    "end",
    "page up",
    "page down",
    "up",
    "down",
    "left",
    "right",
]
_MAIN_KEYS += [chr(code) for code in range(ord("a"), ord("z") + 1)]
_MAIN_KEYS += [str(digit) for digit in range(10)]
_MAIN_KEYS += [f"f{i}" for i in range(1, 13)]
_MAIN_KEYS += [
    "num 0",
    "num 1",
    "num 2",
    "num 3",
    "num 4",
    "num 5",
    "num 6",
    "num 7",
    "num 8",
    "num 9",
    "num +",
    "num -",
    "num *",
    "num /",
    "num .",
]
if _PYNPUT_OK:
    _MAIN_KEYS += ["mouse1", "mouse2", "mouse3", "mouse4", "mouse5"]


class HotkeyPickerDialog(QtWidgets.QDialog):
    def __init__(self, current: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Hotkey")
        self.setModal(True)
        self.setMinimumWidth(560)

        self._recording = False
        self._pressed: set[str] = set()
        self._has_trigger = False
        self._kb_listener = None
        self._mouse_listener = None
        self._keyboard_hook = None

        layout = QtWidgets.QVBoxLayout(self)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Combination:"))
        self._combo = QtWidgets.QLineEdit(current)
        row.addWidget(self._combo, 1)
        self._record_btn = QtWidgets.QPushButton("Record")
        self._record_btn.clicked.connect(self._toggle_record)
        row.addWidget(self._record_btn)
        clear_btn = QtWidgets.QPushButton("Clear")
        clear_btn.clicked.connect(self._clear)
        row.addWidget(clear_btn)
        layout.addLayout(row)

        mod_box = QtWidgets.QGroupBox("Modifiers")
        mod_layout = QtWidgets.QHBoxLayout(mod_box)
        self._mod_checks: dict[str, QtWidgets.QCheckBox] = {}
        for name in _MOD_ORDER:
            cb = QtWidgets.QCheckBox(name.capitalize())
            cb.toggled.connect(self._on_manual_change)
            self._mod_checks[name] = cb
            mod_layout.addWidget(cb)
        layout.addWidget(mod_box)

        key_row = QtWidgets.QHBoxLayout()
        key_row.addWidget(QtWidgets.QLabel("Main key:"))
        self._main_key = QtWidgets.QComboBox()
        self._main_key.setEditable(True)
        self._main_key.addItems(_MAIN_KEYS)
        self._main_key.currentTextChanged.connect(self._on_manual_change)
        key_row.addWidget(self._main_key, 1)
        layout.addLayout(key_row)

        self._status = QtWidgets.QLabel("Use checkboxes + key, or Record.")
        layout.addWidget(self._status)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._apply_combo_to_controls(current)

    def get(self) -> str | None:
        if self.exec() == int(QtWidgets.QDialog.DialogCode.Accepted):
            value = self._combo.text().strip().lower()
            return value or None
        return None

    def accept(self):
        self._stop_record()
        super().accept()

    def reject(self):
        self._stop_record()
        super().reject()

    def _clear(self):
        self._combo.setText("")
        self._apply_combo_to_controls("")

    def _apply_combo_to_controls(self, combo: str):
        parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
        mods = set(p for p in parts if p in _MOD_ORDER)
        main = next((p for p in reversed(parts) if p not in _MOD_ORDER), "")
        for name, cb in self._mod_checks.items():
            cb.blockSignals(True)
            cb.setChecked(name in mods)
            cb.blockSignals(False)
        self._main_key.blockSignals(True)
        self._main_key.setCurrentText(main)
        self._main_key.blockSignals(False)

    def _on_manual_change(self):
        if self._recording:
            return
        mods = [name for name in _MOD_ORDER if self._mod_checks[name].isChecked()]
        main = self._main_key.currentText().strip().lower()
        self._combo.setText("+".join(mods + ([main] if main else [])))

    def _toggle_record(self):
        if self._recording:
            self._stop_record()
        else:
            self._start_record()

    def _start_record(self):
        self._recording = True
        self._pressed.clear()
        self._has_trigger = False
        self._combo.setText("")
        self._combo.setReadOnly(True)
        self._record_btn.setText("Stop")
        self._status.setText("Listening... press combo and release to lock.")
        QtCore.QTimer.singleShot(200, self._attach_listeners)

    def _attach_listeners(self):
        if not self._recording:
            return

        if _PYNPUT_OK:
            self._kb_listener = _pk.Listener(on_press=self._on_pynput_key_press, on_release=self._on_pynput_key_release)
            self._mouse_listener = _pm.Listener(on_click=self._on_mouse_click)
            self._kb_listener.start()
            self._mouse_listener.start()
        else:
            self._keyboard_hook = keyboard.hook(self._on_keyboard_event)

    def _stop_record(self):
        if not self._recording:
            return
        self._recording = False
        self._combo.setReadOnly(False)
        self._record_btn.setText("Record")

        if self._kb_listener:
            self._kb_listener.stop()
            self._kb_listener = None
        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None
        if self._keyboard_hook:
            keyboard.unhook(self._keyboard_hook)
            self._keyboard_hook = None

        combo = self._combo.text().strip().lower()
        if combo:
            self._apply_combo_to_controls(combo)
            self._status.setText(f"Captured: {combo}")
        else:
            self._status.setText("Nothing captured.")

    def _on_keyboard_event(self, event):
        key = self._canonical_name(event.name)
        if not key:
            return
        if event.event_type == "down":
            self._pressed.add(key)
            if key not in _MOD_ORDER:
                self._has_trigger = True
            self._refresh_display_async()
        elif event.event_type == "up":
            self._pressed.discard(key)
            if not self._pressed and self._has_trigger:
                self._lock_combo_async()

    def _on_pynput_key_press(self, key):
        name = self._resolve_pynput_key(key)
        if name:
            self._pressed.add(name)
            if name not in _MOD_ORDER:
                self._has_trigger = True
            self._refresh_display_async()

    def _on_pynput_key_release(self, key):
        name = self._resolve_pynput_key(key)
        if name:
            self._pressed.discard(name)
        if not self._pressed and self._has_trigger:
            self._lock_combo_async()

    def _on_mouse_click(self, _x, _y, button, pressed):
        if _pm is None:
            return
        btn_map = {
            _pm.Button.left: "mouse1",
            _pm.Button.right: "mouse2",
            _pm.Button.middle: "mouse3",
            _pm.Button.x1: "mouse4",
            _pm.Button.x2: "mouse5",
        }
        name = btn_map.get(button)
        if not name:
            return
        if pressed:
            self._pressed.add(name)
            self._has_trigger = True
            self._refresh_display_async()
        else:
            self._pressed.discard(name)
            if not self._pressed and self._has_trigger:
                self._lock_combo_async()

    def _refresh_display_async(self):
        QtCore.QTimer.singleShot(0, self._refresh_display)

    def _lock_combo_async(self):
        QtCore.QTimer.singleShot(0, self._stop_record)

    def _refresh_display(self):
        mods = [name for name in _MOD_ORDER if name in self._pressed]
        others = sorted(name for name in self._pressed if name not in _MOD_ORDER)
        combo = "+".join(mods + (others[:1] if others else []))
        self._combo.setText(combo)

    def _canonical_name(self, name: str | None) -> str | None:
        if not name:
            return None
        raw = name.strip().lower()
        aliases = {
            "left ctrl": "ctrl",
            "right ctrl": "ctrl",
            "left shift": "shift",
            "right shift": "shift",
            "left alt": "alt",
            "right alt": "alt",
            "alt gr": "alt",
            "left windows": "windows",
            "right windows": "windows",
            "escape": "esc",
            "return": "enter",
        }
        if raw in aliases:
            return aliases[raw]
        if raw in _MOD_ORDER or raw in _MAIN_KEYS:
            return raw
        if len(raw) == 1 and (raw.isalpha() or raw.isdigit()):
            return raw
        if raw.startswith("numpad "):
            return "num " + raw.replace("numpad ", "")
        return None

    def _resolve_pynput_key(self, key) -> str | None:
        if _pk is None:
            return None
        mod_map = {
            _pk.Key.ctrl_l: "ctrl",
            _pk.Key.ctrl_r: "ctrl",
            _pk.Key.shift: "shift",
            _pk.Key.shift_r: "shift",
            _pk.Key.alt_l: "alt",
            _pk.Key.alt_r: "alt",
            _pk.Key.alt_gr: "alt",
            _pk.Key.cmd: "windows",
            _pk.Key.cmd_r: "windows",
        }
        if key in mod_map:
            return mod_map[key]

        special = {
            _pk.Key.space: "space",
            _pk.Key.enter: "enter",
            _pk.Key.tab: "tab",
            _pk.Key.esc: "esc",
            _pk.Key.backspace: "backspace",
            _pk.Key.delete: "delete",
            _pk.Key.insert: "insert",
            _pk.Key.home: "home",
            _pk.Key.end: "end",
            _pk.Key.page_up: "page up",
            _pk.Key.page_down: "page down",
            _pk.Key.up: "up",
            _pk.Key.down: "down",
            _pk.Key.left: "left",
            _pk.Key.right: "right",
        }
        if key in special:
            return special[key]

        vk = getattr(key, "vk", None)
        if isinstance(vk, int) and 96 <= vk <= 105:
            return f"num {vk - 96}"

        char = getattr(key, "char", None)
        if char:
            return self._canonical_name(char)
        return None
