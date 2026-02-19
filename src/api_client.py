import io
import requests

from logger import log


def ping(base_url: str, timeout: int = 5) -> tuple[bool, str]:
    """Check whether the Whisper server is reachable. Returns (ok, message)."""
    base_url = base_url.rstrip("/")
    for path in ("/health", "/", "/docs"):
        url = base_url + path
        log.debug("ping: GET %s", url)
        try:
            r = requests.get(url, timeout=timeout)
            msg = f"OK  ({r.status_code})  —  {url}"
            log.info("ping: %s", msg)
            return True, msg
        except requests.exceptions.ConnectionError:
            log.warning("ping: connection refused — %s", url)
            continue
        except requests.exceptions.Timeout:
            msg = f"Timeout after {timeout}s  —  {url}"
            log.warning("ping: %s", msg)
            return False, msg
        except Exception as exc:
            log.error("ping: unexpected error — %s", exc)
            return False, str(exc)

    msg = f"Connection refused — is the server running?\nTried: {base_url}"
    log.error("ping: %s", msg)
    return False, msg


class WhisperClient:
    """
    Sends audio to an OpenAI-compatible whisper endpoint.

    Expected server:  POST /v1/audio/transcriptions
    Required fields:  file=<audio>, model=<name>
    Optional fields:  language, response_format
    """

    def __init__(self, settings_manager):
        self._settings = settings_manager

    def transcribe(self, wav_bytes: bytes) -> str:
        base_url = self._settings.get("api_url", "http://localhost:9876").rstrip("/")
        endpoint = self._settings.get("api_endpoint", "/v1/audio/transcriptions").lstrip("/")
        language = self._settings.get("language", "").strip()
        model = self._settings.get("model", "whisper-1").strip() or "whisper-1"

        url = f"{base_url}/{endpoint}"

        form_data: dict[str, str] = {
            "model": model,
            "response_format": "json",
        }
        if language and language.lower() != "auto":
            form_data["language"] = language

        log.info(
            "Transcribe  POST %s  form=%s  audio=%d bytes",
            url, form_data, len(wav_bytes),
        )

        files = {"file": ("recording.wav", io.BytesIO(wav_bytes), "audio/wav")}

        try:
            response = requests.post(url, data=form_data, files=files, timeout=60)
            log.info(
                "Response  status=%d  size=%d bytes",
                response.status_code, len(response.content),
            )
            log.debug("Response body: %s", response.text[:500])
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            log.error("HTTP error: %s", exc)
            body = exc.response.text[:500] if exc.response is not None else "n/a"
            log.error("Response body was: %s", body)
            raise
        except requests.exceptions.ConnectionError as exc:
            log.error("Connection error — is the server running? %s", exc)
            raise
        except requests.exceptions.Timeout:
            log.error("Request timed out after 60s")
            raise

        text = self._extract_text(response)
        log.info("Transcription result: %r", text)
        return text

    # ------------------------------------------------------------------

    def _extract_text(self, response) -> str:
        try:
            data = response.json()
            log.debug("Parsed JSON response: %s", data)
        except Exception:
            log.debug("Response is plain text: %s", response.text[:200])
            return response.text.strip()

        if isinstance(data, str):
            return data.strip()

        if isinstance(data, dict):
            for key in ("text", "transcript", "transcription"):
                if key in data:
                    return str(data[key]).strip()
            if "results" in data and isinstance(data["results"], dict):
                inner = data["results"]
                for key in ("transcription", "text"):
                    if key in inner:
                        return str(inner[key]).strip()

        log.warning("Could not find text field in response, returning raw: %s", data)
        return str(data).strip()
