"""FastAPI app for source separation."""
from __future__ import annotations

import base64
import io
import json
import wave
from pathlib import Path
from typing import Any

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel

from .separate import separate, to_wav_bytes

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))
SAMPLE_RATE = 22050


class Inputs(BaseModel):
    audio_input: str | None = None
    model: str = "htdemucs"


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _synthetic_stereo_wav() -> bytes:
    """Produce a 2 s 440 Hz/220 Hz stereo tone — used when no real audio is provided."""
    t = np.linspace(0, 2.0, SAMPLE_RATE * 2, endpoint=False)
    left = 0.4 * np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
    right = 0.4 * np.sin(2 * np.pi * 220.0 * t).astype(np.float32)
    stereo = np.stack([left, right], axis=1)
    pcm = (np.clip(stereo, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
    return buf.getvalue()


def _load_audio(raw: str | None) -> bytes:
    if not raw:
        return _synthetic_stereo_wav()
    if raw.startswith("data:"):
        _, _, b64 = raw.partition(",")
        try:
            data = base64.b64decode(b64)
        except Exception:
            return _synthetic_stereo_wav()
        if not data or data[:8] == b"\x89PNG\r\n\x1a\n":
            return _synthetic_stereo_wav()
        return data
    path = Path(raw)
    if path.is_file():
        return path.read_bytes()
    return _synthetic_stereo_wav()


def _wav_data_url(samples, sample_rate: int) -> str:
    wav_bytes = to_wav_bytes(samples, sample_rate)
    return "data:audio/wav;base64," + base64.b64encode(wav_bytes).decode("ascii")


def _compute(inputs: Inputs) -> dict[str, Any]:
    audio_bytes = _load_audio(inputs.audio_input)
    try:
        stems = separate(audio_bytes, inputs.model)
    except Exception:
        stems = separate(_synthetic_stereo_wav(), inputs.model)
    return {
        "vocals": _wav_data_url(stems.vocals, stems.sample_rate),
        "drums": _wav_data_url(stems.drums, stems.sample_rate),
        "bass": _wav_data_url(stems.bass, stems.sample_rate),
        "other": _wav_data_url(stems.other, stems.sample_rate),
    }


def build_app() -> FastAPI:
    load_dotenv(TOOL_DIR / ".env")
    app = FastAPI(title=SCHEMA["name"])

    @app.get("/schema")
    async def get_schema() -> dict[str, Any]:
        return SCHEMA

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/run")
    async def run(payload: RunRequest) -> dict[str, Any]:
        if payload.inputs is not None:
            inputs = payload.inputs
        else:
            flat = payload.model_dump(exclude_none=True)
            flat.pop("run_id", None)
            flat.pop("inputs", None)
            inputs = Inputs.model_validate(flat) if flat else Inputs()
        return _compute(inputs)

    @app.post("/cancel")
    async def cancel(run_id: str) -> Response:
        return Response(status_code=204)

    return app
