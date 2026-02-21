"""
Local inference engine for Parakeet (onnx-asr) and Whisper (faster-whisper) models.
"""

import functools
import json
import os
import subprocess
import sys
import tempfile
import time

from logger import log

ONNX_MODEL_IDS = {
    "parakeet-tdt-0.6b-v3": "nemo-parakeet-tdt-0.6b-v3",
    "parakeet-tdt-0.6b-v3-fp32": "istupakov/parakeet-tdt-0.6b-v3-onnx",
}

FASTER_WHISPER_IDS = {
    "whisper-tiny": "tiny",
    "whisper-tiny-en": "tiny.en",
    "whisper-base": "base",
    "whisper-base-en": "base.en",
    "whisper-small": "small",
    "whisper-small-en": "small.en",
    "whisper-medium": "medium",
    "whisper-medium-en": "medium.en",
    "whisper-large": "large-v2",
    "whisper-large-v1": "large-v1",
    "whisper-large-v2": "large-v2",
    "whisper-large-v3": "large-v3",
    "whisper-turbo": "turbo",
}


def is_parakeet_model(name: str) -> bool:
    return name.strip().startswith("parakeet-")


def is_whisper_model(name: str) -> bool:
    return name.strip().startswith("whisper-")


@functools.lru_cache(maxsize=1)
def _cuda_available() -> bool:
    """Fast GPU presence check via nvidia-smi. Never loads CUDA DLLs."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


@functools.lru_cache(maxsize=1)
def _ctranslate2_cuda_ok() -> bool:
    """
    Probe CTranslate2 CUDA support in a child process.
    If CTranslate2 crashes with an access violation, only the child process dies.
    """
    if not _cuda_available():
        return False
    try:
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                "import ctranslate2; "
                "n = ctranslate2.get_cuda_device_count(); "
                "exit(0 if n > 0 else 1)",
            ],
            capture_output=True,
            timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


@functools.lru_cache(maxsize=32)
def _whisper_cuda_load_ok(model_id: str, compute_type: str) -> bool:
    """
    Probe faster-whisper model load on CUDA in a child process.
    If native code crashes, only the child dies and we can safely fall back.
    """
    try:
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from faster_whisper import WhisperModel; "
                    f"WhisperModel({model_id!r}, device='cuda', compute_type={compute_type!r}); "
                    "exit(0)"
                ),
            ],
            capture_output=True,
            timeout=120,
        )
        return r.returncode == 0
    except Exception:
        return False


class LocalInferenceEngine:
    def __init__(self, settings):
        self._settings = settings
        self._model = None
        self._loaded_name = None
        self._loaded_device = None
        self._warmed_models: set[tuple[str, str, str]] = set()
        self._ready_tokens: set[str] = self._load_ready_tokens()
        self._probe_cache: dict[str, bool] = {}

    def transcribe(self, wav_bytes: bytes) -> str:
        model_name = self._settings.get("model", "")
        device = self._settings.get("model_device", "gpu")
        if is_parakeet_model(model_name):
            return self._transcribe_parakeet(wav_bytes, model_name, device)
        return self._transcribe_whisper(wav_bytes, model_name, device)

    def unload(self) -> None:
        self._model = None
        self._loaded_name = None
        self._loaded_device = None
        self._warmed_models.clear()
        self._probe_cache.clear()

    def is_warm(self, model_name: str, device: str) -> bool:
        if is_parakeet_model(model_name):
            token = self._model_token("parakeet", model_name)
            if self._is_ready_token(token):
                return True
            ok = self._probe_local_cache("parakeet", model_name)
            if ok:
                self._mark_ready("parakeet", model_name)
            return ok
        if is_whisper_model(model_name):
            token = self._model_token("whisper", model_name)
            if self._is_ready_token(token):
                return True
            ok = self._probe_local_cache("whisper", model_name)
            if ok:
                self._mark_ready("whisper", model_name)
            return ok
        return True

    def is_ready_cached(self, model_name: str) -> bool:
        if is_parakeet_model(model_name):
            return self._is_ready_token(self._model_token("parakeet", model_name))
        if is_whisper_model(model_name):
            return self._is_ready_token(self._model_token("whisper", model_name))
        return True

    # Whisper (faster-whisper)
    def _transcribe_whisper(self, wav_bytes: bytes, model_name: str, device: str) -> str:
        if model_name not in FASTER_WHISPER_IDS:
            known = ", ".join(FASTER_WHISPER_IDS)
            raise ValueError(f"Unknown Whisper model '{model_name}'. Known models: {known}")

        self._configure_cache()
        fw_id = FASTER_WHISPER_IDS[model_name]
        hw_device, compute_type = self._resolve_whisper_runtime(fw_id, device)
        cold_start = not self.is_warm(model_name, device)
        if cold_start:
            log.info("Whisper warmup/download start: model=%s device=%s", model_name, hw_device)

        started = time.perf_counter()
        try:
            text = self._infer_whisper_subprocess(wav_bytes, fw_id, hw_device, compute_type)
            self._warmed_models.add(("whisper", model_name, device))
            self._mark_ready("whisper", model_name)
            return text
        except RuntimeError as exc:
            if hw_device == "cuda":
                log.warning("Whisper CUDA subprocess failed (%s); retrying on CPU.", exc)
                text = self._infer_whisper_subprocess(wav_bytes, fw_id, "cpu", "int8")
                self._warmed_models.add(("whisper", model_name, device))
                self._mark_ready("whisper", model_name)
                return text
            raise
        finally:
            if cold_start:
                elapsed = time.perf_counter() - started
                log.info("Whisper warmup/download finished in %.1fs", elapsed)

    def _resolve_whisper_runtime(self, fw_id: str, device: str) -> tuple[str, str]:
        use_cuda = device == "gpu" and _ctranslate2_cuda_ok()
        if use_cuda and not _whisper_cuda_load_ok(fw_id, "float16"):
            use_cuda = False
        if device == "gpu" and not use_cuda:
            log.warning(
                "GPU mode requested, but CUDA probe failed; falling back to CPU "
                "for faster-whisper to avoid a native crash."
            )
        return ("cuda", "float16") if use_cuda else ("cpu", "int8")

    def _infer_whisper_subprocess(
        self,
        wav_bytes: bytes,
        model_id: str,
        hw_device: str,
        compute_type: str,
    ) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name
        try:
            code = (
                "import sys\n"
                "from faster_whisper import WhisperModel\n"
                "wav_path, model_id, hw_device, compute_type = sys.argv[1:5]\n"
                "model = WhisperModel(model_id, device=hw_device, compute_type=compute_type)\n"
                "segments, _ = model.transcribe(wav_path)\n"
                "print(''.join(seg.text for seg in segments).strip())\n"
            )
            result = subprocess.run(
                [sys.executable, "-c", code, tmp_path, model_id, hw_device, compute_type],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                err = (result.stderr or "").strip()
                out = (result.stdout or "").strip()
                detail = err or out or f"exit code {result.returncode}"
                raise RuntimeError(detail)
            return (result.stdout or "").rstrip("\r\n")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # Parakeet (onnx-asr)
    def _transcribe_parakeet(self, wav_bytes: bytes, model_name: str, device: str) -> str:
        if model_name not in ONNX_MODEL_IDS:
            known = ", ".join(ONNX_MODEL_IDS)
            raise ValueError(f"Unknown Parakeet model '{model_name}'. Known models: {known}")

        self._configure_cache()
        onnx_id = ONNX_MODEL_IDS[model_name]
        run_device = self._resolve_parakeet_runtime(device)
        cold_start = not self.is_warm(model_name, device)
        if cold_start:
            log.info("Parakeet warmup/download start: model=%s device=%s", model_name, run_device)

        started = time.perf_counter()
        try:
            text = self._infer_parakeet_subprocess(wav_bytes, onnx_id, run_device)
            self._warmed_models.add(("parakeet", model_name, device))
            self._mark_ready("parakeet", model_name)
            return text
        except RuntimeError as exc:
            if run_device == "gpu":
                log.warning("Parakeet GPU subprocess failed (%s); retrying on CPU.", exc)
                text = self._infer_parakeet_subprocess(wav_bytes, onnx_id, "cpu")
                self._warmed_models.add(("parakeet", model_name, device))
                self._mark_ready("parakeet", model_name)
                return text
            raise
        finally:
            if cold_start:
                elapsed = time.perf_counter() - started
                log.info("Parakeet warmup/download finished in %.1fs", elapsed)

    def _resolve_parakeet_runtime(self, device: str) -> str:
        use_cuda = device == "gpu" and _cuda_available()
        if device == "gpu" and not use_cuda:
            log.warning(
                "GPU mode requested, but CUDA probe failed; falling back to CPU "
                "for Parakeet to avoid a native crash."
            )
        return "gpu" if use_cuda else "cpu"

    def _infer_parakeet_subprocess(self, wav_bytes: bytes, onnx_id: str, run_device: str) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name
        try:
            code = (
                "import sys\n"
                "import onnx_asr\n"
                "wav_path, model_id = sys.argv[1:3]\n"
                "model = onnx_asr.load_model(model_id)\n"
                "result = model.recognize(wav_path)\n"
                "if isinstance(result, str):\n"
                "    text = result\n"
                "elif isinstance(result, list) and result:\n"
                "    text = str(result[0])\n"
                "elif isinstance(result, dict):\n"
                "    if 'text' in result:\n"
                "        text = result['text']\n"
                "    elif 'segments' in result:\n"
                "        text = ' '.join(s.get('text', '') for s in result['segments'])\n"
                "    else:\n"
                "        text = str(result)\n"
                "else:\n"
                "    text = str(result)\n"
                "print(text)\n"
            )
            env = os.environ.copy()
            if run_device == "cpu":
                env["CUDA_VISIBLE_DEVICES"] = "-1"
            else:
                env.pop("CUDA_VISIBLE_DEVICES", None)
            result = subprocess.run(
                [sys.executable, "-c", code, tmp_path, onnx_id],
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
            )
            if result.returncode != 0:
                err = (result.stderr or "").strip()
                out = (result.stdout or "").strip()
                detail = err or out or f"exit code {result.returncode}"
                raise RuntimeError(detail)
            return (result.stdout or "").rstrip("\r\n")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _configure_cache(self):
        if self._settings.get("portable_models", False):
            if getattr(sys, "frozen", False):
                base = os.path.dirname(sys.executable)
            else:
                base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            models_dir = os.path.join(base, "models")
            os.makedirs(models_dir, exist_ok=True)
            os.environ["HF_HOME"] = models_dir
        else:
            os.environ.pop("HF_HOME", None)

    def _cache_scope(self) -> str:
        return "portable" if bool(self._settings.get("portable_models", False)) else "shared"

    def _model_token(self, kind: str, model_name: str) -> str:
        return f"{kind}|{model_name}|{self._cache_scope()}"

    def _is_ready_token(self, token: str) -> bool:
        return token in self._ready_tokens

    def _mark_ready(self, kind: str, model_name: str) -> None:
        token = self._model_token(kind, model_name)
        if token in self._ready_tokens:
            return
        self._ready_tokens.add(token)
        self._persist_ready_tokens()

    def _load_ready_tokens(self) -> set[str]:
        raw = self._settings.get("local_ready_models", "")
        if not raw:
            return set()
        try:
            data = json.loads(str(raw))
            if isinstance(data, list):
                return {str(x) for x in data if isinstance(x, str)}
        except Exception:
            pass
        return set()

    def _persist_ready_tokens(self) -> None:
        if not hasattr(self._settings, "update"):
            return
        try:
            payload = json.dumps(sorted(self._ready_tokens))
            self._settings.update({"local_ready_models": payload})
        except Exception:
            pass

    def _probe_local_cache(self, kind: str, model_name: str) -> bool:
        token = self._model_token(kind, model_name)
        if token in self._probe_cache:
            return self._probe_cache[token]

        if kind == "whisper":
            fw_id = FASTER_WHISPER_IDS.get(model_name)
            if not fw_id:
                self._probe_cache[token] = False
                return False
            code = (
                "import os,sys\n"
                "from faster_whisper import WhisperModel\n"
                "model_id = sys.argv[1]\n"
                "root = os.environ.get('HF_HOME') or None\n"
                "WhisperModel(model_id, device='cpu', compute_type='int8', local_files_only=True, download_root=root)\n"
                "print('ok')\n"
            )
            env = os.environ.copy()
            result = subprocess.run(
                [sys.executable, "-c", code, fw_id],
                capture_output=True,
                text=True,
                timeout=25,
                env=env,
            )
            ok = result.returncode == 0
            self._probe_cache[token] = ok
            return ok

        if kind == "parakeet":
            onnx_id = ONNX_MODEL_IDS.get(model_name)
            if not onnx_id:
                self._probe_cache[token] = False
                return False
            code = (
                "import sys\n"
                "import onnx_asr\n"
                "model_id = sys.argv[1]\n"
                "onnx_asr.load_model(model_id)\n"
                "print('ok')\n"
            )
            env = os.environ.copy()
            env["HF_HUB_OFFLINE"] = "1"
            env["TRANSFORMERS_OFFLINE"] = "1"
            result = subprocess.run(
                [sys.executable, "-c", code, onnx_id],
                capture_output=True,
                text=True,
                timeout=25,
                env=env,
            )
            ok = result.returncode == 0
            self._probe_cache[token] = ok
            return ok

        self._probe_cache[token] = False
        return False
