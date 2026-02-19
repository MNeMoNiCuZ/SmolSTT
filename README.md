# SmolSTT

SmolSTT is a minimal global push-to-talk speech-to-text desktop app for Windows.
It records microphone audio, sends it to an OpenAI-compatible Whisper endpoint,
and outputs text to clipboard and/or inserts it into the active app.

## Features

- Global hotkey capture (`toggle` or `hold`)
- Microphone device selection
- Optional microphone sensitivity threshold filter
- Whisper/OpenAI-compatible transcription API support
- Clipboard and cursor insertion output modes
- Toast notifications (including timing, size, and animation settings)
- System tray controls
- Optional start-with-Windows autostart
- Light and dark themes

## Requirements

- Windows
- Python 3.12+

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

- `api_url`: Base URL for your Whisper/OpenAI-compatible server
- `api_endpoint`: Endpoint path for transcription requests
- `model`: Model name sent in the request (for example `whisper-small`)
- `language`: Language hint (`auto` supported)

### Hotkey

- `hotkey`: Global hotkey combination
- `hotkey_mode`:
  - `toggle`: press once to start, press again to stop
  - `hold`: record while key is held

### Microphone

- `microphone`: Select input device
- `microphone_sensitivity_enabled`: Enable threshold filtering
- `microphone_sensitivity`: Minimum RMS threshold for accepting audio
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
- `show_sensitivity_reject_notification`: Show popup on sensitivity rejection
- `show_transcribing_notification`: Show transcribing spinner
- `show_recording_indicator`: Show recording dot
- `notification_font_size`: Popup text size
- `notification_width`: Popup width
- `notification_height`: Popup max height (`0` = no limit)
- `notification_fade_in_duration_s`: Fade-in duration
- `notification_duration_s`: Visible duration
- `notification_fade_duration_s`: Fade-out duration

### General

- `autostart`: Start with Windows
- `app_theme`: `dark` or `light`
