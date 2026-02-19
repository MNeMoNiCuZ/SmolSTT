import queue
import numpy as np
import sounddevice as sd
from PyQt6 import QtCore, QtWidgets

from api_client import ping
from autostart import is_autostart_enabled
from hotkey_picker import HotkeyPickerDialog
from theme import normalize_theme, settings_stylesheet


MODEL_OPTIONS = [
    "whisper-tiny",
    "whisper-tiny-en",
    "whisper-base",
    "whisper-base-en",
    "whisper-small",
    "whisper-small-en",
    "whisper-medium",
    "whisper-medium-en",
    "whisper-large",
    "whisper-large-v1",
    "whisper-large-v2",
    "whisper-large-v3",
    "whisper-turbo",
]

LANGUAGE_OPTIONS = [
    "auto",
    "en",
    "de",
    "fr",
    "es",
    "it",
    "pt",
    "nl",
    "sv",
    "no",
    "da",
    "fi",
    "pl",
    "cs",
    "ru",
    "uk",
    "tr",
    "ar",
    "hi",
    "ja",
    "ko",
    "zh",
]


class FlexibleDoubleSpinBox(QtWidgets.QDoubleSpinBox):
    """Accept both comma and period as decimal separators and always display period."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLocale(QtCore.QLocale(QtCore.QLocale.Language.English, QtCore.QLocale.Country.UnitedStates))

    def _normalize(self, text: str) -> str:
        return (text or "").strip().replace(",", ".")

    def valueFromText(self, text: str) -> float:
        return super().valueFromText(self._normalize(text))

    def validate(self, text: str, pos: int):
        normalized = self._normalize(text)
        return super().validate(normalized, min(pos, len(normalized)))

    def textFromValue(self, value: float) -> str:
        return f"{float(value):.{self.decimals()}f}"


class SensitivityTestDialog(QtWidgets.QDialog):
    def __init__(self, parent, device_index: int | None, initial_threshold: int, theme: str):
        super().__init__(parent)
        self.setWindowTitle("Microphone Sensitivity Test")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setStyleSheet(settings_stylesheet(theme))

        self._device_index = None if device_index == -1 else device_index
        self._stream = None
        self._levels: queue.Queue[float] = queue.Queue()

        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(10)

        root.addWidget(QtWidgets.QLabel("Lower threshold = more sensitive. Higher threshold = less sensitive."))

        self._meter = QtWidgets.QProgressBar()
        self._meter.setRange(0, 4000)
        self._meter.setToolTip("Live RMS microphone level.")
        root.addWidget(self._meter)

        self._level_label = QtWidgets.QLabel("Live RMS: 0")
        root.addWidget(self._level_label)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Threshold"))
        self._threshold = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self._threshold.setRange(1, 4000)
        self._threshold.setValue(max(1, min(initial_threshold, 4000)))
        self._threshold.setToolTip("Lower value captures quieter audio.")
        row.addWidget(self._threshold, 1)
        self._threshold_value = QtWidgets.QLabel(str(self._threshold.value()))
        row.addWidget(self._threshold_value)
        root.addLayout(row)

        self._state = QtWidgets.QLabel("Click Start to monitor microphone level.")
        root.addWidget(self._state)

        btns = QtWidgets.QHBoxLayout()
        self._start_btn = QtWidgets.QPushButton("Start")
        self._stop_btn = QtWidgets.QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        ok_btn = QtWidgets.QPushButton("Use Threshold")
        close_btn = QtWidgets.QPushButton("Close")
        btns.addWidget(self._start_btn)
        btns.addWidget(self._stop_btn)
        btns.addStretch(1)
        btns.addWidget(ok_btn)
        btns.addWidget(close_btn)
        root.addLayout(btns)

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._drain_levels)

        self._threshold.valueChanged.connect(lambda v: self._threshold_value.setText(str(v)))
        self._start_btn.clicked.connect(self._start)
        self._stop_btn.clicked.connect(self._stop)
        ok_btn.clicked.connect(self.accept)
        close_btn.clicked.connect(self.reject)

    def threshold(self) -> int:
        return int(self._threshold.value())

    def closeEvent(self, event):
        self._stop()
        super().closeEvent(event)

    def _start(self):
        if self._stream is not None:
            return

        def _callback(indata, frames, time_info, status):
            if status:
                return
            rms = float(np.sqrt(np.mean(np.square(indata.astype(np.float32)))))
            try:
                self._levels.put_nowait(rms)
            except queue.Full:
                pass

        try:
            self._stream = sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="int16",
                device=self._device_index,
                callback=_callback,
            )
            self._stream.start()
            self._timer.start(80)
            self._state.setText("Listening...")
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
        except Exception as exc:
            self._state.setText(f"Could not start test: {exc}")
            self._stream = None

    def _stop(self):
        self._timer.stop()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)

    def _drain_levels(self):
        latest = None
        while not self._levels.empty():
            latest = self._levels.get_nowait()
        if latest is None:
            return

        val = int(max(0, min(4000, latest)))
        self._meter.setValue(val)
        self._level_label.setText(f"Live RMS: {val}")

        if val >= self._threshold.value():
            self._state.setText("Current voice level is above threshold.")
        else:
            self._state.setText("Current voice is below threshold. Lower threshold for more sensitivity.")


class SettingsWindow:
    def __init__(self, ui_host, settings_manager, on_save):
        self._ui = ui_host
        self._settings = settings_manager
        self._on_save = on_save
        self._window: QtWidgets.QDialog | None = None
        self._dirty = False

    def open(self):
        self._ui.call_soon(self._open_ui)

    def _open_ui(self):
        if self._window is not None and self._window.isVisible():
            self._window.raise_()
            self._window.activateWindow()
            return

        theme = normalize_theme(self._settings.get("app_theme", "dark"))

        win = QtWidgets.QDialog()
        win.setWindowTitle("SmolSTT Settings")
        win.setModal(False)
        win.setFixedWidth(760)
        win.setStyleSheet(settings_stylesheet(theme))
        self._window = win

        root = QtWidgets.QVBoxLayout(win)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        server_group = QtWidgets.QGroupBox("Server")
        server_layout = QtWidgets.QVBoxLayout(server_group)
        server_layout.setSpacing(8)
        root.addWidget(server_group)

        hotkey_group = QtWidgets.QGroupBox("Hotkey")
        hotkey_layout = QtWidgets.QVBoxLayout(hotkey_group)
        hotkey_layout.setSpacing(8)
        root.addWidget(hotkey_group)

        mic_group = QtWidgets.QGroupBox("Microphone")
        mic_layout = QtWidgets.QVBoxLayout(mic_group)
        mic_layout.setSpacing(8)
        root.addWidget(mic_group)

        output_group = QtWidgets.QGroupBox("Output")
        output_layout = QtWidgets.QVBoxLayout(output_group)
        output_layout.setSpacing(8)
        root.addWidget(output_group)

        notify_group = QtWidgets.QGroupBox("Notifications")
        notify_layout = QtWidgets.QVBoxLayout(notify_group)
        notify_layout.setSpacing(8)
        root.addWidget(notify_group)

        self._api_url = QtWidgets.QLineEdit(self._settings.get("api_url"))
        self._api_url.setToolTip("Base URL for your Whisper/OpenAI-compatible API server.")
        self._api_url.setMinimumWidth(180)
        self._api_url.setMaximumWidth(240)

        self._endpoint = QtWidgets.QLineEdit(self._settings.get("api_endpoint"))
        self._endpoint.setToolTip("Transcription endpoint path.")
        self._endpoint.setMinimumWidth(180)
        self._endpoint.setMaximumWidth(260)
        row_endpoint = QtWidgets.QHBoxLayout()
        server_label = QtWidgets.QLabel("Server")
        server_label.setToolTip("Base URL for your Whisper/OpenAI-compatible API server.")
        row_endpoint.addWidget(server_label)
        row_endpoint.addWidget(self._api_url)
        row_endpoint.addSpacing(10)
        endpoint_label = QtWidgets.QLabel("Endpoint")
        endpoint_label.setToolTip("Transcription endpoint path.")
        row_endpoint.addWidget(endpoint_label)
        row_endpoint.addWidget(self._endpoint)
        self._test_btn = QtWidgets.QPushButton("Test Connection")
        self._test_btn.setToolTip("Check if API server is reachable.")
        self._test_btn.clicked.connect(self._test_connection)
        self._test_status = QtWidgets.QLabel("")
        self._test_status.setToolTip("Connection test result.")
        self._test_status.setMinimumWidth(90)
        self._test_status.setMaximumWidth(140)
        row_endpoint.addWidget(self._test_btn)
        row_endpoint.addWidget(self._test_status)
        row_endpoint.addStretch(1)
        server_layout.addLayout(row_endpoint)

        self._model = QtWidgets.QComboBox()
        self._model.setEditable(True)
        self._model.addItems(MODEL_OPTIONS)
        self._model.setCurrentText(self._settings.get("model", "whisper-small"))
        self._model.setToolTip("Model name sent to the API.")
        self._model.setMinimumWidth(180)
        self._model.setMaximumWidth(240)

        self._language = QtWidgets.QComboBox()
        self._language.setEditable(True)
        self._language.addItems(LANGUAGE_OPTIONS)
        self._language.setCurrentText(self._settings.get("language", "en"))
        self._language.setToolTip("Language hint for transcription.")
        self._language.setMinimumWidth(140)
        self._language.setMaximumWidth(180)
        self._language.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow)

        row_model = QtWidgets.QHBoxLayout()
        model_label = QtWidgets.QLabel("Model")
        model_label.setToolTip("Model name sent to the API.")
        row_model.addWidget(model_label)
        row_model.addWidget(self._model)
        row_model.addSpacing(10)
        language_label = QtWidgets.QLabel("Language")
        language_label.setToolTip("Language hint for transcription.")
        row_model.addWidget(language_label)
        row_model.addWidget(self._language)
        row_model.addStretch(1)
        server_layout.addLayout(row_model)

        self._hotkey = QtWidgets.QLineEdit(self._settings.get("hotkey"))
        self._hotkey.setToolTip("Global hotkey combination.")
        hk_btn = QtWidgets.QPushButton("Set Hotkey")
        hk_btn.setToolTip("Open hotkey picker dialog.")
        hk_btn.clicked.connect(self._pick_hotkey)

        self._mode_toggle = QtWidgets.QRadioButton("Toggle")
        self._mode_hold = QtWidgets.QRadioButton("Hold")
        self._mode_toggle.setToolTip("One press starts and next press stops recording.")
        self._mode_hold.setToolTip("Recording is active while hotkey is held.")
        if self._settings.get("hotkey_mode", "toggle") == "hold":
            self._mode_hold.setChecked(True)
        else:
            self._mode_toggle.setChecked(True)

        hk_row = QtWidgets.QHBoxLayout()
        hk_row.addWidget(QtWidgets.QLabel("Hotkey"))
        hk_row.addWidget(self._hotkey, 1)
        hk_row.addWidget(hk_btn)
        hk_row.addSpacing(12)
        hk_row.addWidget(self._mode_toggle)
        hk_row.addWidget(self._mode_hold)
        hk_row.addStretch(1)
        hotkey_layout.addLayout(hk_row)

        self._mic_labels, self._mic_indices = self._load_devices()
        self._mic = QtWidgets.QComboBox()
        self._mic.addItems(self._mic_labels)
        current_name = self._settings.get("microphone_name", "Default")
        if current_name in self._mic_labels:
            self._mic.setCurrentIndex(self._mic_labels.index(current_name))
        self._mic.setToolTip("Audio input device.")
        self._mic.setMinimumWidth(280)
        self._mic.setMaximumWidth(360)

        self._sens_enabled = QtWidgets.QCheckBox("Use sensitivity")
        self._sens_enabled.setChecked(bool(self._settings.get("microphone_sensitivity_enabled", False)))
        self._sens_enabled.setToolTip("Enable microphone level threshold filter.")

        self._sensitivity = QtWidgets.QSpinBox()
        self._sensitivity.setRange(1, 4000)
        self._sensitivity.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._sensitivity.setValue(int(self._settings.get("microphone_sensitivity", 120)))
        self._sensitivity.setToolTip("Lower value = more sensitive. Higher = less sensitive.")

        sens_btn = QtWidgets.QPushButton("Test")
        sens_btn.setToolTip("Open live microphone level meter.")
        sens_btn.clicked.connect(self._open_sensitivity_test)

        mic_row = QtWidgets.QHBoxLayout()
        mic_row.addWidget(QtWidgets.QLabel("Microphone"))
        mic_row.addWidget(self._mic, 1)
        mic_row.addSpacing(16)
        mic_row.addWidget(self._sens_enabled)
        mic_row.addSpacing(12)
        mic_row.addWidget(QtWidgets.QLabel("Threshold"))
        mic_row.addWidget(self._sensitivity)
        mic_row.addWidget(sens_btn)
        mic_layout.addLayout(mic_row)

        self._out_clipboard = QtWidgets.QCheckBox("Add to clipboard")
        self._out_clipboard.setChecked(bool(self._settings.get("output_clipboard", True)))
        self._out_clipboard.setToolTip("Copy transcription text to clipboard.")

        self._out_insert = QtWidgets.QCheckBox("Insert at cursor")
        self._out_insert.setChecked(bool(self._settings.get("output_insert", False)))
        self._out_insert.setToolTip("Insert output into focused app.")

        self._insert_method = QtWidgets.QComboBox()
        self._insert_method.addItems(["paste", "type"])
        self._insert_method.setCurrentText(self._settings.get("output_insert_method", "paste"))
        self._insert_method.setToolTip("paste uses clipboard; type sends keystrokes.")
        self._insert_method.setMinimumWidth(110)
        self._insert_method.setMaximumWidth(140)

        self._typing_speed = QtWidgets.QSpinBox()
        self._typing_speed.setRange(50, 1000)
        self._typing_speed.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._typing_speed.setValue(int(self._settings.get("typing_speed", 100)))
        self._typing_speed.setToolTip("Characters per second when method is type.")
        self._typing_speed.setMinimumWidth(72)
        self._typing_speed.setMaximumWidth(96)

        output_row = QtWidgets.QHBoxLayout()
        output_row.addWidget(QtWidgets.QLabel("Output"))
        output_row.addWidget(self._out_clipboard)
        output_row.addWidget(self._out_insert)
        output_row.addSpacing(12)
        output_row.addWidget(QtWidgets.QLabel("Method"))
        output_row.addWidget(self._insert_method)
        output_row.addWidget(QtWidgets.QLabel("Typing speed"))
        output_row.addWidget(self._typing_speed)
        output_row.addStretch(1)
        output_layout.addLayout(output_row)

        self._notify = QtWidgets.QCheckBox("Pop-up")
        self._notify.setChecked(bool(self._settings.get("show_notification", True)))
        self._notify.setToolTip("Show popup with transcribed output.")

        self._notify_reject = QtWidgets.QCheckBox("Reject alert")
        self._notify_reject.setChecked(
            bool(self._settings.get("show_sensitivity_reject_notification", True))
        )
        self._notify_reject.setToolTip("Show popup when recording is rejected by sensitivity.")

        self._autostart = QtWidgets.QCheckBox("Start with Windows")
        self._autostart.setChecked(bool(is_autostart_enabled()))
        self._autostart.setToolTip("Launch SmolSTT on sign-in.")

        self._theme = QtWidgets.QComboBox()
        self._theme.addItems(["dark", "light"])
        self._theme.setCurrentText(theme)
        self._theme.setToolTip("Choose app theme for settings, tray menu and popups.")
        self._theme.setMinimumWidth(90)
        self._theme.setMaximumWidth(120)

        self._notify_font_size = QtWidgets.QSpinBox()
        self._notify_font_size.setRange(9, 24)
        self._notify_font_size.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._notify_font_size.setValue(int(self._settings.get("notification_font_size", 11)))
        self._notify_font_size.setToolTip("Notification text size.")

        self._notify_width = QtWidgets.QSpinBox()
        self._notify_width.setRange(50, 2400)
        self._notify_width.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._notify_width.setCorrectionMode(QtWidgets.QAbstractSpinBox.CorrectionMode.CorrectToNearestValue)
        self._notify_width.setValue(int(self._settings.get("notification_width", 390)))
        self._notify_width.setToolTip("Preferred popup width in pixels. Long text grows vertically.")

        self._notify_height = QtWidgets.QSpinBox()
        self._notify_height.setRange(0, 2400)
        self._notify_height.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._notify_height.setValue(int(self._settings.get("notification_height", 0)))
        self._notify_height.setToolTip("Maximum popup height in pixels. Set 0 for no height limit.")

        fade_in_setting = self._settings.get("notification_fade_in_duration_s", None)
        fade_in_seconds = 0.10 if fade_in_setting is None else float(fade_in_setting)
        self._notify_fade_in_duration = FlexibleDoubleSpinBox()
        self._notify_fade_in_duration.setRange(0.0, 10.0)
        self._notify_fade_in_duration.setDecimals(2)
        self._notify_fade_in_duration.setSingleStep(0.05)
        self._notify_fade_in_duration.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._notify_fade_in_duration.setValue(max(0.0, min(fade_in_seconds, 10.0)))
        self._notify_fade_in_duration.setToolTip("Length of the fade-in animation when a notification appears (seconds).")

        duration_setting = self._settings.get("notification_duration_s", None)
        duration_seconds = 4.0 if duration_setting is None else float(duration_setting)
        if duration_setting is None:
            try:
                duration_seconds = float(self._settings.get("notification_duration_ms", 4000)) / 1000.0
            except (TypeError, ValueError):
                duration_seconds = 4.0
        self._notify_duration = FlexibleDoubleSpinBox()
        self._notify_duration.setRange(0.3, 60.0)
        self._notify_duration.setDecimals(1)
        self._notify_duration.setSingleStep(0.1)
        self._notify_duration.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._notify_duration.setValue(max(0.3, min(duration_seconds, 60.0)))
        self._notify_duration.setToolTip("Time the notification stays fully visible after fade-in and before fade-out (seconds).")

        fade_setting = self._settings.get("notification_fade_duration_s", None)
        fade_seconds = 0.22 if fade_setting is None else float(fade_setting)
        if fade_setting is None:
            try:
                fade_seconds = float(self._settings.get("notification_fade_duration_ms", 220)) / 1000.0
            except (TypeError, ValueError):
                fade_seconds = 0.22
        self._notify_fade_duration = FlexibleDoubleSpinBox()
        self._notify_fade_duration.setRange(0.0, 10.0)
        self._notify_fade_duration.setDecimals(2)
        self._notify_fade_duration.setSingleStep(0.05)
        self._notify_fade_duration.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._notify_fade_duration.setValue(max(0.0, min(fade_seconds, 10.0)))
        self._notify_fade_duration.setToolTip("How long the fade-out animation lasts (seconds).")

        self._show_recording_indicator = QtWidgets.QCheckBox("Recording dot")
        self._show_recording_indicator.setChecked(bool(self._settings.get("show_recording_indicator", True)))
        self._show_recording_indicator.setToolTip("Show blinking recording dot while recording.")

        self._show_transcribing_notification = QtWidgets.QCheckBox("Transcribing")
        self._show_transcribing_notification.setChecked(
            bool(self._settings.get("show_transcribing_notification", True))
        )
        self._show_transcribing_notification.setToolTip("Show transcribing spinner during processing.")
        for checkbox in (
            self._notify,
            self._notify_reject,
            self._show_recording_indicator,
            self._show_transcribing_notification,
        ):
            checkbox.setStyleSheet("QCheckBox { font-size: 11px; }")

        notify_row_1 = QtWidgets.QHBoxLayout()
        theme_label = QtWidgets.QLabel("Theme")
        theme_label.setToolTip("Choose app theme for settings, tray menu and popups.")
        notify_row_1.addWidget(theme_label)
        notify_row_1.addWidget(self._theme)
        notify_row_1.addSpacing(8)
        text_size_label = QtWidgets.QLabel("Text size")
        text_size_label.setToolTip("Notification text size.")
        notify_row_1.addWidget(text_size_label)
        notify_row_1.addWidget(self._notify_font_size)
        notify_row_1.addSpacing(10)
        notify_width_label = QtWidgets.QLabel("Notification width")
        notify_width_label.setToolTip("Preferred popup width in pixels. Long text wraps into more lines.")
        notify_row_1.addWidget(notify_width_label)
        notify_row_1.addWidget(self._notify_width)
        notify_row_1.addSpacing(10)
        notify_height_label = QtWidgets.QLabel("Notification height")
        notify_height_label.setToolTip("Maximum popup height in pixels. Set 0 for no height limit.")
        notify_row_1.addWidget(notify_height_label)
        notify_row_1.addWidget(self._notify_height)
        notify_row_1.addStretch(1)
        notify_layout.addLayout(notify_row_1)

        notify_row_2 = QtWidgets.QHBoxLayout()
        notify_row_2.addWidget(self._notify)
        notify_row_2.addWidget(self._notify_reject)
        notify_row_2.addWidget(self._show_recording_indicator)
        notify_row_2.addWidget(self._show_transcribing_notification)
        notify_row_2.addStretch(1)
        notify_layout.addLayout(notify_row_2)

        notify_row_3 = QtWidgets.QHBoxLayout()
        fade_in_label = QtWidgets.QLabel("Fade in duration")
        fade_in_label.setToolTip("Length of the fade-in animation when a notification appears (seconds).")
        notify_row_3.addWidget(fade_in_label)
        notify_row_3.addWidget(self._notify_fade_in_duration)
        notify_row_3.addSpacing(16)
        duration_label = QtWidgets.QLabel("Notification duration")
        duration_label.setToolTip("Time the notification remains fully visible after fade-in and before fade-out (seconds).")
        notify_row_3.addWidget(duration_label)
        notify_row_3.addWidget(self._notify_duration)
        notify_row_3.addSpacing(16)
        fade_label = QtWidgets.QLabel("Fade out duration")
        fade_label.setToolTip("Length of the fade-out animation after notification duration ends (seconds).")
        notify_row_3.addWidget(fade_label)
        notify_row_3.addWidget(self._notify_fade_duration)
        notify_row_3.addStretch(1)
        notify_layout.addLayout(notify_row_3)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self._autostart)
        buttons.addStretch(1)
        self._apply_btn = QtWidgets.QPushButton("Apply")
        self._apply_btn.setEnabled(False)
        self._apply_btn.setToolTip("Apply settings without closing.")
        self._apply_btn.clicked.connect(self._apply)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(win.close)
        buttons.addWidget(self._apply_btn)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

        self._bind_dirty_tracking()
        win.setFixedSize(760, win.sizeHint().height())
        win.show()

    def _wrap(self, layout: QtWidgets.QLayout) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        widget.setLayout(layout)
        return widget

    def _bind_dirty_tracking(self):
        widgets = [
            self._api_url,
            self._endpoint,
            self._model,
            self._language,
            self._hotkey,
            self._mode_toggle,
            self._mode_hold,
            self._mic,
            self._sens_enabled,
            self._sensitivity,
            self._out_clipboard,
            self._out_insert,
            self._insert_method,
            self._typing_speed,
            self._notify,
            self._notify_reject,
            self._show_recording_indicator,
            self._show_transcribing_notification,
            self._notify_width,
            self._notify_height,
            self._notify_fade_in_duration,
            self._notify_duration,
            self._notify_fade_duration,
            self._autostart,
            self._theme,
            self._notify_font_size,
        ]
        for widget in widgets:
            if isinstance(widget, QtWidgets.QLineEdit):
                widget.textChanged.connect(self._mark_dirty)
            elif isinstance(widget, QtWidgets.QComboBox):
                widget.currentTextChanged.connect(self._mark_dirty)
            elif isinstance(widget, QtWidgets.QAbstractButton):
                widget.toggled.connect(self._mark_dirty)
            elif isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                widget.valueChanged.connect(self._mark_dirty)

    def _mark_dirty(self, *_args):
        self._dirty = True
        if self._apply_btn is not None:
            self._apply_btn.setEnabled(True)

    def _load_devices(self):
        labels = ["Default"]
        indices = [None]
        try:
            for i, dev in enumerate(sd.query_devices()):
                if dev["max_input_channels"] > 0:
                    labels.append(f"{i}: {dev['name']}")
                    indices.append(i)
        except Exception:
            pass
        return labels, indices

    def _pick_hotkey(self):
        dlg = HotkeyPickerDialog(self._hotkey.text().strip(), parent=self._window)
        result = dlg.get()
        if result:
            self._hotkey.setText(result)

    def _test_connection(self):
        url = self._api_url.text().strip().rstrip("/")
        if not url:
            self._test_status.setText("Enter a URL first.")
            return
        self._test_btn.setEnabled(False)
        self._test_status.setText("Testing...")
        ok, msg = ping(url)
        self._show_test_result(ok, msg)

    def _show_test_result(self, ok: bool, msg: str):
        if self._test_btn is not None:
            self._test_btn.setEnabled(True)
            self._test_btn.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        if self._test_status is not None:
            self._test_status.setText("OK" if ok else "Failed")
            self._test_status.setToolTip(msg)
        # Prevent combo editor text from appearing selected after test updates.
        if self._model is not None and self._model.lineEdit() is not None:
            self._model.lineEdit().deselect()

    def _open_sensitivity_test(self):
        idx = self._mic.currentIndex()
        device_index = self._mic_indices[idx] if 0 <= idx < len(self._mic_indices) else None
        dlg = SensitivityTestDialog(
            self._window,
            device_index,
            self._sensitivity.value(),
            normalize_theme(self._theme.currentText()),
        )
        if dlg.exec() == int(QtWidgets.QDialog.DialogCode.Accepted):
            self._sensitivity.setValue(dlg.threshold())
            self._mark_dirty()

    def _apply(self):
        if self._window is None:
            return
        # Commit any in-progress edits so typed values are saved reliably.
        for widget in (
            self._typing_speed,
            self._notify_width,
            self._notify_height,
            self._notify_fade_in_duration,
            self._notify_duration,
            self._notify_fade_duration,
            self._notify_font_size,
            self._sensitivity,
        ):
            if isinstance(widget, QtWidgets.QAbstractSpinBox):
                widget.interpretText()

        mic_idx = self._mic.currentIndex()
        if 0 <= mic_idx < len(self._mic_labels):
            mic_name = self._mic_labels[mic_idx]
            mic_index = self._mic_indices[mic_idx]
        else:
            mic_name = "Default"
            mic_index = None

        hotkey = self._hotkey.text().strip().lower()
        if not hotkey:
            QtWidgets.QMessageBox.critical(self._window, "Invalid hotkey", "Hotkey cannot be empty.")
            return

        new_settings = {
            "api_url": self._api_url.text().strip().rstrip("/"),
            "api_endpoint": "/" + self._endpoint.text().strip("/"),
            "model": self._model.currentText().strip() or "whisper-small",
            "language": self._language.currentText().strip(),
            "hotkey": hotkey,
            "hotkey_mode": "hold" if self._mode_hold.isChecked() else "toggle",
            "microphone_index": mic_index,
            "microphone_name": mic_name,
            "microphone_sensitivity_enabled": self._sens_enabled.isChecked(),
            "microphone_sensitivity": int(self._sensitivity.value()),
            "output_clipboard": self._out_clipboard.isChecked(),
            "output_insert": self._out_insert.isChecked(),
            "output_insert_method": self._insert_method.currentText(),
            "typing_speed": int(self._typing_speed.value()),
            "show_notification": self._notify.isChecked(),
            "show_sensitivity_reject_notification": self._notify_reject.isChecked(),
            "show_recording_indicator": self._show_recording_indicator.isChecked(),
            "show_transcribing_notification": self._show_transcribing_notification.isChecked(),
            "notification_font_size": int(self._notify_font_size.value()),
            "notification_width": int(self._notify_width.value()),
            "notification_height": int(self._notify_height.value()),
            "notification_fade_in_duration_s": float(self._notify_fade_in_duration.value()),
            "notification_duration_s": float(self._notify_duration.value()),
            "notification_fade_duration_s": float(self._notify_fade_duration.value()),
            "autostart": self._autostart.isChecked(),
            "app_theme": normalize_theme(self._theme.currentText()),
        }

        self._on_save(new_settings)
        self._dirty = False
        self._apply_btn.setEnabled(False)

        # Apply selected theme immediately in this open dialog too.
        self._window.setStyleSheet(settings_stylesheet(normalize_theme(self._theme.currentText())))
