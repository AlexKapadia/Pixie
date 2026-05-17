"""FastAPI app for the streaming tool-use agent."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .agent import StreamEvent, run_agent

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class Inputs(BaseModel):
    messages: list[dict] | None = None
    tools: list[str] = ["calculator"]


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    messages: list[dict] | None = None
    tools: list[str] | None = None
    inputs: Inputs | None = None


def _empty_log() -> dict[str, Any]:
    return {"lines": []}


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
        if not inputs.messages:
            inputs.messages = [{"role": "user", "content": "What is 7 * 8?"}]
        pending[run_id] = inputs
        return {"run_id": run_id, "reply": "", "tool_calls": _empty_log()}

    @app.get("/stream")
    async def stream(run_id: str, request: Request) -> StreamingResponse:
        inputs = pending.pop(run_id, Inputs(messages=[{"role": "user", "content": "What is 7 * 8?"}]))
        log_lines: list[dict[str, Any]] = []

        async def event_stream() -> AsyncIterator[bytes]:
            try:
                async for event in run_agent(inputs.messages or [], inputs.tools):
                    if await request.is_disconnected():
                        return
                    if event.kind == "text":
                        payload = {"chunk": event.payload, "done": False}
                    else:
                        log_lines.append({
                            "t": time.time(),
                            "level": "tool",
                            "message": json.dumps(event.payload),
                        })
                        payload = {"tool_calls": {"lines": list(log_lines)}, "done": False}
                    yield f"data: {json.dumps(payload)}\n\n".encode("utf-8")
                final = {"tool_calls": {"lines": log_lines}, "chunk": "", "done": True}
                yield f"data: {json.dumps(final)}\n\n".encode("utf-8")
            except asyncio.CancelledError:
                raise

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/cancel")
    async def cancel(run_id: str) -> Response:
        pending.pop(run_id, None)
        return Response(status_code=204)

    return app
