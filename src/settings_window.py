import queue
import threading
import os
import random
import numpy as np
import sounddevice as sd
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtGui import QFont, QStandardItem, QStandardItemModel, QTextCursor

from api_client import ping
from autostart import is_autostart_enabled
from hotkey_picker import HotkeyPickerDialog
from logger import log
from theme import normalize_theme, settings_stylesheet


MODEL_CATALOG = [
    # Whisper – local (faster-whisper) or external API
    {"name": "whisper-tiny",          "category": "whisper", "device": "any"},
    {"name": "whisper-tiny-en",       "category": "whisper", "device": "any"},
    {"name": "whisper-base",          "category": "whisper", "device": "any"},
    {"name": "whisper-base-en",       "category": "whisper", "device": "any"},
    {"name": "whisper-small",         "category": "whisper", "device": "any"},
    {"name": "whisper-small-en",      "category": "whisper", "device": "any"},
    {"name": "whisper-medium",        "category": "whisper", "device": "any"},
    {"name": "whisper-medium-en",     "category": "whisper", "device": "any"},
    {"name": "whisper-large",         "category": "whisper", "device": "any"},
    {"name": "whisper-large-v1",      "category": "whisper", "device": "any"},
    {"name": "whisper-large-v2",      "category": "whisper", "device": "any"},
    {"name": "whisper-large-v3",      "category": "whisper", "device": "any"},
    {"name": "whisper-turbo",         "category": "whisper", "device": "any"},
    # Parakeet – always local via onnx-asr
    {"name": "parakeet-tdt-0.6b-v3",      "category": "parakeet", "device": "any"},
    {"name": "parakeet-tdt-0.6b-v3-fp32", "category": "parakeet", "device": "any"},
]

API_WHISPER_MODELS = {
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
}

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


class WidePopupComboBox(QtWidgets.QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup_min_width = 360

    def set_popup_min_width(self, width: int) -> None:
        self._popup_min_width = max(220, int(width))

    def showPopup(self):
        view = self.view()
        if view is not None:
            view.setMinimumWidth(max(self._popup_min_width, self.width()))
        super().showPopup()


class AudioDropLineEdit(QtWidgets.QLineEdit):
    fileDropped = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls() if event.mimeData() is not None else []
        if any(self._is_supported(u.toLocalFile()) for u in urls if u.isLocalFile()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls() if event.mimeData() is not None else []
        for u in urls:
            if not u.isLocalFile():
                continue
            path = u.toLocalFile()
            if self._is_supported(path):
                self.fileDropped.emit(path)
                event.acceptProposedAction()
                return
        event.ignore()

    @staticmethod
    def _is_supported(path: str) -> bool:
        ext = os.path.splitext(path or "")[1].lower()
        return ext in {".wav", ".mp3"}


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
        row.addWidget(QtWidgets.QLabel("Sensitivity Threshold"))
        self._threshold = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self._threshold.setRange(0, 4000)
        self._threshold.setValue(max(0, min(initial_threshold, 4000)))
        self._threshold.setToolTip("Lower value captures quieter audio.")
        row.addWidget(self._threshold, 1)
        self._threshold_value = QtWidgets.QLabel(str(self._threshold.value()))
        row.addWidget(self._threshold_value)
        root.addLayout(row)

        btns = QtWidgets.QHBoxLayout()
        self._start_btn = QtWidgets.QPushButton("Start")
        self._stop_btn = QtWidgets.QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        ok_btn = QtWidgets.QPushButton("Use Sensitivity Threshold")
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
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
        except Exception as exc:
            log.error("Could not start sensitivity test stream: %s", exc)
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


class SettingsWindow:
    def __init__(
        self,
        ui_host,
        settings_manager,
        on_save,
        speed_mode_getter=None,
        speed_mode_setter=None,
        test_start_record_callback=None,
        test_stop_record_callback=None,
        test_start_output_callback=None,
        test_stop_output_callback=None,
        test_use_recorded_callback=None,
        test_has_recorded_callback=None,
        test_delete_recorded_callback=None,
        test_list_output_sources_callback=None,
        test_set_input_file_callback=None,
        notification_preview_callback=None,
    ):
        self._ui = ui_host
        self._settings = settings_manager
        self._on_save = on_save
        self._speed_mode_getter = speed_mode_getter
        self._speed_mode_setter = speed_mode_setter
        self._test_start_record_callback = test_start_record_callback
        self._test_stop_record_callback = test_stop_record_callback
        self._test_start_output_callback = test_start_output_callback
        self._test_stop_output_callback = test_stop_output_callback
        self._test_use_recorded_callback = test_use_recorded_callback
        self._test_has_recorded_callback = test_has_recorded_callback
        self._test_delete_recorded_callback = test_delete_recorded_callback
        self._test_list_output_sources_callback = test_list_output_sources_callback
        self._test_set_input_file_callback = test_set_input_file_callback
        self._notification_preview_callback = notification_preview_callback
        self._window: QtWidgets.QDialog | None = None
        self._dirty = False
        self._is_test_recording = False
        self._is_output_capturing = False
        self._last_test_caption = ""
        self._anchor_test_index = 0

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
        win.setFixedWidth(700)
        win.setStyleSheet(settings_stylesheet(theme))
        self._window = win

        root = QtWidgets.QVBoxLayout(win)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        server_group = QtWidgets.QGroupBox("Program Settings")
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

        testing_group = QtWidgets.QGroupBox("Testing")
        testing_layout = QtWidgets.QVBoxLayout(testing_group)
        testing_layout.setSpacing(8)
        root.addWidget(testing_group)

        # ── Backend (Local / External API) ────────────────────────────────
        saved_backend = self._settings.get("whisper_backend", "local")
        self._backend_local = QtWidgets.QRadioButton("Local")
        self._backend_api   = QtWidgets.QRadioButton("API")
        self._backend_local.setToolTip("Run speech-to-text locally on this computer using downloaded models.")
        self._backend_api.setToolTip("Send audio to an external OpenAI-compatible transcription server.")
        self._backend_group = QtWidgets.QButtonGroup(self._window)
        self._backend_group.setExclusive(True)
        self._backend_group.addButton(self._backend_local)
        self._backend_group.addButton(self._backend_api)
        if saved_backend == "api":
            self._backend_api.setChecked(True)
        else:
            self._backend_local.setChecked(True)

        # ── Server URL / Endpoint ─────────────────────────────────────────
        self._api_url = QtWidgets.QLineEdit(self._settings.get("api_url"))
        self._api_url.setToolTip("Server base URL. Typical value: http://localhost:9876")
        self._api_url.setMinimumWidth(180)
        self._api_url.setMaximumWidth(240)

        self._endpoint = QtWidgets.QLineEdit(self._settings.get("api_endpoint"))
        self._endpoint.setToolTip("HTTP path used for transcription requests. Typical value: /v1/audio/transcriptions")
        self._endpoint.setMinimumWidth(160)
        self._endpoint.setMaximumWidth(220)

        self._server_label = QtWidgets.QLabel("Server")
        self._server_label.setToolTip("Base URL for the external Whisper API server.")
        self._endpoint_label = QtWidgets.QLabel("Endpoint")
        self._endpoint_label.setToolTip("Transcription endpoint path.")

        self._test_btn = QtWidgets.QPushButton("Test")
        self._test_btn.setToolTip("Tests connectivity to the configured API server URL.")
        self._test_btn.clicked.connect(self._test_connection)
        self._test_btn.setMinimumWidth(72)
        self._test_btn.setMaximumWidth(72)
        self._theme = QtWidgets.QComboBox()
        self._theme.addItems(["dark", "light"])
        self._theme.setCurrentText(theme)
        self._theme.setToolTip("Choose light or dark theme for settings, tray menu, spinner and notifications.")
        self._theme.setMinimumWidth(90)
        self._theme.setMaximumWidth(120)

        row_endpoint = QtWidgets.QHBoxLayout()
        row_endpoint.addWidget(self._server_label)
        row_endpoint.addWidget(self._api_url, 2)
        row_endpoint.addSpacing(8)
        row_endpoint.addWidget(self._endpoint_label)
        row_endpoint.addWidget(self._endpoint, 2)
        row_endpoint.addStretch(1)
        row_endpoint.addWidget(self._test_btn)
        server_layout.addLayout(row_endpoint)

        # ── Model / Language ──────────────────────────────────────────────
        saved_model = self._settings.get("model", "whisper-small")
        self._model = self._build_model_combo(saved_model)

        self._language = QtWidgets.QComboBox()
        self._language.setEditable(True)
        self._language.addItems(LANGUAGE_OPTIONS)
        self._language.setCurrentText(self._settings.get("language", "en"))
        self._language.setToolTip("Language hint for transcription.")
        self._language.setMinimumWidth(100)
        self._language.setMaximumWidth(140)
        self._language.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow)

        row_model = QtWidgets.QHBoxLayout()
        model_label = QtWidgets.QLabel("Model")
        model_label.setToolTip("Transcription model.")
        row_model.addWidget(model_label)
        row_model.addWidget(self._model)
        row_model.addSpacing(8)
        language_label = QtWidgets.QLabel("Language")
        language_label.setToolTip("Language hint for transcription.")
        secondary_label_width = max(self._endpoint_label.sizeHint().width(), language_label.sizeHint().width())
        self._endpoint_label.setFixedWidth(secondary_label_width)
        language_label.setFixedWidth(secondary_label_width)
        row_model.addWidget(language_label)
        row_model.addWidget(self._language)
        row_model.addStretch(1)

        server_layout.addLayout(row_model)

        row_test = QtWidgets.QHBoxLayout()
        self._input_file_path = AudioDropLineEdit()
        self._input_file_path.setPlaceholderText("Drag/Drop")
        self._input_file_path.setToolTip("Audio file override. If set, Test uses this file first (.wav/.mp3).")
        self._input_file_path.setText(str(self._settings.get("test_input_file", "") or ""))
        self._input_file_path.setMinimumWidth(150)
        self._input_file_path.setMaximumWidth(180)
        self._input_file_path.fileDropped.connect(self._set_input_file)
        self._record_test_btn = QtWidgets.QPushButton("Microphone")
        self._record_test_btn.setToolTip("Record a temporary microphone clip for testing.")
        self._record_test_btn.clicked.connect(self._toggle_record_test_clip)
        self._record_test_btn.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._record_test_btn.customContextMenuRequested.connect(
            lambda p, btn=self._record_test_btn: self._show_recorded_context_menu(btn, p)
        )
        self._use_recorded_btn = QtWidgets.QPushButton("Test")
        self._use_recorded_btn.setToolTip("Run transcription on the current test source and show the result in Test caption field.")
        self._use_recorded_btn.setMinimumWidth(72)
        self._use_recorded_btn.setMaximumWidth(72)
        self._use_recorded_btn.clicked.connect(self._use_recorded_clip)
        self._use_recorded_btn.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._use_recorded_btn.customContextMenuRequested.connect(
            lambda p, btn=self._use_recorded_btn: self._show_recorded_context_menu(btn, p)
        )
        self._use_output_btn = QtWidgets.QPushButton("System Audio")
        self._use_output_btn.setToolTip("Capture system playback audio (loopback) into the test clip.")
        self._use_output_btn.clicked.connect(self._toggle_output_capture)
        self._output_source = WidePopupComboBox()
        self._output_source.setMinimumWidth(120)
        self._output_source.setMaximumWidth(170)
        self._output_source.setToolTip("Choose which system-audio capture source to use.")
        self._output_source.set_popup_min_width(460)
        self._populate_output_sources()
        row_test.addWidget(self._input_file_path)
        row_test.addWidget(self._record_test_btn)
        row_test.addWidget(self._use_output_btn)
        row_test.addStretch(1)
        row_test.addSpacing(10)
        row_test.addWidget(self._output_source)
        testing_layout.addLayout(row_test)

        self._testing_target = QtWidgets.QPlainTextEdit()
        self._testing_target.setPlaceholderText("Test caption field")
        self._testing_target.setPlainText(self._last_test_caption)
        self._testing_target.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._testing_target.customContextMenuRequested.connect(self._show_testing_target_menu)
        fm = self._testing_target.fontMetrics()
        field_height = int(fm.lineSpacing() * 3 + 16)
        self._testing_target.setFixedHeight(field_height)
        self._use_recorded_btn.setFixedHeight(field_height)

        row_test_caption = QtWidgets.QHBoxLayout()
        row_test_caption.addWidget(self._testing_target, 1)
        row_test_caption.addSpacing(8)
        row_test_caption.addWidget(self._use_recorded_btn)
        testing_layout.addLayout(row_test_caption)

        # ── Device (CPU / GPU) + Portable ────────────────────────────────
        saved_device = self._settings.get("model_device", "gpu")
        self._device_cpu = QtWidgets.QRadioButton("CPU")
        self._device_gpu = QtWidgets.QRadioButton("GPU")
        self._device_cpu.setToolTip("Use CPU for local inference (compatible, usually slower).")
        self._device_gpu.setToolTip("Use GPU for local inference (faster, requires CUDA-compatible setup).")
        self._device_group = QtWidgets.QButtonGroup(self._window)
        self._device_group.setExclusive(True)
        self._device_group.addButton(self._device_cpu)
        self._device_group.addButton(self._device_gpu)
        if saved_device == "cpu":
            self._device_cpu.setChecked(True)
        else:
            self._device_gpu.setChecked(True)

        self._portable_check = QtWidgets.QCheckBox("Portable Mode")
        self._portable_check.setChecked(bool(self._settings.get("portable_models", False)))
        self._portable_check.setToolTip(
            "Store downloaded models in ./models/ next to the app\n"
            "instead of the HuggingFace cache (~/.cache/huggingface)."
        )
        self._portable_check.setStyleSheet("QCheckBox { font-size: 11px; }")

        row_device = QtWidgets.QHBoxLayout()
        row_device.addWidget(self._backend_local)
        row_device.addWidget(self._backend_api)
        row_device.addSpacing(16)
        row_device.addWidget(self._device_cpu)
        row_device.addWidget(self._device_gpu)
        row_device.addStretch(1)
        row_device.addSpacing(16)
        row_device.addWidget(self._portable_check)
        row_device.addSpacing(12)
        row_device.addWidget(QtWidgets.QLabel("Theme"))
        row_device.addWidget(self._theme)
        server_layout.addLayout(row_device)

        # ── Connections ───────────────────────────────────────────────────
        self._model.currentTextChanged.connect(self._on_model_changed)
        self._backend_local.toggled.connect(lambda _: self._on_backend_changed())
        self._backend_api.toggled.connect(lambda _: self._on_backend_changed())
        self._portable_check.toggled.connect(lambda _: self._refresh_test_clip_state())

        # ── Hotkey ────────────────────────────────────────────────────────
        self._hotkey = QtWidgets.QLineEdit(self._settings.get("hotkey"))
        self._hotkey.setToolTip("Global hotkey for microphone capture.")
        self._hotkey.setReadOnly(True)
        self._hotkey.setEnabled(False)
        hk_btn = QtWidgets.QPushButton("Set")
        hk_btn.setToolTip("Open hotkey picker dialog.")
        hk_btn.clicked.connect(self._pick_hotkey)
        self._system_audio_hotkey = QtWidgets.QLineEdit(self._settings.get("system_audio_hotkey", ""))
        self._system_audio_hotkey.setToolTip("Global hotkey for system audio capture/transcription.")
        self._system_audio_hotkey.setReadOnly(True)
        self._system_audio_hotkey.setEnabled(False)
        self._hotkey.setMinimumWidth(154)
        self._hotkey.setMaximumWidth(154)
        self._system_audio_hotkey.setMinimumWidth(154)
        self._system_audio_hotkey.setMaximumWidth(154)
        hk_sys_btn = QtWidgets.QPushButton("Set")
        hk_sys_btn.setToolTip("Open hotkey picker dialog.")
        hk_sys_btn.clicked.connect(self._pick_system_audio_hotkey)

        self._mode_toggle = QtWidgets.QRadioButton("Toggle")
        self._mode_hold = QtWidgets.QRadioButton("Hold")
        self._mode_toggle.setToolTip("Press once to start recording, press again to stop.")
        self._mode_hold.setToolTip("Recording is active only while the hotkey is held down.")
        if self._settings.get("hotkey_mode", "toggle") == "hold":
            self._mode_hold.setChecked(True)
        else:
            self._mode_toggle.setChecked(True)
        self._suppress_hotkey = QtWidgets.QCheckBox("Suppress hotkey")
        self._suppress_hotkey.setChecked(bool(self._settings.get("suppress_hotkey", False)))
        self._suppress_hotkey.setToolTip(
            "If enabled, SmolSTT consumes the hotkey so other apps do not receive it.\n"
            "Risk: may interfere with games or leave modifier keys feeling stuck.\n"
            "Recommended: keep this off unless you explicitly need suppression."
        )

        hk_row = QtWidgets.QHBoxLayout()
        mic_hotkey_label = QtWidgets.QLabel("Microphone Hotkey")
        sys_hotkey_label = QtWidgets.QLabel("System Audio Hotkey")
        label_width = max(
            mic_hotkey_label.fontMetrics().horizontalAdvance("Microphone Hotkey"),
            sys_hotkey_label.fontMetrics().horizontalAdvance("System Audio Hotkey"),
        ) + 6
        mic_hotkey_label.setFixedWidth(label_width)
        sys_hotkey_label.setFixedWidth(label_width)
        hk_row.addWidget(mic_hotkey_label)
        hk_row.addWidget(self._hotkey, 1)
        hk_row.addWidget(hk_btn)
        hk_row.addSpacing(12)
        hk_row.addWidget(self._mode_toggle)
        hk_row.addWidget(self._mode_hold)
        hk_row.addStretch(1)
        hotkey_layout.addLayout(hk_row)

        hk_row_2 = QtWidgets.QHBoxLayout()
        hk_row_2.addWidget(sys_hotkey_label)
        hk_row_2.addWidget(self._system_audio_hotkey, 1)
        hk_row_2.addWidget(hk_sys_btn)
        hk_row_2.addSpacing(8)
        hk_row_2.addWidget(self._suppress_hotkey)
        hk_row_2.addStretch(1)
        hotkey_layout.addLayout(hk_row_2)

        # ── Microphone ────────────────────────────────────────────────────
        self._mic_labels, self._mic_indices = self._load_devices()
        self._mic = WidePopupComboBox()
        self._mic.addItems(self._mic_labels)
        current_name = self._settings.get("microphone_name", "Default")
        if current_name in self._mic_labels:
            self._mic.setCurrentIndex(self._mic_labels.index(current_name))
        self._mic.setToolTip("Microphone/input device used for normal capture.")
        self._mic.setMinimumWidth(140)
        self._mic.setMaximumWidth(180)
        self._mic.set_popup_min_width(520)

        self._sensitivity = QtWidgets.QSpinBox()
        self._sensitivity.setRange(0, 4000)
        self._sensitivity.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._sensitivity.setValue(int(self._settings.get("microphone_sensitivity", 80)))
        self._sensitivity.setToolTip("Sensitivity threshold (RMS). 0 disables filtering; lower values capture quieter speech.")

        sens_btn = QtWidgets.QPushButton("Test")
        sens_btn.setToolTip("Open live microphone level meter.")
        sens_btn.clicked.connect(self._open_sensitivity_test)
        sens_btn.setMinimumWidth(72)
        sens_btn.setMaximumWidth(72)

        mic_row = QtWidgets.QHBoxLayout()
        mic_row.addWidget(QtWidgets.QLabel("Microphone"))
        mic_row.addWidget(self._mic)
        mic_row.addStretch(1)
        threshold_label = QtWidgets.QLabel("Sensitivity Threshold")
        threshold_label.setMinimumWidth(140)
        threshold_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        mic_row.addWidget(threshold_label)
        mic_row.addWidget(self._sensitivity)
        mic_row.addWidget(sens_btn)
        mic_layout.addLayout(mic_row)

        # ── Output ────────────────────────────────────────────────────────
        self._out_clipboard = QtWidgets.QCheckBox("Add to clipboard")
        self._out_clipboard.setChecked(bool(self._settings.get("output_clipboard", True)))
        self._out_clipboard.setToolTip("Copy the transcription result to clipboard.")

        self._out_insert = QtWidgets.QCheckBox("Insert at cursor")
        self._out_insert.setChecked(bool(self._settings.get("output_insert", False)))
        self._out_insert.setToolTip("Type/paste the result into the currently focused app.")

        self._insert_method = QtWidgets.QComboBox()
        self._insert_method.addItems(["paste", "type"])
        self._insert_method.setCurrentText(self._settings.get("output_insert_method", "paste"))
        self._insert_method.setToolTip("Paste uses clipboard; Type sends keystrokes directly.")
        self._insert_method.setMinimumWidth(110)
        self._insert_method.setMaximumWidth(140)

        self._typing_speed = QtWidgets.QSpinBox()
        self._typing_speed.setRange(50, 5000)
        self._typing_speed.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._typing_speed.setValue(int(self._settings.get("typing_speed", 100)))
        self._typing_speed.setToolTip("Typing rate when Method=type. Higher is faster but can be less reliable in some apps.")
        self._typing_speed.setMinimumWidth(72)
        self._typing_speed.setMaximumWidth(96)

        output_row = QtWidgets.QHBoxLayout()
        output_row.addWidget(QtWidgets.QLabel("Output"))
        output_row.addWidget(self._out_clipboard)
        output_row.addWidget(self._out_insert)
        output_row.addStretch(1)
        output_row.addSpacing(8)
        output_row.addWidget(QtWidgets.QLabel("Method"))
        output_row.addWidget(self._insert_method)
        output_row.addWidget(QtWidgets.QLabel("Typing speed"))
        output_row.addWidget(self._typing_speed)
        output_layout.addLayout(output_row)

        # ── Notifications ─────────────────────────────────────────────────
        self._notify = QtWidgets.QCheckBox("Pop-up")
        self._notify.setChecked(bool(self._settings.get("show_notification", True)))
        self._notify.setToolTip("Show popup notifications for transcription results.")

        self._notify_reject = QtWidgets.QCheckBox("Reject alert")
        self._notify_reject.setChecked(
            bool(self._settings.get("show_sensitivity_reject_notification", True))
        )
        self._notify_reject.setToolTip("Show a popup when audio is rejected by sensitivity threshold.")
        self._notify_empty = QtWidgets.QCheckBox("Empty")
        self._notify_empty.setChecked(bool(self._settings.get("show_empty_notification", False)))
        self._notify_empty.setToolTip("Show a popup when transcription returns empty text.")

        self._autostart = QtWidgets.QCheckBox("Start with Windows")
        self._autostart.setChecked(bool(is_autostart_enabled()))
        self._autostart.setToolTip("Launch SmolSTT on sign-in.")

        self._notify_font_size = QtWidgets.QSpinBox()
        self._notify_font_size.setRange(9, 24)
        self._notify_font_size.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._notify_font_size.setValue(int(self._settings.get("notification_font_size", 11)))
        self._notify_font_size.setToolTip("Base text size used in notifications.")

        self._notify_width = QtWidgets.QSpinBox()
        self._notify_width.setRange(50, 2400)
        self._notify_width.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._notify_width.setCorrectionMode(QtWidgets.QAbstractSpinBox.CorrectionMode.CorrectToNearestValue)
        self._notify_width.setValue(int(self._settings.get("notification_width", 390)))
        self._notify_width.setToolTip("Preferred notification width in pixels.")

        self._notify_height = QtWidgets.QSpinBox()
        self._notify_height.setRange(0, 2400)
        self._notify_height.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._notify_height.setValue(int(self._settings.get("notification_height", 0)))
        self._notify_height.setToolTip("Maximum notification height in pixels. Use 0 for no height limit.")

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
        self._show_recording_indicator.setToolTip("Show animated recording dot during capture/preview.")

        self._show_transcribing_notification = QtWidgets.QCheckBox("Transcribing")
        self._show_transcribing_notification.setChecked(
            bool(self._settings.get("show_transcribing_notification", True))
        )
        self._show_transcribing_notification.setToolTip("Show a transcribing spinner while a request is processing.")
        self._speed_mode = QtWidgets.QComboBox()
        self._speed_mode.addItem("Disabled", "disabled")
        self._speed_mode.addItem("Current request", "current")
        self._speed_mode.addItem("Average", "average")
        current_speed_mode = "disabled"
        if callable(self._speed_mode_getter):
            try:
                current_speed_mode = str(self._speed_mode_getter() or "disabled").strip().lower()
            except Exception:
                current_speed_mode = "disabled"
        idx = self._speed_mode.findData(current_speed_mode)
        self._speed_mode.setCurrentIndex(idx if idx >= 0 else 0)
        self._speed_mode.setToolTip(
            "Speed badge in notifications:\n"
            "Disabled = hide stats.\n"
            "Current request = chars/sec + total time for latest result.\n"
            "Average = combined chars/sec + total processing time over recent requests."
        )
        self._speed_mode.currentIndexChanged.connect(self._on_speed_mode_changed)
        self._notification_anchor = QtWidgets.QComboBox()
        self._notification_anchor.addItem("↖", "top_left")
        self._notification_anchor.addItem("↑", "top_center")
        self._notification_anchor.addItem("↗", "top_right")
        self._notification_anchor.addItem("→", "right_center")
        self._notification_anchor.addItem("↘", "bottom_right")
        self._notification_anchor.addItem("↓", "bottom_center")
        self._notification_anchor.addItem("↙", "bottom_left")
        self._notification_anchor.addItem("←", "left_center")
        self._notification_anchor.setToolTip("Choose where notifications/spinner appear on screen.")
        anchor_width = max(48, self._notification_anchor.fontMetrics().horizontalAdvance("Anchor") + 12)
        self._notification_anchor.setFixedWidth(anchor_width)
        anchor_value = str(self._settings.get("notification_anchor", "bottom_right") or "bottom_right")
        self._notification_anchor.blockSignals(True)
        anchor_idx = self._notification_anchor.findData(anchor_value)
        self._notification_anchor.setCurrentIndex(anchor_idx if anchor_idx >= 0 else 0)
        self._notification_anchor.blockSignals(False)
        self._notification_anchor_test_btn = QtWidgets.QPushButton("Test")
        self._notification_anchor_test_btn.setToolTip("Show a 5-second anchor preview (notification + stats + dot).")
        self._notification_anchor_test_btn.setMinimumWidth(72)
        self._notification_anchor_test_btn.setMaximumWidth(72)
        self._notification_anchor_test_btn.clicked.connect(self._on_anchor_test_button)
        self._notification_anchor.currentIndexChanged.connect(self._on_anchor_changed_preview)
        for checkbox in (
            self._notify,
            self._notify_empty,
            self._notify_reject,
            self._show_recording_indicator,
            self._show_transcribing_notification,
        ):
            checkbox.setStyleSheet("QCheckBox { font-size: 11px; }")

        notify_row_1 = QtWidgets.QHBoxLayout()
        text_size_label = QtWidgets.QLabel("Text size")
        text_size_label.setToolTip("Notification text size.")
        notify_row_1.addWidget(text_size_label)
        notify_row_1.addWidget(self._notify_font_size)
        notify_row_1.addSpacing(10)
        notify_width_label = QtWidgets.QLabel("Width")
        notify_width_label.setToolTip("Preferred notification width in pixels.")
        notify_row_1.addWidget(notify_width_label)
        notify_row_1.addWidget(self._notify_width)
        notify_row_1.addSpacing(10)
        notify_height_label = QtWidgets.QLabel("Height")
        notify_height_label.setToolTip("Maximum notification height in pixels. Use 0 for no limit.")
        notify_row_1.addWidget(notify_height_label)
        notify_row_1.addWidget(self._notify_height)
        notify_row_1.addStretch(1)
        anchor_label = QtWidgets.QLabel("Anchor")
        anchor_label.setToolTip("On-screen anchor for notifications.")
        notify_row_1.addWidget(anchor_label)
        notify_row_1.addWidget(self._notification_anchor)
        notify_row_1.addWidget(self._notification_anchor_test_btn)
        notify_layout.addLayout(notify_row_1)

        notify_row_2 = QtWidgets.QHBoxLayout()
        notify_row_2.addWidget(self._notify)
        notify_row_2.addWidget(self._notify_empty)
        notify_row_2.addWidget(self._notify_reject)
        notify_row_2.addWidget(self._show_recording_indicator)
        notify_row_2.addWidget(self._show_transcribing_notification)
        notify_row_2.addStretch(1)
        stats_label = QtWidgets.QLabel("Stats")
        stats_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        notify_row_2.addWidget(stats_label)
        notify_row_2.addWidget(self._speed_mode)
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

        self._normalize_control_heights()
        self._bind_dirty_tracking()
        self._on_model_changed(saved_model)
        self._refresh_test_clip_state()
        # Reset dirty state – _on_model_changed may have toggled radio states
        self._dirty = False
        self._apply_btn.setEnabled(False)
        win.setFixedSize(700, win.sizeHint().height())
        win.show()

    # ── Model combo helpers ───────────────────────────────────────────────

    def _build_model_combo(self, saved_model: str) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        combo.setToolTip("Transcription model.")
        combo.setMinimumWidth(180)
        combo.setMaximumWidth(240)
        std_model = QStandardItemModel()
        combo.setModel(std_model)
        self._populate_model_items(std_model, api_only=bool(self._backend_api.isChecked()))

        # Select saved model by index; fall back to first selectable item.
        first_valid = -1
        for i in range(std_model.rowCount()):
            item = std_model.item(i)
            if item is None:
                continue
            if item.isEnabled() and item.isSelectable():
                if first_valid == -1:
                    first_valid = i
                if item.text() == saved_model:
                    combo.setCurrentIndex(i)
                    return combo
        if first_valid >= 0:
            combo.setCurrentIndex(first_valid)
        return combo

    def _populate_model_items(self, std_model: QStandardItemModel, api_only: bool = False):
        std_model.clear()

        whisper_items  = [e for e in MODEL_CATALOG if e["category"] == "whisper"]
        if api_only:
            whisper_items = [e for e in whisper_items if e["name"] in API_WHISPER_MODELS]
            parakeet_items = []
        else:
            parakeet_items = [e for e in MODEL_CATALOG if e["category"] == "parakeet"]

        def _add_header(text):
            h = QStandardItem(text)
            h.setFlags(
                h.flags()
                & ~QtCore.Qt.ItemFlag.ItemIsSelectable
                & ~QtCore.Qt.ItemFlag.ItemIsEnabled
            )
            font = QFont()
            font.setItalic(True)
            h.setFont(font)
            std_model.appendRow(h)

        if whisper_items:
            _add_header("── Whisper ──")
            for entry in whisper_items:
                std_model.appendRow(QStandardItem(entry["name"]))

        if parakeet_items:
            _add_header("── Parakeet ──")
            for entry in parakeet_items:
                std_model.appendRow(QStandardItem(entry["name"]))

    # ── Model / backend change handlers ──────────────────────────────────

    def _on_model_changed(self, model_name: str):
        name = model_name.strip()
        is_parakeet = name.startswith("parakeet-")

        entry = next((e for e in MODEL_CATALOG if e["name"] == name), None)
        model_device_support = entry["device"] if entry else "any"

        if is_parakeet:
            # Parakeet is always local – lock backend to Local
            self._backend_local.setChecked(True)
            self._backend_local.setEnabled(False)
            self._backend_api.setEnabled(False)
        else:
            self._backend_local.setEnabled(True)
            self._backend_api.setEnabled(True)

        self._update_server_and_device(model_device_support)

    def _on_backend_changed(self):
        self._refresh_model_list_for_backend()
        name = self._model.currentText().strip()
        entry = next((e for e in MODEL_CATALOG if e["name"] == name), None)
        model_device_support = entry["device"] if entry else "any"
        self._update_server_and_device(model_device_support)
        self._refresh_test_clip_state()

    def _on_speed_mode_changed(self, _index: int):
        if not callable(self._speed_mode_setter):
            return
        mode = str(self._speed_mode.currentData() or "disabled")
        try:
            self._speed_mode_setter(mode)
        except Exception:
            pass

    def _update_server_and_device(self, model_device_support: str):
        is_parakeet = self._model.currentText().strip().startswith("parakeet-")
        using_api = self._backend_api.isChecked()

        # Server fields enabled only when using external API
        for w in (self._api_url, self._endpoint, self._test_btn,
                  self._server_label, self._endpoint_label):
            w.setEnabled(using_api)

        # Device availability is driven by model capability.
        if model_device_support == "cpu":
            self._device_cpu.setChecked(True)
            self._device_cpu.setEnabled(True)
            self._device_gpu.setEnabled(False)
        elif model_device_support == "gpu":
            self._device_gpu.setChecked(True)
            self._device_cpu.setEnabled(False)
            self._device_gpu.setEnabled(True)
        else:  # "any" – both available, keep user preference
            self._device_cpu.setEnabled(True)
            self._device_gpu.setEnabled(True)
        self._refresh_test_clip_state()

    def _current_test_options(self) -> dict:
        mic_idx = self._mic.currentIndex()
        mic_index = self._mic_indices[mic_idx] if 0 <= mic_idx < len(self._mic_indices) else None
        return {
            "model": self._model.currentText().strip(),
            "whisper_backend": "api" if self._backend_api.isChecked() else "local",
            "model_device": "cpu" if self._device_cpu.isChecked() else "gpu",
            "portable_models": self._portable_check.isChecked(),
            "api_url": self._api_url.text().strip().rstrip("/"),
            "api_endpoint": "/" + self._endpoint.text().strip("/"),
            "language": self._language.currentText().strip(),
            "microphone_index": mic_index,
            "sample_rate": 16000,
            "output_capture_source": str(self._output_source.currentData() or "auto"),
            "input_file_path": self._input_file_path.text().strip(),
        }

    def _populate_output_sources(self):
        if self._output_source.count() > 0:
            preferred = str(self._output_source.currentData() or "auto")
        else:
            preferred = str(self._settings.get("output_capture_source", "auto") or "auto")
        log.info("Settings: refreshing output capture sources")
        self._output_source.clear()
        self._output_source.addItem("Auto (System Audio)", "auto")
        if not callable(self._test_list_output_sources_callback):
            log.warning("Settings: output source callback is not available")
            self._output_source.setEnabled(False)
            return
        try:
            sources = self._test_list_output_sources_callback() or []
        except Exception:
            sources = []
        log.info("Settings: output capture sources found: %d", len(sources))
        if not sources:
            self._output_source.addItem("No loopback source found", "none")
            self._output_source.setEnabled(False)
            self._refresh_test_clip_state()
            return
        for source_id, label in sources:
            self._output_source.addItem(str(label), str(source_id))
        preferred_idx = self._output_source.findData(preferred)
        if preferred_idx >= 0:
            self._output_source.setCurrentIndex(preferred_idx)
        self._update_output_source_popup_width()
        self._output_source.setEnabled(True)
        self._refresh_test_clip_state()

    def _update_output_source_popup_width(self):
        if self._output_source is None:
            return
        fm = self._output_source.fontMetrics()
        widest = 0
        for i in range(self._output_source.count()):
            widest = max(widest, fm.horizontalAdvance(self._output_source.itemText(i)))
        # Keep control compact while allowing a readable popup list.
        self._output_source.set_popup_min_width(min(700, max(360, widest + 42)))

    def _refresh_test_clip_state(self):
        can_record = callable(self._test_start_record_callback) and callable(self._test_stop_record_callback)
        can_output = callable(self._test_start_output_callback) and callable(self._test_stop_output_callback)
        source_ok = self._output_source.isEnabled() and self._output_source.count() > 0
        if hasattr(self, "_record_test_btn") and self._record_test_btn is not None:
            self._record_test_btn.setEnabled(can_record and not self._is_output_capturing)
            self._record_test_btn.setText("Stop" if self._is_test_recording else "Microphone")
        if hasattr(self, "_use_output_btn") and self._use_output_btn is not None:
            self._use_output_btn.setEnabled(can_output and source_ok and not self._is_test_recording)
            self._use_output_btn.setText("Stop" if self._is_output_capturing else "System Audio")
        has_clip = False
        if callable(self._test_has_recorded_callback):
            try:
                has_clip = bool(self._test_has_recorded_callback(self._current_test_options()))
            except Exception:
                has_clip = False
        if hasattr(self, "_use_recorded_btn") and self._use_recorded_btn is not None:
            self._use_recorded_btn.setEnabled(has_clip and not self._is_test_recording and not self._is_output_capturing)

    def _toggle_record_test_clip(self):
        opts = self._current_test_options()
        if not self._is_test_recording:
            if not callable(self._test_start_record_callback):
                return
            ok, msg = self._test_start_record_callback(opts)
            if ok:
                self._is_test_recording = True
            else:
                log.error("Settings: record test start failed: %s", msg)
            self._refresh_test_clip_state()
            return
        if not callable(self._test_stop_record_callback):
            return
        ok, msg = self._test_stop_record_callback(opts)
        self._is_test_recording = False
        if not ok:
            log.error("Settings: record test stop failed: %s", msg)
        self._refresh_test_clip_state()

    def _toggle_output_capture(self):
        opts = self._current_test_options()
        log.info(
            "Settings: System Audio clicked (capturing=%s source=%s)",
            self._is_output_capturing,
            opts.get("output_capture_source", "auto"),
        )
        if not self._is_output_capturing:
            if not callable(self._test_start_output_callback):
                log.error("Settings: start output callback missing")
                return
            ok, msg = self._test_start_output_callback(opts)
            if ok:
                self._is_output_capturing = True
                log.info("Settings: output capture started")
            else:
                log.error("Settings: output capture start failed: %s", msg)
            self._refresh_test_clip_state()
            return
        if not callable(self._test_stop_output_callback):
            log.error("Settings: stop output callback missing")
            return
        ok, msg = self._test_stop_output_callback(opts)
        self._is_output_capturing = False
        if not ok:
            log.error("Settings: output capture stop failed: %s", msg)
        else:
            log.info("Settings: output capture stopped and clip saved")
        self._refresh_test_clip_state()

    def _use_recorded_clip(self):
        if not callable(self._test_use_recorded_callback):
            return
        opts = self._current_test_options()
        self._run_use_recorded_async(opts)

    def _run_use_recorded_async(self, opts: dict):
        log.info("Settings: use recorded requested")
        if self._record_test_btn is not None:
            self._record_test_btn.setEnabled(False)
        if self._use_output_btn is not None:
            self._use_output_btn.setEnabled(False)
        if self._use_recorded_btn is not None:
            self._use_recorded_btn.setEnabled(False)

        def _worker():
            try:
                ok, msg = self._test_use_recorded_callback(opts)
                if not ok:
                    log.error("Settings: use recorded failed: %s", msg)
                else:
                    log.info("Settings: use recorded completed: %s", msg)
            finally:
                self._ui.call_soon(self._refresh_test_clip_state)

        threading.Thread(target=_worker, daemon=True).start()

    def _show_recorded_context_menu(self, source_btn, pos):
        if self._window is None:
            return
        global_pos = source_btn.mapToGlobal(pos) if isinstance(source_btn, QtWidgets.QWidget) else self._window.mapToGlobal(pos)
        menu = QtWidgets.QMenu(self._window)
        delete_action = menu.addAction("Delete recorded audio")
        chosen = menu.exec(global_pos)
        if chosen != delete_action:
            return
        if not callable(self._test_delete_recorded_callback):
            return
        ok, msg = self._test_delete_recorded_callback(self._current_test_options())
        if not ok:
            log.error("Settings: delete recorded audio failed: %s", msg)
        self._refresh_test_clip_state()

    def set_test_caption_text(self, text: str):
        self._last_test_caption = str(text or "")

        def _apply():
            if not hasattr(self, "_testing_target") or self._testing_target is None:
                return
            self._testing_target.setPlainText(self._last_test_caption)
            cursor = self._testing_target.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._testing_target.setTextCursor(cursor)

        self._ui.call_soon(_apply)

    def _show_testing_target_menu(self, pos):
        if not hasattr(self, "_testing_target") or self._testing_target is None:
            return
        menu = QtWidgets.QMenu(self._window)
        copy_action = menu.addAction("Copy")
        chosen = menu.exec(self._testing_target.mapToGlobal(pos))
        if chosen == copy_action:
            self._testing_target.copy()

    def _pick_input_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Select Audio File",
            "",
            "Audio Files (*.wav *.mp3)",
        )
        if path:
            self._set_input_file(path)

    def _set_input_file(self, path: str):
        if not callable(self._test_set_input_file_callback):
            return
        ok, msg = self._test_set_input_file_callback(path, self._current_test_options())
        if ok:
            self._input_file_path.setText(path)
            self._refresh_test_clip_state()
        else:
            log.error("Settings: input file import failed: %s", msg)

    def _refresh_model_list_for_backend(self):
        combo_model = self._model.model()
        if not isinstance(combo_model, QStandardItemModel):
            return
        current = self._model.currentText().strip()
        self._model.blockSignals(True)
        self._populate_model_items(combo_model, api_only=bool(self._backend_api.isChecked()))
        first_valid = -1
        selected = -1
        for i in range(combo_model.rowCount()):
            item = combo_model.item(i)
            if item is None:
                continue
            if item.isEnabled() and item.isSelectable():
                if first_valid == -1:
                    first_valid = i
                if item.text().strip() == current:
                    selected = i
        self._model.setCurrentIndex(selected if selected >= 0 else first_valid)
        self._model.blockSignals(False)

    # ── Standard helpers ──────────────────────────────────────────────────

    def _wrap(self, layout: QtWidgets.QLayout) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        widget.setLayout(layout)
        return widget

    def _normalize_control_heights(self):
        height = 28
        controls = [
            self._api_url,
            self._endpoint,
            self._model,
            self._language,
            self._theme,
            self._input_file_path,
            self._output_source,
            self._hotkey,
            self._system_audio_hotkey,
            self._mic,
            self._insert_method,
            self._speed_mode,
            self._notification_anchor,
            self._sensitivity,
            self._typing_speed,
            self._notify_font_size,
            self._notify_width,
            self._notify_height,
            self._notify_fade_in_duration,
            self._notify_duration,
            self._notify_fade_duration,
        ]
        for widget in controls:
            if isinstance(widget, QtWidgets.QWidget):
                widget.setFixedHeight(height)

    def _bind_dirty_tracking(self):
        widgets = [
            self._api_url,
            self._endpoint,
            self._model,
            self._language,
            self._hotkey,
            self._system_audio_hotkey,
            self._mode_toggle,
            self._mode_hold,
            self._suppress_hotkey,
            self._mic,
            self._sensitivity,
            self._out_clipboard,
            self._out_insert,
            self._insert_method,
            self._typing_speed,
            self._notify,
            self._notify_empty,
            self._notify_reject,
            self._show_recording_indicator,
            self._show_transcribing_notification,
            self._speed_mode,
            self._notify_width,
            self._notify_height,
            self._notify_fade_in_duration,
            self._notify_duration,
            self._notify_fade_duration,
            self._autostart,
            self._theme,
            self._notify_font_size,
            self._notification_anchor,
            self._backend_local,
            self._backend_api,
            self._device_cpu,
            self._device_gpu,
            self._portable_check,
            self._output_source,
            self._input_file_path,
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

    def _pick_system_audio_hotkey(self):
        dlg = HotkeyPickerDialog(self._system_audio_hotkey.text().strip(), parent=self._window)
        result = dlg.get()
        if result:
            self._system_audio_hotkey.setText(result)

    def _on_anchor_changed_preview(self, _index: int):
        self._show_anchor_preview(cycle=False)

    def _on_anchor_test_button(self):
        self._show_anchor_preview(cycle=True)

    def _show_anchor_preview(self, cycle: bool):
        if not callable(self._notification_preview_callback):
            return
        anchor = str(self._notification_anchor.currentData() or "bottom_right")
        lengths = [50, 200, 400, 800]
        target_len = lengths[self._anchor_test_index % len(lengths)]
        self._anchor_test_index += 1
        body = self._build_lorem(target_len)
        message = f"Test Notification ({target_len} chars)\n{body}"
        badge = f"{(target_len / 1.0):.1f} cps | 1.00 s"
        self._notification_preview_callback(
            message=message,
            anchor=anchor,
            duration_ms=5000,
            font_size=int(self._notify_font_size.value()),
            width=int(self._notify_width.value()),
            max_height=int(self._notify_height.value()),
            fade_in_ms=int(float(self._notify_fade_in_duration.value()) * 1000.0),
            fade_out_ms=int(float(self._notify_fade_duration.value()) * 1000.0),
            speed_badge=badge,
            show_dot=True,
        )

    def _build_lorem(self, target_len: int) -> str:
        words = (
            "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore magna aliqua"
        ).split()
        out = []
        while len(" ".join(out)) < max(10, int(target_len)):
            out.append(random.choice(words))
        text = " ".join(out)
        return text[:max(10, int(target_len))]

    def _test_connection(self):
        url = self._api_url.text().strip().rstrip("/")
        if not url:
            self._show_test_result(False, "Enter a URL first.")
            return
        self._test_btn.setEnabled(False)
        ok, msg = ping(url)
        self._show_test_result(ok, msg)

    def _show_test_result(self, ok: bool, msg: str):
        if self._test_btn is not None:
            self._test_btn.setEnabled(True)
            self._test_btn.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        if callable(self._notification_preview_callback):
            anchor = str(self._notification_anchor.currentData() or "bottom_right")
            try:
                font_size = int(self._notify_font_size.value())
                width = int(self._notify_width.value())
                max_height = int(self._notify_height.value())
                fade_in_ms = int(float(self._notify_fade_in_duration.value()) * 1000.0)
                fade_out_ms = int(float(self._notify_fade_duration.value()) * 1000.0)
            except Exception:
                font_size, width, max_height, fade_in_ms, fade_out_ms = 11, 390, 0, 100, 220
            self._notification_preview_callback(
                (f"{'Connection OK' if ok else 'Connection Failed'}: {str(msg or '').strip()}"),
                anchor,
                2200,
                font_size,
                width,
                max_height,
                max(0, fade_in_ms),
                max(0, fade_out_ms),
                speed_badge="",
                show_dot=False,
            )

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
            "system_audio_hotkey": self._system_audio_hotkey.text().strip().lower(),
            "hotkey_mode": "hold" if self._mode_hold.isChecked() else "toggle",
            "suppress_hotkey": self._suppress_hotkey.isChecked(),
            "microphone_index": mic_index,
            "microphone_name": mic_name,
            "microphone_sensitivity_enabled": int(self._sensitivity.value()) > 0,
            "microphone_sensitivity": int(self._sensitivity.value()),
            "output_clipboard": self._out_clipboard.isChecked(),
            "output_insert": self._out_insert.isChecked(),
            "output_insert_method": self._insert_method.currentText(),
            "typing_speed": int(self._typing_speed.value()),
            "show_notification": self._notify.isChecked(),
            "show_empty_notification": self._notify_empty.isChecked(),
            "show_sensitivity_reject_notification": self._notify_reject.isChecked(),
            "show_recording_indicator": self._show_recording_indicator.isChecked(),
            "show_transcribing_notification": self._show_transcribing_notification.isChecked(),
            "notification_font_size": int(self._notify_font_size.value()),
            "notification_width": int(self._notify_width.value()),
            "notification_height": int(self._notify_height.value()),
            "notification_anchor": str(self._notification_anchor.currentData() or "bottom_right"),
            "notification_fade_in_duration_s": float(self._notify_fade_in_duration.value()),
            "notification_duration_s": float(self._notify_duration.value()),
            "notification_fade_duration_s": float(self._notify_fade_duration.value()),
            "autostart": self._autostart.isChecked(),
            "app_theme": normalize_theme(self._theme.currentText()),
            "whisper_backend": "api" if self._backend_api.isChecked() else "local",
            "model_device": "cpu" if self._device_cpu.isChecked() else "gpu",
            "portable_models": self._portable_check.isChecked(),
            "output_capture_source": str(self._output_source.currentData() or "auto"),
            "test_input_file": self._input_file_path.text().strip(),
            "speed_stats_mode": str(self._speed_mode.currentData() or "disabled"),
        }

        self._on_save(new_settings)
        self._dirty = False
        self._apply_btn.setEnabled(False)

        # Apply selected theme immediately in this open dialog too.
        self._window.setStyleSheet(settings_stylesheet(normalize_theme(self._theme.currentText())))
