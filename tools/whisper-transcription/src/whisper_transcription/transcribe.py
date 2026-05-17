"""faster-whisper wrapper with a lazy model + simple speaker heuristic."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Iterator

_model_lock = threading.Lock()
_model = None


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str


def _load_model():  # lazy: first call downloads ~75 MB on first run
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel
                _model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _model


def _speaker_for(index: int, prev_end: float, start: float) -> str:
    """Naive single-channel speaker tag: gap > 0.8 s flips speakers."""
    if index == 0:
        return "S1"
    return "S2" if (start - prev_end) > 0.8 else "S1"


def transcribe(audio_path: str, language: str | None) -> Iterator[Segment]:
    model = _load_model()
    lang = None if language in (None, "", "auto") else language
    segments, _info = model.transcribe(audio_path, language=lang, beam_size=1, vad_filter=True)
    prev_end = 0.0
    for index, seg in enumerate(segments):
        speaker = _speaker_for(index, prev_end, seg.start)
        prev_end = seg.end
        yield Segment(start=float(seg.start), end=float(seg.end), text=seg.text.strip(), speaker=speaker)
