import io
import threading
import wave

import numpy as np
import sounddevice as sd

from logger import log


class AudioRecorder:
    def __init__(self, settings_manager):
        self._settings = settings_manager
        self._recording = False
        self._frames = []
        self._stream = None
        self._lock = threading.Lock()
        self._last_capture_info = {
            "rms": None,
            "threshold": None,
            "sensitivity_enabled": False,
            "rejected_by_threshold": False,
        }

    def get_devices(self) -> list[tuple[int | None, str]]:
        devices = [(-1, "Default")]
        try:
            for i, dev in enumerate(sd.query_devices()):
                if dev["max_input_channels"] > 0:
                    devices.append((i, f"{i}: {dev['name']}"))
        except Exception as exc:
            log.error("Failed to enumerate audio devices: %s", exc)
        return devices

    def start(self):
        if self._recording:
            log.warning("start() called while already recording - ignored")
            return

        sample_rate = self._settings.get("sample_rate", 16000)
        device_index = self._settings.get("microphone_index", None)
        if device_index == -1:
            device_index = None

        device_name = self._settings.get("microphone_name", "Default")
        log.info(
            "Recording START - device=%r index=%s sample_rate=%d Hz",
            device_name,
            device_index,
            sample_rate,
        )

        self._frames = []
        self._recording = True
        self._last_capture_info = {
            "rms": None,
            "threshold": self._get_sensitivity(),
            "sensitivity_enabled": bool(self._settings.get("microphone_sensitivity_enabled", False)),
            "rejected_by_threshold": False,
        }

        def _callback(indata, frames, time_info, status):
            if status:
                log.warning("sounddevice status: %s", status)
            if self._recording:
                with self._lock:
                    self._frames.append(indata.copy())

        try:
            self._stream = sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                device=device_index,
                callback=_callback,
            )
            self._stream.start()
            log.debug("Audio stream opened successfully")
        except Exception as exc:
            self._recording = False
            log.error("Failed to open audio stream: %s", exc)
            raise

    def stop(self) -> bytes | None:
        if not self._recording:
            log.warning("stop() called while not recording - ignored")
            return None

        self._recording = False

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        with self._lock:
            frame_count = len(self._frames)
            if not self._frames:
                log.warning("Recording stopped but no audio frames captured")
                return None
            audio = np.concatenate(self._frames, axis=0)

        sample_rate = self._settings.get("sample_rate", 16000)
        duration = len(audio) / sample_rate
        rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float32)))))
        sensitivity_enabled = bool(self._settings.get("microphone_sensitivity_enabled", False))
        threshold = self._get_sensitivity()

        log.info("Recording STOP - %d frames, %.2f seconds of audio captured", frame_count, duration)
        log.info("Recording level - rms=%.2f threshold=%d enabled=%s", rms, threshold, sensitivity_enabled)

        self._last_capture_info = {
            "rms": rms,
            "threshold": threshold,
            "sensitivity_enabled": sensitivity_enabled,
            "rejected_by_threshold": bool(sensitivity_enabled and rms < threshold),
        }

        if sensitivity_enabled and rms < threshold:
            log.info("Recording rejected by sensitivity threshold")
            return None

        wav_bytes = self._to_wav(audio)
        log.debug("WAV buffer size: %d bytes", len(wav_bytes))
        return wav_bytes

    def _to_wav(self, audio: np.ndarray) -> bytes:
        sample_rate = self._settings.get("sample_rate", 16000)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio.tobytes())
        buf.seek(0)
        return buf.read()

    def _get_sensitivity(self) -> int:
        try:
            threshold = int(self._settings.get("microphone_sensitivity", 120))
        except (TypeError, ValueError):
            threshold = 120
        return max(1, min(threshold, 4000))

    def get_last_capture_info(self) -> dict:
        return dict(self._last_capture_info)
