"""FastAPI app for the {{TOOL_NAME}} chat tool.

The chat layout convention:

* ``POST /run`` accepts ``{run_id, messages, history}`` and returns
  ``{run_id, reply: ""}`` immediately (the reply is streamed separately).
* ``GET /stream?run_id=...`` returns Server-Sent Events. Each event has a
  ``data:`` line carrying a JSON-encoded chunk:
  ``{"chunk": "<text>", "done": false}``. The final event sets
  ``"done": true`` and the server closes the stream.

Pixie's renderer assembles the chunks into the ``reply`` stream_text
output as they arrive.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .streaming import generate_reply

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = TOOL_DIR / "tool.json"
PROMPTS_DIR = TOOL_DIR / "prompts"


class ChatMessage(BaseModel):
    role: str
    content: str


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    messages: list[ChatMessage] | None = None
    history: list[ChatMessage] | None = None
    inputs: dict[str, Any] | None = None


def _system_prompt() -> str:
    system_file = PROMPTS_DIR / "system.md"
    if system_file.is_file():
        return system_file.read_text(encoding="utf-8")
    return "You are a helpful assistant."


def build_app() -> FastAPI:
    load_dotenv(TOOL_DIR / ".env")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    app = FastAPI(title=schema["name"])
    pending: dict[str, list[ChatMessage]] = {}

    @app.get("/schema")
    async def get_schema() -> dict[str, Any]:
        return schema

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/run")
    async def run(payload: RunRequest) -> dict[str, Any]:
        run_id = payload.run_id or str(uuid.uuid4())
        messages = payload.messages
        if messages is None and payload.inputs is not None:
            raw = payload.inputs.get("messages") or []
            messages = [ChatMessage.model_validate(m) for m in raw]
        if not messages:
            messages = [ChatMessage(role="user", content="")]
        pending[run_id] = messages
        return {"run_id": run_id, "reply": ""}

    @app.get("/stream")
    async def stream(run_id: str, request: Request) -> StreamingResponse:
        messages = pending.pop(run_id, [])
        system = _system_prompt()

        async def event_stream() -> AsyncIterator[bytes]:
            try:
                async for chunk in generate_reply(system, messages):
                    if await request.is_disconnected():
                        return
                    payload = json.dumps({"chunk": chunk, "done": False})
                    yield f"data: {payload}\n\n".encode("utf-8")
                yield b"data: " + json.dumps({"chunk": "", "done": True}).encode("utf-8") + b"\n\n"
            except asyncio.CancelledError:
                raise

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/cancel")
    async def cancel(run_id: str) -> Response:
        pending.pop(run_id, None)
        return Response(status_code=204)

    return app
