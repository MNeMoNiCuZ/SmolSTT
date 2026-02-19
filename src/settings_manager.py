import json
from pathlib import Path

DEFAULT_SETTINGS = {
    # API
    "api_url": "http://localhost:9876",
    "api_endpoint": "/v1/audio/transcriptions",
    "model": "whisper-small",
    "language": "en",
    # Hotkey
    "hotkey": "ctrl+shift+space",
    "hotkey_mode": "toggle",        # "toggle" | "hold"
    # Output
    "output_clipboard": True,       # copy result to clipboard
    "output_insert": False,         # insert at cursor
    "output_insert_method": "paste", # "paste" | "type"
    "typing_speed": 100,            # characters per second when output_insert_method=type
    "show_notification": True,      # pop-up toast
    "show_sensitivity_reject_notification": True,
    "show_recording_indicator": True,
    "show_transcribing_notification": True,
    "notification_font_size": 11,
    "notification_width": 390,
    "notification_height": 0,
    "notification_fade_in_duration_s": 0.10,
    "notification_duration_s": 4.0,
    "notification_fade_duration_s": 0.22,
    "app_theme": "dark",            # "dark" | "light"
    # Microphone
    "microphone_index": None,
    "microphone_name": "Default",
    "microphone_sensitivity_enabled": False,
    "microphone_sensitivity": 120,  # minimum RMS level to keep recording
    "sample_rate": 16000,
    # General
    "autostart": False,
}

CONFIG_DIR = Path.home() / ".smolstt"
CONFIG_FILE = CONFIG_DIR / "settings.json"


class SettingsManager:
    def __init__(self):
        self._settings = DEFAULT_SETTINGS.copy()
        self._load()

    def _load(self):
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._settings.update(saved)
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
            speed = int(self._settings.get("typing_speed", 100))
        except (TypeError, ValueError):
            speed = 100
        speed = max(50, min(speed, 1000))
        if self._settings.get("typing_speed") != speed:
            self._settings["typing_speed"] = speed
            changed = True

        show_reject = bool(self._settings.get("show_sensitivity_reject_notification", True))
        if self._settings.get("show_sensitivity_reject_notification") != show_reject:
            self._settings["show_sensitivity_reject_notification"] = show_reject
            changed = True
        show_indicator = bool(self._settings.get("show_recording_indicator", True))
        if self._settings.get("show_recording_indicator") != show_indicator:
            self._settings["show_recording_indicator"] = show_indicator
            changed = True
        show_transcribing = bool(self._settings.get("show_transcribing_notification", True))
        if self._settings.get("show_transcribing_notification") != show_transcribing:
            self._settings["show_transcribing_notification"] = show_transcribing
            changed = True

        model_aliases = {
            "tiny": "whisper-tiny",
            "base": "whisper-base",
            "small": "whisper-small",
            "medium": "whisper-medium",
            "large": "whisper-large",
            "large-v3": "whisper-large-v3",
        }
        model = str(self._settings.get("model", "whisper-small")).strip().lower()
        mapped = model_aliases.get(model, model)
        if mapped != self._settings.get("model"):
            self._settings["model"] = mapped
            changed = True

        try:
            sensitivity = int(self._settings.get("microphone_sensitivity", 120))
        except (TypeError, ValueError):
            sensitivity = 120
        sensitivity = max(1, min(sensitivity, 4000))
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
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
        except Exception:
            pass

    def get(self, key, default=None):
        return self._settings.get(key, default)

    def update(self, new_settings: dict):
        self._settings.update(new_settings)
        self.save()
