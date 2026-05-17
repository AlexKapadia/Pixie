# Whisper Transcription

CPU-only faster-whisper transcription that streams segments back as they're decoded. Uses the `tiny` model on first call (~75 MB download). Includes a naive gap-based speaker labeller.

## Install
```
cd tools/whisper-transcription
uv sync
```

## Test
```
uv run pixie validate whisper-transcription --summary
```
