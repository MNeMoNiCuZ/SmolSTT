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
import tempfile
import io
import wave
import subprocess
from collections import deque

import keyboard as kb
import numpy as np
import pyautogui
import pyperclip
import sounddevice as sd

# Make src/ importable without a package prefix
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from api_client import WhisperClient
from autostart import set_autostart, is_autostart_enabled
from local_inference import LocalInferenceEngine, is_parakeet_model, is_whisper_model, _no_window_kwargs
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
        self._local_engine = LocalInferenceEngine(self._settings)
        self._hotkey_mgr = HotkeyManager()
        self._system_hotkey_mgr = HotkeyManager()
        self._overlay = RecordingOverlay(self._ui, anchor_getter=self._notification_anchor)
        self._overlay_refs = 0
        self._tray = TrayIcon(self)
        self._toast = ToastNotification(self._ui)
        self._spinner = ProcessingSpinner(self._ui)
        self._speed_stats_mode = "disabled"
        self._speed_samples: deque[tuple[float, int, float]] = deque()
        self._test_capture_stream = None
        self._test_capture_frames: list[np.ndarray] = []
        self._test_capture_lock = threading.Lock()
        self._test_capture_rate = 16000
        self._test_capture_channels = 1
        self._test_capture_mode = None
        self._test_capture_backend = None
        self._pa_audio = None
        self._pa_stream = None
        self._pa_thread = None
        self._pa_stop_event = threading.Event()
        self._set_speed_stats_mode(self._settings.get("speed_stats_mode", "disabled"))
        self._settings_win = SettingsWindow(
            self._ui,
            self._settings,
            self._on_settings_saved,
            speed_mode_getter=self._get_speed_stats_mode,
            speed_mode_setter=self._set_speed_stats_mode,
            test_start_record_callback=self._start_test_recording,
            test_stop_record_callback=self._stop_test_recording,
            test_start_output_callback=self._start_output_capture,
            test_stop_output_callback=self._stop_output_capture,
            test_use_recorded_callback=self._use_recorded_clip,
            test_has_recorded_callback=self._has_recorded_clip,
            test_delete_recorded_callback=self._delete_recorded_clip,
            test_list_output_sources_callback=self._list_output_capture_sources,
            test_set_input_file_callback=self._set_test_clip_from_file,
            notification_preview_callback=self._preview_notification_from_settings,
        )
        self._apply_theme()

        self._recording = False
        self._system_audio_recording = False

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
        system_hotkey = str(self._settings.get("system_audio_hotkey", "") or "").strip()
        mode = self._settings.get("hotkey_mode", "toggle")
        suppress = bool(self._settings.get("suppress_hotkey", False))
        log.info("Registering microphone hotkey: %s mode: %s suppress=%s", hotkey, mode, suppress)

        if mode == "hold":
            self._hotkey_mgr.register(
                hotkey,
                on_activate=self._start,
                on_deactivate=self._stop,
                mode="hold",
                suppress=suppress,
            )
        else:
            self._hotkey_mgr.register(
                hotkey,
                on_activate=self._toggle_from_hotkey,
                mode="toggle",
                suppress=suppress,
            )
        self._system_hotkey_mgr.unregister()
        if system_hotkey:
            log.info("Registering system audio hotkey: %s mode: %s suppress=%s", system_hotkey, mode, suppress)
            if mode == "hold":
                self._system_hotkey_mgr.register(
                    system_hotkey,
                    on_activate=self._start_system_audio_capture,
                    on_deactivate=self._stop_system_audio_capture,
                    mode="hold",
                    suppress=suppress,
                )
            else:
                self._system_hotkey_mgr.register(
                    system_hotkey,
                    on_activate=self._toggle_system_audio_hotkey,
                    mode="toggle",
                    suppress=suppress,
                )

    def _toggle_from_hotkey(self):
        log.debug("Hotkey triggered (recording=%s)", self._recording)
        try:
            self.toggle()
        finally:
            self._release_modifier_keys()

    def _toggle_system_audio_hotkey(self):
        log.debug("System audio hotkey triggered (recording=%s)", self._system_audio_recording)
        try:
            if self._system_audio_recording:
                self._stop_system_audio_capture()
            else:
                self._start_system_audio_capture()
        finally:
            self._release_modifier_keys()

    def _release_modifier_keys(self):
        # Safety net for rare stuck-modifier states after global hotkeys.
        keys = (
            "left ctrl", "right ctrl", "ctrl",
            "left alt", "right alt", "alt", "alt gr",
            "left shift", "right shift", "shift",
            "left windows", "right windows", "windows",
        )
        for key in keys:
            try:
                kb.release(key)
            except Exception:
                pass

    def _start(self):
        if self._recording or self._system_audio_recording:
            return
        self._recording = True
        self._overlay_acquire()
        self._tray.set_recording(True)
        try:
            self._recorder.start(level_callback=self._on_live_rms)
        except Exception as exc:
            log.error("Could not start recorder: %s", exc)
            self._recording = False
            self._overlay_release()
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
                anchor=self._notification_anchor(),
            )

    def _start_system_audio_capture(self):
        if self._system_audio_recording or self._recording:
            return
        opts = {
            "output_capture_source": str(self._settings.get("output_capture_source", "auto") or "auto"),
            "portable_models": False,
            "suppress_recorded_toast": True,
        }
        ok, msg = self._start_test_capture(opts, source="output")
        if not ok:
            log.error("System audio capture start failed: %s", msg)
            self._tray.set_status("Error - see console")
            return
        self._system_audio_recording = True
        self._tray.set_recording(True)

    def _stop_system_audio_capture(self):
        if not self._system_audio_recording:
            return
        self._system_audio_recording = False
        self._tray.set_recording(False)
        self._tray.set_processing()
        opts = {"portable_models": False, "suppress_recorded_toast": True}
        ok, msg = self._stop_test_capture(opts)
        if not ok:
            log.error("System audio capture stop failed: %s", msg)
            self._tray.set_status("Error - see console")
            return
        threading.Thread(target=self._process_system_audio_clip, daemon=True).start()

    def _process_system_audio_clip(self):
        opts = {"portable_models": False}
        path = self._test_clip_path(opts)
        if not os.path.exists(path):
            self._tray.set_status("No audio captured")
            return
        try:
            wav = self._load_audio_for_transcribe(path)
        except OSError as exc:
            log.error("System audio: failed to read clip path=%s err=%s", path, exc)
            self._tray.set_status("Error - see console")
            return
        ok, _ = self._transcribe_blob(wav, self._effective_options(opts), force_no_insert=False, context="System audio")
        self._tray.set_status("Ready" if ok else "Error - see console")

    def _stop(self):
        if not self._recording:
            return
        self._recording = False
        self._system_audio_recording = False
        self._overlay_release()
        self._tray.set_recording(False)
        self._tray.set_processing()
        threading.Thread(target=self._process, daemon=True).start()

    def _overlay_acquire(self):
        if not self._settings.get("show_recording_indicator", True):
            return
        self._overlay_refs += 1
        if self._overlay_refs == 1:
            self._overlay.show()

    def _overlay_release(self):
        if self._overlay_refs <= 0:
            self._overlay_refs = 0
            return
        self._overlay_refs -= 1
        if self._overlay_refs == 0:
            self._overlay.hide()

    def _on_live_rms(self, rms: float):
        if not self._settings.get("show_recording_indicator", True):
            return
        self._overlay.set_rms(rms)

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
                    ratio = f"{float(rms):.2f}/{float(threshold):.0f}"
                    msg = f"Sensitivity Threshold: <b>{ratio}</b>"
                    log.info("Sensitivity rejection toast: %s", msg)
                    if self._settings.get("show_sensitivity_reject_notification", True):
                        self._toast.show(
                            "Sensitivity Threshold",
                            msg,
                            theme=self.current_theme(),
                            font_size=self._toast_font_size(),
                            width=self._toast_width(),
                            max_height=self._toast_height(),
                            fade_in_duration_ms=self._toast_fade_in_duration_ms(),
                            visible_duration_ms=self._toast_duration_ms(),
                            fade_duration_ms=self._toast_fade_duration_ms(),
                            anchor=self._notification_anchor(),
                        )
                    self._tray.set_status("Rejected by sensitivity threshold")
                    return
                self._tray.set_status("No audio captured")
                return

            show_spinner = bool(self._settings.get("show_transcribing_notification", True))
            model = self._settings.get("model", "")
            backend = self._settings.get("whisper_backend", "local")
            use_local = is_parakeet_model(model) or (is_whisper_model(model) and backend == "local")
            if show_spinner:
                spinner_label = "Transcribing"
                if use_local and not self._local_engine.is_ready_cached(model):
                    spinner_label = "Downloading"
                self._spinner.show(
                    theme=self.current_theme(),
                    label=spinner_label,
                    font_size=self._toast_font_size(),
                    anchor=self._notification_anchor(),
                )
            request_started = time.perf_counter()
            try:
                if use_local:
                    text = self._local_engine.transcribe(wav)
                else:
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
                    anchor=self._notification_anchor(),
                )
                return

            cleaned = self._sanitize_text(text)
            if not cleaned:
                self._tray.set_status("(empty result)")
                self._record_speed_stats(0, time.perf_counter() - request_started)
                if self._settings.get("show_empty_notification", True):
                    self._toast.show(
                        "",
                        "Empty Input",
                        theme=self.current_theme(),
                        font_size=self._toast_font_size(),
                        width=self._toast_width(),
                        max_height=self._toast_height(),
                        fade_in_duration_ms=self._toast_fade_in_duration_ms(),
                        visible_duration_ms=self._toast_duration_ms(),
                        fade_duration_ms=self._toast_fade_duration_ms(),
                        anchor=self._notification_anchor(),
                    )
                return

            self._record_speed_stats(len(cleaned), time.perf_counter() - request_started)
            self._deliver(cleaned, speed_badge=self._speed_badge_text())
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

    def _deliver(self, text: str, speed_badge: str = "", force_no_insert: bool = False):
        do_clipboard = self._settings.get("output_clipboard", True) and not bool(force_no_insert)
        do_insert = self._settings.get("output_insert", False) and not bool(force_no_insert)
        method = self._settings.get("output_insert_method", "paste")
        notify = self._settings.get("show_notification", True)
        typing_speed = self._get_typing_speed()
        try:
            self._settings_win.set_test_caption_text(text)
        except Exception:
            pass

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
                speed_badge=speed_badge,
                anchor=self._notification_anchor(),
            )

    def _get_typing_speed(self) -> int:
        try:
            speed = int(self._settings.get("typing_speed", 100))
        except (TypeError, ValueError):
            speed = 100
        return max(50, min(speed, 5000))

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

    def _notification_anchor(self) -> str:
        anchor = str(self._settings.get("notification_anchor", "bottom_right") or "bottom_right").strip().lower()
        allowed = {
            "bottom_right", "bottom_left", "top_right", "top_left",
            "top_center", "bottom_center", "left_center", "right_center",
        }
        return anchor if anchor in allowed else "bottom_right"

    def _preview_notification_from_settings(
        self,
        message: str,
        anchor: str,
        duration_ms: int,
        font_size: int,
        width: int,
        max_height: int,
        fade_in_ms: int,
        fade_out_ms: int,
        speed_badge: str = "",
        show_dot: bool = True,
    ) -> None:
        self._toast.show(
            "",
            str(message or "Test Notification"),
            theme=self.current_theme(),
            font_size=max(9, min(int(font_size), 24)),
            width=max(50, min(int(width), 2400)),
            max_height=max(0, min(int(max_height), 2400)),
            fade_in_duration_ms=max(0, int(fade_in_ms)),
            visible_duration_ms=max(300, int(duration_ms)),
            fade_duration_ms=max(0, int(fade_out_ms)),
            speed_badge=str(speed_badge or ""),
            anchor=anchor,
        )
        if not show_dot:
            return
        self._overlay.preview_pulse(duration_ms=max(300, int(duration_ms)), anchor=anchor)

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

    def _effective_options(self, overrides: dict | None = None) -> dict:
        merged = {
            "model": self._settings.get("model", ""),
            "whisper_backend": self._settings.get("whisper_backend", "local"),
            "model_device": self._settings.get("model_device", "gpu"),
            "portable_models": bool(self._settings.get("portable_models", False)),
            "api_url": self._settings.get("api_url", "http://localhost:9876"),
            "api_endpoint": self._settings.get("api_endpoint", "/v1/audio/transcriptions"),
            "language": self._settings.get("language", "en"),
            "microphone_index": self._settings.get("microphone_index", None),
            "sample_rate": int(self._settings.get("sample_rate", 16000)),
            "input_file_path": str(self._settings.get("test_input_file", "") or ""),
        }
        if overrides:
            merged.update(overrides)
        return merged

    def _test_clip_path(self, overrides: dict | None = None) -> str:
        opts = self._effective_options(overrides)
        if bool(opts.get("portable_models", False)):
            if getattr(sys, "frozen", False):
                base = os.path.dirname(sys.executable)
            else:
                base = os.path.dirname(os.path.abspath(__file__))
            return os.path.join(base, "test.wav")
        base = os.path.join(tempfile.gettempdir(), "SmolSTT")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "test.wav")

    def _resolve_test_audio_path(self, overrides: dict | None = None) -> str | None:
        opts = self._effective_options(overrides)
        input_file = str(opts.get("input_file_path", "") or "").strip()
        if input_file and os.path.isfile(input_file):
            return input_file
        wav_path = self._test_clip_path(opts)
        if os.path.exists(wav_path):
            return wav_path
        mp3_path = os.path.splitext(wav_path)[0] + ".mp3"
        if os.path.exists(mp3_path):
            return mp3_path
        return None

    def _has_recorded_clip(self, overrides: dict | None = None) -> bool:
        return self._resolve_test_audio_path(overrides) is not None

    def _delete_recorded_clip(self, overrides: dict | None = None) -> tuple[bool, str]:
        path = self._test_clip_path(overrides)
        if not os.path.exists(path):
            return False, "No recorded clip found."
        try:
            os.remove(path)
            return True, "Deleted."
        except OSError as exc:
            return False, f"Could not delete recorded clip: {exc}"

    def _set_test_clip_from_file(self, src_path: str, overrides: dict | None = None) -> tuple[bool, str]:
        if not src_path or not os.path.isfile(src_path):
            return False, "File does not exist."
        ext = os.path.splitext(src_path)[1].lower()
        if ext not in {".wav", ".mp3"}:
            return False, "Only .wav and .mp3 are supported."
        return True, "Selected."

    def _start_test_recording(self, overrides: dict | None = None) -> tuple[bool, str]:
        return self._start_test_capture(overrides, source="mic")

    def _stop_test_recording(self, overrides: dict | None = None) -> tuple[bool, str]:
        return self._stop_test_capture(overrides)

    def _start_output_capture(self, overrides: dict | None = None) -> tuple[bool, str]:
        selected = None
        if isinstance(overrides, dict):
            selected = overrides.get("output_capture_source")
        log.info("Output capture: start requested (source=%s)", selected if selected is not None else "auto")
        return self._start_test_capture(overrides, source="output")

    def _stop_output_capture(self, overrides: dict | None = None) -> tuple[bool, str]:
        log.info("Output capture: stop requested")
        return self._stop_test_capture(overrides)

    def _start_test_capture(self, overrides: dict | None = None, source: str = "mic") -> tuple[bool, str]:
        if self._test_capture_stream is not None or self._pa_stream is not None:
            log.warning("Test capture: already running (mode=%s)", self._test_capture_mode)
            return False, "Capture already running."
        opts = self._effective_options(overrides)
        preferred_rate = int(opts.get("sample_rate", 16000))
        log.info("Test capture: starting (source=%s preferred_rate=%s)", source, preferred_rate)

        def _callback(indata, frames, time_info, status):
            if status:
                return
            with self._test_capture_lock:
                self._test_capture_frames.append(indata.copy())
            if self._settings.get("show_recording_indicator", True):
                try:
                    rms = float(np.sqrt(np.mean(np.square(indata.astype(np.float32)))))
                    self._overlay.set_rms(rms)
                except Exception:
                    pass

        device_index = None
        channels = 1
        extra_settings = None
        candidates: list[tuple[int | None, int, float, object | None, str]] = []
        if source == "mic":
            device_index = opts.get("microphone_index")
            if device_index == -1:
                device_index = None
            try:
                info = sd.query_devices(device_index) if device_index is not None else sd.query_devices(sd.default.device[0])
                default_rate = float(info.get("default_samplerate", preferred_rate) or preferred_rate)
            except Exception:
                default_rate = float(preferred_rate)
            rate_opts = []
            for r in (preferred_rate, int(default_rate), 48000, 44100):
                if r and r not in rate_opts:
                    rate_opts.append(float(r))
            for r in rate_opts:
                candidates.append((device_index, 1, r, None, f"microphone @ {int(r)}Hz"))
        else:
            try:
                selected_source = str(opts.get("output_capture_source", "auto") or "auto").strip()
                log.info("Output capture: selected source=%s", selected_source)
                # Output capture is WASAPI loopback only (PyAudioWPatch).
                if not (selected_source == "auto" or selected_source.startswith("pa:")):
                    selected_source = "auto"
                ok, msg = self._start_pyaudio_loopback_capture(selected_source, preferred_rate)
                if ok:
                    self._overlay_acquire()
                    return True, "OK"
                log.error("Output capture: WASAPI loopback failed: %s", msg)
                return False, msg
            except Exception as exc:
                log.exception("Output capture: preparation failed")
                return False, f"Could not prepare output capture: {exc}"

        last_error = ""
        log.info("Test capture: trying %d stream candidates", len(candidates))
        for dev, ch, rate, extra, label in candidates:
            try:
                log.debug(
                    "Test capture: trying device=%s channels=%s rate=%s label=%s",
                    dev, ch, int(rate), label,
                )
                sd.check_input_settings(device=dev, channels=ch, samplerate=rate, dtype="int16", extra_settings=extra)
                self._test_capture_frames = []
                self._test_capture_rate = int(rate)
                self._test_capture_channels = ch
                self._test_capture_mode = source
                self._test_capture_backend = "sounddevice"
                self._test_capture_stream = sd.InputStream(
                    samplerate=rate,
                    channels=ch,
                    dtype="int16",
                    device=dev,
                    callback=_callback,
                    extra_settings=extra,
                )
                self._test_capture_stream.start()
                self._overlay_acquire()
                log.info("Test capture: started successfully (%s)", label)
                return True, "OK"
            except Exception as exc:
                self._test_capture_stream = None
                self._test_capture_frames = []
                self._test_capture_mode = None
                self._test_capture_backend = None
                last_error = f"{label}: {exc}"
                log.debug("Test capture: candidate failed: %s", last_error)
                continue
        log.error("Test capture: all candidates failed: %s", last_error)
        return False, f"Capture start failed: {last_error}"

    def _start_pyaudio_loopback_capture(self, selected_source: str, preferred_rate: int) -> tuple[bool, str]:
        try:
            import pyaudiowpatch as pyaudio
        except Exception:
            return False, "PyAudioWPatch not installed."
        try:
            pa = pyaudio.PyAudio()
        except Exception as exc:
            return False, f"PyAudio init failed: {exc}"

        device_info = None
        if selected_source.startswith("pa:"):
            try:
                idx = int(selected_source.split(":", 1)[1])
                info = pa.get_device_info_by_index(idx)
                if int(info.get("maxInputChannels", 0) or 0) > 0:
                    device_info = info
            except Exception:
                device_info = None

        if device_info is None and hasattr(pa, "get_default_wasapi_loopback"):
            try:
                device_info = pa.get_default_wasapi_loopback()
            except Exception:
                device_info = None

        if device_info is None and hasattr(pa, "get_loopback_device_info_generator"):
            try:
                for info in pa.get_loopback_device_info_generator():
                    if int(info.get("maxInputChannels", 0) or 0) > 0:
                        device_info = info
                        break
            except Exception:
                device_info = None

        if device_info is None:
            try:
                pa.terminate()
            except Exception:
                pass
            return False, "No WASAPI loopback device available."

        max_in = int(device_info.get("maxInputChannels", 2) or 2)
        channel_candidates = [2, 1] if max_in >= 2 else [1]
        rate_candidates: list[int] = []
        for r in (int(device_info.get("defaultSampleRate", preferred_rate) or preferred_rate), 48000, 44100, preferred_rate):
            if r and int(r) not in rate_candidates:
                rate_candidates.append(int(r))

        stream = None
        last_error = ""
        for rate in rate_candidates:
            for ch in channel_candidates:
                try:
                    stream = pa.open(
                        format=pyaudio.paInt16,
                        channels=ch,
                        rate=rate,
                        input=True,
                        input_device_index=int(device_info["index"]),
                        frames_per_buffer=2048,
                    )
                    self._test_capture_frames = []
                    self._test_capture_rate = int(rate)
                    self._test_capture_channels = int(ch)
                    self._test_capture_mode = "output"
                    self._test_capture_backend = "pyaudiowpatch"
                    self._pa_audio = pa
                    self._pa_stream = stream
                    self._pa_stop_event.clear()

                    def _reader():
                        while not self._pa_stop_event.is_set():
                            try:
                                data = self._pa_stream.read(2048, exception_on_overflow=False)
                            except Exception:
                                break
                            arr = np.frombuffer(data, dtype=np.int16)
                            if arr.size == 0:
                                continue
                            if ch > 1:
                                arr = arr.reshape(-1, ch)
                            else:
                                arr = arr.reshape(-1, 1)
                            with self._test_capture_lock:
                                self._test_capture_frames.append(arr.copy())
                            if self._settings.get("show_recording_indicator", True):
                                try:
                                    rms = float(np.sqrt(np.mean(np.square(arr.astype(np.float32)))))
                                    self._overlay.set_rms(rms)
                                except Exception:
                                    pass

                    self._pa_thread = threading.Thread(target=_reader, daemon=True)
                    self._pa_thread.start()
                    log.info(
                        "Test capture: started successfully (WASAPI loopback idx=%s ch=%d rate=%d)",
                        int(device_info["index"]),
                        ch,
                        rate,
                    )
                    return True, "OK"
                except Exception as exc:
                    last_error = str(exc)
                    stream = None
                    continue

        try:
            pa.terminate()
        except Exception:
            pass
        return False, f"WASAPI loopback start failed: {last_error}"

    def _list_output_capture_sources(self) -> list[tuple[str, str]]:
        sources: list[tuple[str, str]] = []
        try:
            import pyaudiowpatch as pyaudio
            pa = pyaudio.PyAudio()
            if hasattr(pa, "get_loopback_device_info_generator"):
                for info in pa.get_loopback_device_info_generator():
                    if int(info.get("maxInputChannels", 0) or 0) <= 0:
                        continue
                    idx = int(info.get("index"))
                    name = str(info.get("name", "")).strip()
                    sources.append((f"pa:{idx}", f"WASAPI Loopback: {name} (Recommended)"))
            try:
                pa.terminate()
            except Exception:
                pass
        except Exception:
            pass
        log.debug("Output capture: list sources -> %s", [sid for sid, _ in sources])
        return sources

    def _stop_test_capture(self, overrides: dict | None = None) -> tuple[bool, str]:
        if self._test_capture_stream is None and self._pa_stream is None:
            log.warning("Test capture: stop requested but no stream is running")
            return False, "Capture not running."
        self._overlay_release()
        if self._test_capture_backend == "pyaudiowpatch":
            self._pa_stop_event.set()
            try:
                if self._pa_thread is not None:
                    self._pa_thread.join(timeout=1.0)
            except Exception:
                pass
            try:
                if self._pa_stream is not None:
                    self._pa_stream.stop_stream()
                    self._pa_stream.close()
            except Exception:
                pass
            try:
                if self._pa_audio is not None:
                    self._pa_audio.terminate()
            except Exception:
                pass
            self._pa_stream = None
            self._pa_audio = None
            self._pa_thread = None
        else:
            stream = self._test_capture_stream
            self._test_capture_stream = None
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        with self._test_capture_lock:
            frames = list(self._test_capture_frames)
            self._test_capture_frames = []
        mode = self._test_capture_mode
        self._test_capture_mode = None
        self._test_capture_backend = None
        if not frames:
            log.warning("Test capture: stopped with no frames captured")
            return False, "No audio captured."
        try:
            audio = np.concatenate(frames, axis=0)
        except Exception:
            return False, "No audio captured."
        if int(audio.size) <= 0:
            log.warning("Test capture: captured audio buffer is empty")
            return False, "No audio captured."
        if audio.ndim > 1 and audio.shape[1] > 1:
            # Fold channels without cancellation: keep per-sample strongest magnitude.
            audio_f = audio.astype(np.float32)
            strongest_idx = np.argmax(np.abs(audio_f), axis=1)
            mono = audio_f[np.arange(audio_f.shape[0]), strongest_idx]
            channel_levels = np.sqrt(np.mean(np.square(audio_f), axis=0))
            log.debug(
                "Test capture: multi-channel input detected; channel RMS=%s using max-abs fold",
                channel_levels.tolist(),
            )
            audio = mono.astype(np.int16).reshape(-1, 1)
        mono = audio.reshape(-1).astype(np.float32)
        rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size > 0 else 0.0
        dbfs_before = (20.0 * np.log10(max(rms, 1.0) / 32768.0)) if mono.size > 0 else -90.0
        active_ratio = float(np.mean(np.abs(mono) > 600.0)) if mono.size > 0 else 0.0

        # Output loopback can be captured very quietly on some drivers.
        # Normalize low-level output recordings to improve downstream STT.
        if mode == "output" and mono.size > 0 and dbfs_before < -32.0:
            target_dbfs = -24.0
            target_rms = 32768.0 * (10.0 ** (target_dbfs / 20.0))
            peak = float(np.max(np.abs(mono))) if mono.size > 0 else 1.0
            rms_gain = target_rms / max(rms, 1.0)
            peak_gain = 30000.0 / max(peak, 1.0)  # keep headroom, avoid hard clipping
            gain = max(1.0, min(rms_gain, peak_gain, 12.0))
            if gain > 1.05:
                boosted = np.clip(mono * gain, -32768.0, 32767.0)
                audio = boosted.astype(np.int16).reshape(-1, 1)
                mono = boosted
                rms = float(np.sqrt(np.mean(np.square(mono))))
                log.info(
                    "Test capture: output gain applied x%.2f (dbfs %.1f -> %.1f)",
                    gain,
                    dbfs_before,
                    20.0 * np.log10(max(rms, 1.0) / 32768.0),
                )

        dbfs_raw = (20.0 * np.log10(max(rms, 1.0) / 32768.0)) if mono.size > 0 else -90.0
        dbfs = 0.0 if rms <= 1.0 else dbfs_raw

        opts = self._effective_options(overrides)
        path = self._test_clip_path(opts)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(int(self._test_capture_rate))
                wf.writeframes(audio.tobytes())
            sample_count = int(audio.shape[0])
            duration_s = (float(sample_count) / float(self._test_capture_rate)) if self._test_capture_rate > 0 else 0.0
            log.info(
                "Test capture: saved clip path=%s samples=%d rate=%d duration=%.2fs avg_dbfs=%.1f active=%.1f%% mode=%s",
                path,
                sample_count,
                int(self._test_capture_rate),
                duration_s,
                dbfs,
                active_ratio * 100.0,
                mode,
            )
            suppress_recorded_toast = bool(opts.get("suppress_recorded_toast", False))
            if mode in {"output", "mic"} and not suppress_recorded_toast:
                self._toast.show(
                    "",
                    f"Audio recorded {duration_s:.2f} s | {dbfs:.1f} dBFS avg",
                    theme=self.current_theme(),
                    font_size=self._toast_font_size(),
                    width=self._toast_width(),
                    max_height=self._toast_height(),
                    fade_in_duration_ms=self._toast_fade_in_duration_ms(),
                    visible_duration_ms=self._toast_duration_ms(),
                    fade_duration_ms=self._toast_fade_duration_ms(),
                    anchor=self._notification_anchor(),
                )
            return True, f"Audio recorded {duration_s:.2f}s."
        except Exception as exc:
            log.exception("Test capture: save failed")
            return False, f"Could not save recording: {exc}"

    def _use_recorded_clip(self, overrides: dict | None = None) -> tuple[bool, str]:
        opts = self._effective_options(overrides)
        path = self._resolve_test_audio_path(opts)
        if not path:
            log.error("Use recorded: clip missing (input/test.wav/test.mp3)")
            return False, "No recorded clip found."
        try:
            wav = self._load_audio_for_transcribe(path)
        except OSError as exc:
            log.error("Use recorded: failed to read clip path=%s err=%s", path, exc)
            return False, f"Could not read recorded clip: {exc}"
        return self._transcribe_blob(wav, opts, force_no_insert=True, context="Use recorded")

    def _transcribe_blob(
        self,
        wav: bytes,
        opts: dict,
        force_no_insert: bool,
        context: str = "Transcription",
    ) -> tuple[bool, str]:

        class _MapSettings:
            def __init__(self, data, backing_settings=None):
                self._data = data
                self._backing_settings = backing_settings

            def get(self, key, default=None):
                return self._data.get(key, default)

            def update(self, new_settings: dict):
                if not isinstance(new_settings, dict):
                    return
                token_payload = new_settings.get("local_ready_models")
                if token_payload is None:
                    return
                self._data["local_ready_models"] = token_payload
                if self._backing_settings is not None and hasattr(self._backing_settings, "update"):
                    try:
                        self._backing_settings.update({"local_ready_models": token_payload})
                    except Exception:
                        pass

        started = time.perf_counter()
        model = str(opts.get("model", ""))
        backend = str(opts.get("whisper_backend", "local"))
        use_local = is_parakeet_model(model) or (is_whisper_model(model) and backend == "local")
        log.info(
            "%s: start model=%s backend=%s local=%s bytes=%d",
            context, model, backend, use_local, len(wav),
        )
        settings_obj = _MapSettings(opts, backing_settings=self._settings)
        show_spinner = bool(self._settings.get("show_transcribing_notification", True))
        local_engine = LocalInferenceEngine(settings_obj) if use_local else None
        if show_spinner:
            # Do not claim "Downloading" in this path; we can't guarantee an actual fetch.
            self._spinner.show(
                theme=self.current_theme(),
                label="Transcribing",
                font_size=self._toast_font_size(),
                anchor=self._notification_anchor(),
            )
        try:
            if use_local:
                text = local_engine.transcribe(wav) if local_engine is not None else ""
            else:
                text = WhisperClient(settings_obj).transcribe(wav)
            elapsed = time.perf_counter() - started
            log.info("%s: transcription returned in %.2fs", context, elapsed)
            cleaned = self._sanitize_text(text)
            log.info("%s: cleaned chars=%d", context, len(cleaned))
            self._record_speed_stats(len(cleaned), elapsed)
            if cleaned:
                self._deliver(cleaned, speed_badge=self._speed_badge_text(), force_no_insert=force_no_insert)
                log.info("%s: delivered result", context)
                return True, f"Transcribed ({elapsed:.2f}s)."
            if self._settings.get("show_empty_notification", True):
                self._toast.show(
                    "",
                    "Empty Input",
                    theme=self.current_theme(),
                    font_size=self._toast_font_size(),
                    width=self._toast_width(),
                    max_height=self._toast_height(),
                    fade_in_duration_ms=self._toast_fade_in_duration_ms(),
                    visible_duration_ms=self._toast_duration_ms(),
                    fade_duration_ms=self._toast_fade_duration_ms(),
                    anchor=self._notification_anchor(),
                )
                log.info("%s: empty result toast shown", context)
            else:
                log.info("%s: empty result", context)
            return True, "Empty result."
        except Exception as exc:
            log.exception("%s: transcription failed", context)
            return False, f"Transcription failed: {exc}"
        finally:
            if show_spinner:
                self._spinner.hide()

    def _load_audio_for_transcribe(self, path: str) -> bytes:
        ext = os.path.splitext(path or "")[1].lower()
        if ext in {".wav", ".mp3"}:
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                path,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                "pipe:1",
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=90, **_no_window_kwargs())
                if result.returncode == 0 and result.stdout:
                    return result.stdout
            except Exception:
                pass
        with open(path, "rb") as f:
            raw = f.read()
        return self._force_mono_wav_bytes(raw)

    def _force_mono_wav_bytes(self, wav_bytes: bytes) -> bytes:
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as rf:
                ch = int(rf.getnchannels())
                sw = int(rf.getsampwidth())
                rate = int(rf.getframerate())
                frames = int(rf.getnframes())
                raw = rf.readframes(frames)
            if ch <= 1 or sw != 2 or frames <= 0:
                return wav_bytes
            audio = np.frombuffer(raw, dtype=np.int16).reshape(-1, ch)
            audio_f = audio.astype(np.float32)
            strongest_idx = np.argmax(np.abs(audio_f), axis=1)
            mono = audio_f[np.arange(audio_f.shape[0]), strongest_idx].astype(np.int16)
            out = io.BytesIO()
            with wave.open(out, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(rate)
                wf.writeframes(mono.tobytes())
            log.info("Use recorded: coerced WAV to mono (channels=%d -> 1, max-abs fold)", ch)
            return out.getvalue()
        except Exception:
            return wav_bytes

    def _get_speed_stats_mode(self) -> str:
        return self._speed_stats_mode

    def _set_speed_stats_mode(self, mode: str) -> None:
        normalized = (mode or "disabled").strip().lower()
        if normalized not in {"disabled", "current", "average"}:
            normalized = "disabled"
        self._speed_stats_mode = normalized

    def _record_speed_stats(self, chars: int, elapsed_s: float) -> None:
        now = time.time()
        self._speed_samples.append((now, max(0, int(chars)), max(0.0, float(elapsed_s))))
        self._prune_speed_samples(now)

    def _prune_speed_samples(self, now: float | None = None) -> None:
        cutoff = (time.time() if now is None else now) - 60.0
        while self._speed_samples and self._speed_samples[0][0] < cutoff:
            self._speed_samples.popleft()

    def _speed_badge_text(self) -> str:
        mode = self._speed_stats_mode
        if mode == "disabled":
            return ""

        self._prune_speed_samples()
        if not self._speed_samples:
            return ""

        if mode == "current":
            _, chars, elapsed_s = self._speed_samples[-1]
            cps = (chars / elapsed_s) if elapsed_s > 0 else 0.0
            return f"{cps:.1f} cps | {elapsed_s:.2f} s"
        else:
            total_chars = sum(s[1] for s in self._speed_samples)
            total_secs = sum(s[2] for s in self._speed_samples)
            if total_secs <= 0:
                return ""
            cps = total_chars / total_secs
            return f"{cps:.1f} cps avg | {total_secs:.2f} s"

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
            or new_settings.get("system_audio_hotkey") != self._settings.get("system_audio_hotkey")
            or new_settings.get("hotkey_mode") != self._settings.get("hotkey_mode")
            or bool(new_settings.get("suppress_hotkey", False)) != bool(self._settings.get("suppress_hotkey", False))
        )
        autostart_wanted = bool(new_settings.get("autostart"))
        autostart_changed = autostart_wanted != is_autostart_enabled()

        old_device = self._settings.get("model_device")
        old_portable = self._settings.get("portable_models")
        old_backend = self._settings.get("whisper_backend")

        self._settings.update(new_settings)
        self._apply_theme()

        if (
            new_settings.get("model_device") != old_device
            or new_settings.get("portable_models") != old_portable
            or new_settings.get("whisper_backend") != old_backend
        ):
            self._local_engine.unload()

        if hotkey_changed:
            self._register_hotkey()

        if autostart_changed:
            set_autostart(autostart_wanted)

    def quit(self):
        self._hotkey_mgr.stop()
        self._system_hotkey_mgr.stop()
        self._tray.stop()
        self._ui.quit()


if __name__ == "__main__":
    SmolSTTApp().start()
