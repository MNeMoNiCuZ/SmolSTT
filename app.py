"""
SmolSTT - Global push-to-talk Speech-to-Text via Whisper FastAPI
Run: python app.py
"""

import os
import sys
import threading
import time
import traceback
import faulthandler

import keyboard as kb
import pyautogui
import pyperclip

# Make src/ importable without a package prefix
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from api_client import WhisperClient
from autostart import set_autostart
from hotkey_manager import HotkeyManager
from logger import log
from overlay import RecordingOverlay
from recorder import AudioRecorder
from settings_manager import SettingsManager
from settings_window import SettingsWindow
from theme import normalize_theme
from toast import ProcessingSpinner, ToastNotification
from tray import TrayIcon
from ui_host import UIHost

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


class SmolSTTApp:
    def __init__(self):
        log.info("=== SmolSTT starting ===")
        try:
            # Windowed/frozen builds can start without stderr.
            if sys.stderr is not None:
                faulthandler.enable(all_threads=True)
        except Exception:
            pass
        self._install_crash_logging()
        self._settings = SettingsManager()

        self._ui = UIHost()
        self._recorder = AudioRecorder(self._settings)
        self._client = WhisperClient(self._settings)
        self._hotkey_mgr = HotkeyManager()
        self._overlay = RecordingOverlay(self._ui)
        self._tray = TrayIcon(self)
        self._toast = ToastNotification(self._ui)
        self._spinner = ProcessingSpinner(self._ui)
        self._settings_win = SettingsWindow(self._ui, self._settings, self._on_settings_saved)
        self._apply_theme()

        self._recording = False

    def start(self):
        self._tray.start()
        self._register_hotkey()
        log.info(
            "SmolSTT ready - hotkey: %s mode: %s",
            self._settings.get("hotkey"),
            self._settings.get("hotkey_mode"),
        )
        self._ui.run()
        log.info("=== SmolSTT exited ===")

    def toggle(self):
        if self._recording:
            self._stop()
        else:
            self._start()

    def _register_hotkey(self):
        hotkey = self._settings.get("hotkey", "ctrl+shift+space")
        mode = self._settings.get("hotkey_mode", "toggle")
        log.info("Registering hotkey: %s mode: %s", hotkey, mode)

        if mode == "hold":
            self._hotkey_mgr.register(
                hotkey,
                on_activate=self._start,
                on_deactivate=self._stop,
                mode="hold",
            )
        else:
            self._hotkey_mgr.register(
                hotkey,
                on_activate=self._toggle_from_hotkey,
                mode="toggle",
            )

    def _toggle_from_hotkey(self):
        log.debug("Hotkey triggered (recording=%s)", self._recording)
        self.toggle()

    def _start(self):
        if self._recording:
            return
        self._recording = True
        if self._settings.get("show_recording_indicator", True):
            self._overlay.show()
        self._tray.set_recording(True)
        try:
            self._recorder.start()
        except Exception as exc:
            log.error("Could not start recorder: %s", exc)
            self._recording = False
            self._overlay.hide()
            self._tray.set_recording(False)
            self._toast.show(
                "SmolSTT - Error",
                f"Microphone error: {exc}",
                theme=self.current_theme(),
                font_size=self._toast_font_size(),
                width=self._toast_width(),
                max_height=self._toast_height(),
                fade_in_duration_ms=self._toast_fade_in_duration_ms(),
                visible_duration_ms=self._toast_duration_ms(),
                fade_duration_ms=self._toast_fade_duration_ms(),
            )

    def _stop(self):
        if not self._recording:
            return
        self._recording = False
        self._overlay.hide()
        self._tray.set_recording(False)
        self._tray.set_processing()
        threading.Thread(target=self._process, daemon=True).start()

    def _process(self):
        try:
            wav = self._recorder.stop()
            if not wav:
                info = self._recorder.get_last_capture_info()
                rejected_by_threshold = bool(info.get("rejected_by_threshold"))
                rms = info.get("rms")
                threshold = info.get("threshold")
                sensitivity_enabled = bool(info.get("sensitivity_enabled"))
                if rejected_by_threshold or (
                    sensitivity_enabled
                    and rms is not None
                    and threshold is not None
                    and float(rms) < float(threshold)
                ):
                    msg = f"Sensitivity too low. RMS {rms:.2f}, threshold {threshold}."
                    log.info("Sensitivity rejection toast: %s", msg)
                    if self._settings.get("show_sensitivity_reject_notification", True):
                        self._toast.show(
                            "Sensitivity",
                            msg,
                            theme=self.current_theme(),
                            font_size=self._toast_font_size(),
                            width=self._toast_width(),
                            max_height=self._toast_height(),
                            fade_in_duration_ms=self._toast_fade_in_duration_ms(),
                            visible_duration_ms=self._toast_duration_ms(),
                            fade_duration_ms=self._toast_fade_duration_ms(),
                        )
                    self._tray.set_status("Rejected by sensitivity threshold")
                    return
                self._tray.set_status("No audio captured")
                return

            show_spinner = bool(self._settings.get("show_transcribing_notification", True))
            if show_spinner:
                self._spinner.show(theme=self.current_theme())
            try:
                text = self._client.transcribe(wav)
            except Exception as exc:
                log.error("Transcription failed: %s", exc)
                self._tray.set_status("Error - see console")
                self._toast.show(
                    "SmolSTT - Error",
                    str(exc)[:200],
                    theme=self.current_theme(),
                    font_size=self._toast_font_size(),
                    width=self._toast_width(),
                    max_height=self._toast_height(),
                    fade_in_duration_ms=self._toast_fade_in_duration_ms(),
                    visible_duration_ms=self._toast_duration_ms(),
                    fade_duration_ms=self._toast_fade_duration_ms(),
                )
                return

            cleaned = self._sanitize_text(text)
            if not cleaned:
                self._tray.set_status("(empty result)")
                return

            self._deliver(cleaned)
            self._tray.set_status("Ready")
        finally:
            if self._settings.get("show_transcribing_notification", True):
                self._spinner.hide()

    def _sanitize_text(self, text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        token = cleaned.lower().strip(" \t\r\n.,!?;:\"'`()[]{}")
        if token == "you":
            return ""
        return cleaned

    def _deliver(self, text: str):
        do_clipboard = self._settings.get("output_clipboard", True)
        do_insert = self._settings.get("output_insert", False)
        method = self._settings.get("output_insert_method", "paste")
        notify = self._settings.get("show_notification", True)
        typing_speed = self._get_typing_speed()

        if do_clipboard or (do_insert and method == "paste"):
            pyperclip.copy(text)

        if do_insert:
            time.sleep(0.15)
            if method == "paste":
                pyautogui.hotkey("ctrl", "v")
            else:
                kb.write(text, delay=1.0 / typing_speed)

        if notify:
            self._toast.show(
                "",
                text,
                theme=self.current_theme(),
                font_size=self._toast_font_size(),
                width=self._toast_width(),
                max_height=self._toast_height(),
                fade_in_duration_ms=self._toast_fade_in_duration_ms(),
                visible_duration_ms=self._toast_duration_ms(),
                fade_duration_ms=self._toast_fade_duration_ms(),
            )

    def _get_typing_speed(self) -> int:
        try:
            speed = int(self._settings.get("typing_speed", 100))
        except (TypeError, ValueError):
            speed = 100
        return max(50, min(speed, 1000))

    def _toast_font_size(self) -> int:
        try:
            size = int(self._settings.get("notification_font_size", 11))
        except (TypeError, ValueError):
            size = 11
        return max(9, min(size, 24))

    def _toast_height(self) -> int:
        try:
            height = int(self._settings.get("notification_height", 0))
        except (TypeError, ValueError):
            height = 0
        return max(0, min(height, 2400))

    def _toast_width(self) -> int:
        try:
            width = int(self._settings.get("notification_width", 390))
        except (TypeError, ValueError):
            width = 390
        return max(50, min(width, 2400))

    def _toast_duration_ms(self) -> int:
        try:
            seconds = float(self._settings.get("notification_duration_s", 4.0))
            ms = int(seconds * 1000.0)
        except (TypeError, ValueError):
            try:
                ms = int(self._settings.get("notification_duration_ms", 4000))
            except (TypeError, ValueError):
                ms = 4000
        return max(300, min(ms, 60000))

    def _toast_fade_in_duration_ms(self) -> int:
        try:
            seconds = float(self._settings.get("notification_fade_in_duration_s", 0.10))
            ms = int(seconds * 1000.0)
        except (TypeError, ValueError):
            ms = 100
        return max(0, min(ms, 10000))

    def _toast_fade_duration_ms(self) -> int:
        try:
            seconds = float(self._settings.get("notification_fade_duration_s", 0.22))
            ms = int(seconds * 1000.0)
        except (TypeError, ValueError):
            try:
                ms = int(self._settings.get("notification_fade_duration_ms", 220))
            except (TypeError, ValueError):
                ms = 220
        return max(0, min(ms, 10000))

    def open_settings(self):
        self._settings_win.open()

    def current_theme(self) -> str:
        return normalize_theme(self._settings.get("app_theme", "dark"))

    def _apply_theme(self):
        self._ui.set_theme(self.current_theme())
        self._tray.refresh_theme()

    def _install_crash_logging(self):
        def _handle_exception(exc_type, exc, tb):
            try:
                msg = "".join(traceback.format_exception(exc_type, exc, tb))
                log.error("Unhandled exception:\n%s", msg)
            except Exception:
                pass
            try:
                sys.__excepthook__(exc_type, exc, tb)
            except Exception:
                pass

        def _handle_thread_exception(args):
            _handle_exception(args.exc_type, args.exc_value, args.exc_traceback)

        sys.excepthook = _handle_exception
        if hasattr(threading, "excepthook"):
            threading.excepthook = _handle_thread_exception

    def _on_settings_saved(self, new_settings: dict):
        hotkey_changed = (
            new_settings.get("hotkey") != self._settings.get("hotkey")
            or new_settings.get("hotkey_mode") != self._settings.get("hotkey_mode")
        )
        autostart_changed = new_settings.get("autostart") != self._settings.get("autostart")

        self._settings.update(new_settings)
        self._apply_theme()

        if hotkey_changed:
            self._register_hotkey()

        if autostart_changed:
            set_autostart(bool(new_settings.get("autostart")))

    def quit(self):
        self._hotkey_mgr.stop()
        self._tray.stop()
        self._ui.quit()


if __name__ == "__main__":
    SmolSTTApp().start()
