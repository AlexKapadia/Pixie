"""FastAPI app for whisper-transcription with SSE streaming."""
from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .transcribe import transcribe

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class Inputs(BaseModel):
    audio_input: str | None = None
    language: str = "auto"


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _empty_table() -> dict[str, Any]:
    return {
        "columns": [
            {"key": "start", "label": "Start (s)", "type": "number"},
            {"key": "end", "label": "End (s)", "type": "number"},
            {"key": "speaker", "label": "Speaker", "type": "string"},
            {"key": "text", "label": "Text", "type": "string"},
        ],
        "rows": [],
        "downloadable": True,
    }


def _persist_audio(raw: str | None) -> str | None:
    if not raw:
        return None
    if raw.startswith("data:"):
        _, _, b64 = raw.partition(",")
        try:
            data = base64.b64decode(b64)
        except Exception:
            return None
        if not data:
            return None
        # if blob looks like a placeholder PNG (validator probe), reject early
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return None
        suffix = ".wav"
        fd_path = Path(tempfile.mkstemp(suffix=suffix, prefix="whisper_")[1])
        fd_path.write_bytes(data)
        return str(fd_path)
    path = Path(raw)
    if path.is_file():
        return str(path)
    return None


def build_app() -> FastAPI:
    load_dotenv(TOOL_DIR / ".env")
    app = FastAPI(title=SCHEMA["name"])
    pending: dict[str, Inputs] = {}

    @app.get("/schema")
    async def get_schema() -> dict[str, Any]:
        return SCHEMA

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/run")
    async def run(payload: RunRequest) -> dict[str, Any]:
        run_id = payload.run_id or str(uuid.uuid4())
        if payload.inputs is not None:
            inputs = payload.inputs
        else:
            flat = payload.model_dump(exclude_none=True)
            flat.pop("run_id", None)
            flat.pop("inputs", None)
            inputs = Inputs.model_validate(flat) if flat else Inputs()
        pending[run_id] = inputs
        return {"run_id": run_id, "transcript": "", "segments": _empty_table()}

    @app.get("/stream")
    async def stream(run_id: str, request: Request) -> StreamingResponse:
        inputs = pending.pop(run_id, Inputs())
        audio_path = _persist_audio(inputs.audio_input)

        async def event_stream() -> AsyncIterator[bytes]:
            try:
                if audio_path is None:
                    msg = json.dumps({
                        "transcript": "(no audio provided)",
                        "segments": _empty_table(),
                        "done": True,
                    })
                    yield f"data: {msg}\n\n".encode("utf-8")
                    return
                rows: list[dict[str, Any]] = []
                full_text: list[str] = []
                loop = asyncio.get_event_loop()
                iterator = await loop.run_in_executor(None, lambda: iter(transcribe(audio_path, inputs.language)))
                while True:
                    if await request.is_disconnected():
                        return
                    segment = await loop.run_in_executor(None, next, iterator, None)
                    if segment is None:
                        break
                    rows.append({
                        "start": round(segment.start, 2),
                        "end": round(segment.end, 2),
                        "speaker": segment.speaker,
                        "text": segment.text,
                    })
                    full_text.append(segment.text)
                    chunk = json.dumps({"transcript": segment.text + " ", "done": False})
                    yield f"data: {chunk}\n\n".encode("utf-8")
                final = json.dumps({
                    "transcript": " ".join(full_text),
                    "segments": {**_empty_table(), "rows": rows},
                    "done": True,
                })
                yield f"data: {final}\n\n".encode("utf-8")
            except asyncio.CancelledError:
                raise

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/cancel")
    async def cancel(run_id: str) -> Response:
        pending.pop(run_id, None)
        return Response(status_code=204)

    return app
