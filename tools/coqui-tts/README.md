# Text-to-Speech

Offline TTS via pyttsx3 (uses SAPI on Windows, NSSpeechSynthesizer on macOS, espeak on Linux). Returns a 22 kHz WAV data URL.

The folder is named `coqui-tts` for parity with the upstream Pixie tool catalogue. The implementation uses the more portable pyttsx3 (Coqui-TTS pulls a large torch dependency that is brittle on Windows).

## Install
```
cd tools/coqui-tts
uv sync
```

## Test
```
uv run pixie validate coqui-tts --summary
```
