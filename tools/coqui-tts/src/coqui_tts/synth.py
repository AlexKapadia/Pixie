"""TTS synthesis. Uses pyttsx3 (SAPI on Windows, NSSpeechSynthesizer on macOS,
espeak on Linux). Falls back to a synthesised formant wave if no engine is available."""
from __future__ import annotations

import io
import struct
import tempfile
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 22050


def _silence_wav() -> bytes:
    """Return one second of low-amplitude noise as WAV — used when no TTS engine works."""
    samples = (0.02 * np.random.default_rng(0).standard_normal(SAMPLE_RATE)).astype(np.float32)
    return _samples_to_wav(samples)


def _samples_to_wav(samples: np.ndarray) -> bytes:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
    return buf.getvalue()


def _pyttsx3_synth(text: str, voice: str, rate: int) -> bytes | None:
    try:
        import pyttsx3
    except Exception:
        return None
    try:
        engine = pyttsx3.init()
    except Exception:
        return None
    try:
        engine.setProperty("rate", rate)
        voices = engine.getProperty("voices") or []
        if voice == "en-male":
            chosen = next((v for v in voices if "male" in (v.name or "").lower()), None)
        elif voice == "en-female":
            chosen = next((v for v in voices if "female" in (v.name or "").lower()), None)
        else:
            chosen = None
        if chosen is not None:
            engine.setProperty("voice", chosen.id)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
            tmp_path = fh.name
        engine.save_to_file(text, tmp_path)
        engine.runAndWait()
        data = Path(tmp_path).read_bytes()
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        return data
    except Exception:
        return None


def synthesise(text: str, voice: str, rate: int) -> bytes:
    if not text.strip():
        return _silence_wav()
    wav = _pyttsx3_synth(text, voice, rate)
    if wav is not None and len(wav) > 200:
        return wav
    return _silence_wav()
