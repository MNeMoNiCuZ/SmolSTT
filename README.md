# SmolSTT

SmolSTT is a minimal global push-to-talk speech-to-text desktop app for Windows.
It can transcribe from microphone, system audio loopback, or test audio files.
You can run models locally (Whisper/Parakeet) or against an OpenAI-compatible API,
then output text to clipboard and/or insert it at the active cursor.

![STT01](https://github.com/user-attachments/assets/9dca2ccd-a4e9-4d86-aadb-cc565987088e)

<img width="981" height="806" alt="image" src="https://github.com/user-attachments/assets/fc8a2dd0-8879-4936-b493-bf4b270c5596" />


## Features

- Global hotkeys
  - Microphone hotkey (`toggle` or `hold`)
  - Optional separate system-audio hotkey
  - Optional hotkey suppression toggle
- Input modes
  - Microphone recording
  - System audio capture (WASAPI loopback / PyAudioWPatch path on Windows)
  - Test file input (`.wav` / `.mp3`) via drag/drop
- Backends
  - Local inference: Whisper (`faster-whisper`) and Parakeet (`onnx-asr`)
  - API inference: OpenAI-compatible `/v1/audio/transcriptions` endpoint
- Model/device controls
  - Local/API selector
  - CPU/GPU selector for local models
  - Portable Mode for local model storage in app directory
- Output
  - Clipboard copy and/or insert at cursor
  - Insert method: `paste` or `type`
  - Typing speed control
- Notifications and overlays
  - Result notifications with configurable width/height/font/timings
  - Screen anchor selection
  - Transcribing spinner
  - Recording dot with live level scaling
  - Empty-result notifications
  - Stats badge modes: disabled / current request / rolling average
- Testing tools in Settings
  - Record microphone test clip
  - Record system-audio test clip
  - Run Test transcription on current test source
  - Test caption field mirrors last transcribed output
- System tray controls
- Optional start-with-Windows autostart
- Light and dark themes

## Requirements

- Windows
- Python 3.12+

## Whisper Server

SmolSTT supports both local inference and API inference.

- Recommended server: [heimoshuiyu/whisper-fastapi](https://github.com/heimoshuiyu/whisper-fastapi)
- It is easy to set up with Docker using that repository's instructions.

## Setup

1. Create the virtual environment:
   - `venv_create.bat`
2. Install dependencies:
   - `pip install -r requirements.txt`

## Run

- Launch SmolSTT:
  - `app.bat`

## Build

- Build the EXE:
  - `build.bat`

Output:
- `dist/SmolSTT.exe`

## Configuration Options

All settings are available in the app Settings window.

### Server

- `api_url`: Base URL for your OpenAI-compatible transcription server
- `api_endpoint`: Endpoint path (default `/v1/audio/transcriptions`)
- `whisper_backend`: `local` or `api`
- `model`: Active model
  - Whisper models can run local or API
  - Parakeet models are local-only
- `model_device`: `cpu` or `gpu` (local backend)
- `language`: Language hint (`auto` supported)
- `portable_models`: Store local models in app folder instead of shared cache

### Hotkey

- `hotkey`: Global microphone hotkey
- `system_audio_hotkey`: Optional global hotkey for system-audio capture
- `hotkey_mode`:
  - `toggle`: press once to start, press again to stop
  - `hold`: record while key is held
- `suppress_hotkey`: If true, swallows hotkey keystrokes system-wide

  <img width="723" height="335" alt="image" src="https://github.com/user-attachments/assets/b8a9f482-cdce-4de7-9471-99b6882e1a41" />


### Microphone

- `microphone`: Select input device
- `microphone_sensitivity`: RMS threshold for accepting mic audio (`0` disables filter)
- `sample_rate`: Recording sample rate

### Output

- `output_clipboard`: Copy transcribed text to clipboard
- `output_insert`: Insert text at current cursor/focus
- `output_insert_method`:
  - `paste`: paste clipboard contents
  - `type`: type text key-by-key
- `typing_speed`: Characters per second for `type`

### Notifications

- `show_notification`: Show transcript popup
- `show_empty_notification`: Show popup on empty transcription result
- `show_sensitivity_reject_notification`: Show popup on sensitivity rejection
- `show_transcribing_notification`: Show transcribing spinner
- `show_recording_indicator`: Show recording dot
- `notification_font_size`: Popup text size
- `notification_width`: Popup width
- `notification_height`: Popup max height (`0` = no limit)
- `notification_anchor`: Screen anchor for notifications/overlays
- `notification_fade_in_duration_s`: Fade-in duration
- `notification_duration_s`: Visible duration
- `notification_fade_duration_s`: Fade-out duration
- `speed_stats_mode`:
  - `disabled`
  - `current` (latest request)
  - `average` (rolling recent average)

### General

- `autostart`: Start with Windows
- `app_theme`: `dark` or `light`
- `output_capture_source`: Preferred system audio source for loopback capture
- `test_input_file`: Optional file used by Testing `Test` action
