import configparser
import sys
from pathlib import Path

SECTION = "SmolSTT"

DEFAULT_SETTINGS = {
    # API
    "api_url": "http://localhost:9876",
    "api_endpoint": "/v1/audio/transcriptions",
    "model": "whisper-tiny",
    "language": "auto",
    # Hotkey
    "hotkey": "ctrl+shift+space",
    "system_audio_hotkey": "",
    "hotkey_mode": "toggle",        # "toggle" | "hold"
    "suppress_hotkey": False,       # if True, hotkey keystrokes are swallowed system-wide
    # Output
    "output_clipboard": False,      # copy result to clipboard
    "output_insert": True,          # insert at cursor
    "output_insert_method": "type", # "paste" | "type"
    "typing_speed": 1000,           # characters per second when output_insert_method=type
    "show_notification": True,      # pop-up toast
    "show_empty_notification": True,
    "show_sensitivity_reject_notification": True,
    "show_recording_indicator": True,
    "show_transcribing_notification": True,
    "notification_font_size": 15,
    "notification_width": 400,
    "notification_height": 400,
    "notification_fade_in_duration_s": 0.5,
    "notification_duration_s": 3.0,
    "notification_fade_duration_s": 1.0,
    "notification_anchor": "bottom_right",
    "app_theme": "dark",            # "dark" | "light"
    # Microphone
    "microphone_index": None,
    "microphone_name": "Default",
    "microphone_sensitivity_enabled": False,  # legacy key, kept for compatibility
    "microphone_sensitivity": 80,   # 0 disables sensitivity gating; otherwise minimum RMS
    "sample_rate": 16000,
    # Local inference
    "model_device": "gpu",          # "cpu" | "gpu"
    "portable_models": False,       # store models in ./models/ instead of HF cache
    "output_capture_source": "auto",
    "test_input_file": "",
    "whisper_backend": "local",     # "local" (faster-whisper) | "api" (external server)
    "local_ready_models": "",       # JSON list of known-ready local model cache tokens
    "speed_stats_mode": "current",  # "disabled" | "current" | "average"
}

# Keys managed outside the INI file (e.g. registry); never written to disk.
_SKIP_KEYS = {"autostart"}


def _config_path() -> Path:
    """SmolSTT.ini sits next to the exe (frozen) or the project root (script)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "SmolSTT.ini"
    # __file__ is src/settings_manager.py → parent.parent is project root
    return Path(__file__).resolve().parent.parent / "SmolSTT.ini"


CONFIG_FILE = _config_path()


def _serialize(value) -> str:
    if value is None:
        return ""
    return str(value)


def _coerce(key: str, raw: str):
    """Parse a raw INI string back to the correct Python type."""
    default = DEFAULT_SETTINGS.get(key)
    if default is None:
        # e.g. microphone_index: try int, fall back to None
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return raw or None
    if isinstance(default, bool):
        return raw.strip().lower() in ("true", "1", "yes")
    if isinstance(default, int):
        try:
            return int(raw)
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(raw)
        except ValueError:
            return default
    return raw


class SettingsManager:
    def __init__(self):
        self._settings = DEFAULT_SETTINGS.copy()
        self._load()

    def _load(self):
        try:
            config = configparser.RawConfigParser()
            config.read(CONFIG_FILE, encoding="utf-8")
            if config.has_section(SECTION):
                for key, raw in config.items(SECTION):
                    if key in DEFAULT_SETTINGS:
                        self._settings[key] = _coerce(key, raw)
                self._migrate()
        except Exception:
            pass

    def _migrate(self):
        """Auto-fix settings written by older SmolSTT versions."""
        changed = False

        # Old endpoint / port
        if self._settings.get("api_endpoint") == "/asr":
            self._settings["api_endpoint"] = "/v1/audio/transcriptions"
            changed = True
        if self._settings.get("api_url") == "http://localhost:9000":
            self._settings["api_url"] = "http://localhost:9876"
            changed = True

        # Ensure new keys exist
        for key, val in DEFAULT_SETTINGS.items():
            if key not in self._settings:
                self._settings[key] = val
                changed = True

        # Migrate model_device "all" → "gpu"
        if self._settings.get("model_device") == "all":
            self._settings["model_device"] = "gpu"
            changed = True

        # Normalize whisper_backend
        if self._settings.get("whisper_backend") not in ("local", "api"):
            self._settings["whisper_backend"] = "local"
            changed = True
        suppress_hotkey = bool(self._settings.get("suppress_hotkey", False))
        if self._settings.get("suppress_hotkey") != suppress_hotkey:
            self._settings["suppress_hotkey"] = suppress_hotkey
            changed = True
        if self._settings.get("speed_stats_mode") not in ("disabled", "current", "average"):
            self._settings["speed_stats_mode"] = "disabled"
            changed = True

        # Migrate old flat output_action → new split booleans
        if "output_action" in self._settings:
            old = self._settings.pop("output_action")
            if old == "paste":
                self._settings["output_clipboard"] = False
                self._settings["output_insert"] = True
                self._settings["output_insert_method"] = "paste"
            changed = True

        # Remove deprecated keys
        if "task" in self._settings:
            self._settings.pop("task", None)
            changed = True
        if "popup_theme" in self._settings:
            self._settings.pop("popup_theme", None)
            changed = True
        if "show_recording_notification" in self._settings:
            self._settings.pop("show_recording_notification", None)
            changed = True
        if "app_theme" in self._settings:
            val = str(self._settings.get("app_theme", "dark")).strip().lower()
            if val not in {"dark", "light"}:
                self._settings["app_theme"] = "dark"
                changed = True

        try:
            speed = int(self._settings.get("typing_speed", 1000))
        except (TypeError, ValueError):
            speed = 1000
        speed = max(50, min(speed, 5000))
        if self._settings.get("typing_speed") != speed:
            self._settings["typing_speed"] = speed
            changed = True

        show_reject = bool(self._settings.get("show_sensitivity_reject_notification", True))
        if self._settings.get("show_sensitivity_reject_notification") != show_reject:
            self._settings["show_sensitivity_reject_notification"] = show_reject
            changed = True
        show_empty = bool(self._settings.get("show_empty_notification", True))
        if self._settings.get("show_empty_notification") != show_empty:
            self._settings["show_empty_notification"] = show_empty
            changed = True
        show_indicator = bool(self._settings.get("show_recording_indicator", True))
        if self._settings.get("show_recording_indicator") != show_indicator:
            self._settings["show_recording_indicator"] = show_indicator
            changed = True
        show_transcribing = bool(self._settings.get("show_transcribing_notification", True))
        if self._settings.get("show_transcribing_notification") != show_transcribing:
            self._settings["show_transcribing_notification"] = show_transcribing
            changed = True
        anchor = str(self._settings.get("notification_anchor", "bottom_right") or "bottom_right").strip().lower()
        if anchor not in {
            "bottom_right", "bottom_left", "top_right", "top_left",
            "top_center", "bottom_center", "left_center", "right_center",
        }:
            anchor = "bottom_right"
        if self._settings.get("notification_anchor") != anchor:
            self._settings["notification_anchor"] = anchor
            changed = True

        model_aliases = {
            "tiny": "whisper-tiny",
            "base": "whisper-base",
            "small": "whisper-small",
            "medium": "whisper-medium",
            "large": "whisper-large",
            "large-v3": "whisper-large-v3",
            "parakeet-tdt-0.6b-fp16": "parakeet-tdt-0.6b-v3-fp32",
        }
        model = str(self._settings.get("model", "whisper-small")).strip().lower()
        mapped = model_aliases.get(model, model)
        if mapped != self._settings.get("model"):
            self._settings["model"] = mapped
            changed = True

        try:
            sensitivity = int(self._settings.get("microphone_sensitivity", 80))
        except (TypeError, ValueError):
            sensitivity = 80
        sensitivity = max(0, min(sensitivity, 4000))
        if self._settings.get("microphone_sensitivity") != sensitivity:
            self._settings["microphone_sensitivity"] = sensitivity
            changed = True

        enabled = bool(self._settings.get("microphone_sensitivity_enabled", False))
        if self._settings.get("microphone_sensitivity_enabled") != enabled:
            self._settings["microphone_sensitivity_enabled"] = enabled
            changed = True

        try:
            font_size = int(self._settings.get("notification_font_size", 11))
        except (TypeError, ValueError):
            font_size = 11
        font_size = max(9, min(font_size, 24))
        if self._settings.get("notification_font_size") != font_size:
            self._settings["notification_font_size"] = font_size
            changed = True

        try:
            note_width = int(self._settings.get("notification_width", 390))
        except (TypeError, ValueError):
            note_width = 390
        note_width = max(50, min(note_width, 2400))
        if self._settings.get("notification_width") != note_width:
            self._settings["notification_width"] = note_width
            changed = True

        try:
            note_height = int(self._settings.get("notification_height", 0))
        except (TypeError, ValueError):
            note_height = 0
        note_height = max(0, min(note_height, 2400))
        if self._settings.get("notification_height") != note_height:
            self._settings["notification_height"] = note_height
            changed = True

        if "notification_duration_s" not in self._settings:
            try:
                self._settings["notification_duration_s"] = (
                    float(self._settings.get("notification_duration_ms", 4000)) / 1000.0
                )
            except (TypeError, ValueError):
                self._settings["notification_duration_s"] = 4.0
            changed = True

        if "notification_fade_in_duration_s" not in self._settings:
            self._settings["notification_fade_in_duration_s"] = 0.10
            changed = True

        if "notification_fade_duration_s" not in self._settings:
            try:
                self._settings["notification_fade_duration_s"] = (
                    float(self._settings.get("notification_fade_duration_ms", 220)) / 1000.0
                )
            except (TypeError, ValueError):
                self._settings["notification_fade_duration_s"] = 0.22
            changed = True

        try:
            note_duration = float(self._settings.get("notification_duration_s", 4.0))
        except (TypeError, ValueError):
            note_duration = 4.0
        note_duration = max(0.3, min(note_duration, 60.0))
        if self._settings.get("notification_duration_s") != note_duration:
            self._settings["notification_duration_s"] = note_duration
            changed = True

        try:
            fade_in_duration = float(self._settings.get("notification_fade_in_duration_s", 0.10))
        except (TypeError, ValueError):
            fade_in_duration = 0.10
        fade_in_duration = max(0.0, min(fade_in_duration, 10.0))
        if self._settings.get("notification_fade_in_duration_s") != fade_in_duration:
            self._settings["notification_fade_in_duration_s"] = fade_in_duration
            changed = True

        try:
            fade_duration = float(self._settings.get("notification_fade_duration_s", 0.22))
        except (TypeError, ValueError):
            fade_duration = 0.22
        fade_duration = max(0.0, min(fade_duration, 10.0))
        if self._settings.get("notification_fade_duration_s") != fade_duration:
            self._settings["notification_fade_duration_s"] = fade_duration
            changed = True

        # Drop deprecated notification keys once migrated.
        for old_key in (
            "notification_crop_enabled",
            "notification_crop_length",
            "notification_fade_step_s",
            "notification_duration_ms",
            "notification_fade_duration_ms",
            "notification_fade_step_ms",
        ):
            if old_key in self._settings:
                self._settings.pop(old_key, None)
                changed = True

        if changed:
            self.save()

    def save(self):
        config = configparser.RawConfigParser()
        config.add_section(SECTION)
        for key, value in self._settings.items():
            if key in _SKIP_KEYS:
                continue
            if value != DEFAULT_SETTINGS.get(key):
                config.set(SECTION, key, _serialize(value))
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                config.write(f)
        except Exception:
            pass

    def get(self, key, default=None):
        return self._settings.get(key, default)

    def update(self, new_settings: dict):
        self._settings.update(new_settings)
        self.save()
