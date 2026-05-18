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
from pydantic import BaseModel, create_model, model_validator
from typing import ClassVar, Optional

from .streaming import generate_reply

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = TOOL_DIR / "tool.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
PROMPTS_DIR = TOOL_DIR / "prompts"


# --- dynamic per-tool Inputs model ------------------------------------------
# Chat tools mostly receive {"messages": [...]} but tool.json may add
# secondary scalar knobs (e.g. temperature). Building the model from the
# schema means those knobs Just Work without editing this file.

_PY_TYPE: dict[str, type] = {
    "text": str, "textarea": str, "select": str, "radio": str,
    "colour": str, "date": str, "time": str, "datetime": str,
    "number": float, "slider": float,
    "checkbox": bool, "toggle": bool,
    "multiselect": list, "date_range": list,
    "file": str, "image": str, "audio": str,
    "json": Any,
}


def _resolve_numeric_type(spec: dict[str, Any]) -> type:
    """Return int when a number/slider has integer-valued step and bounds."""
    step = spec.get("step")
    default = spec.get("default")
    candidates = [step, default, spec.get("min"), spec.get("max")]
    if any(isinstance(v, float) and not v.is_integer() for v in candidates if v is not None):
        return float
    if isinstance(step, int) or (isinstance(step, float) and step.is_integer()):
        return int
    return float


class _PixieInputsBase(BaseModel):
    """Base for the dynamic Inputs model. Drops ``None`` for keys with a
    schema default so the pydantic default kicks in."""
    _schema_defaults: ClassVar[set[str]] = set()

    @model_validator(mode="before")
    @classmethod
    def _drop_none_with_default(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items()
                    if not (v is None and k in cls._schema_defaults)}
        return data


def _build_inputs_model(schema: dict[str, Any]) -> type[BaseModel]:
    defaults_set: set[str] = set()
    fields: dict[str, tuple[Any, Any]] = {}
    for spec in schema.get("inputs", []) or []:
        key = spec.get("key")
        if not key:
            continue
        kind = spec.get("type")
        if kind in {"number", "slider"}:
            py_type = _resolve_numeric_type(spec)
        else:
            py_type = _PY_TYPE.get(kind, Any)
        if "default" in spec:
            default = spec["default"]
            defaults_set.add(key)
        else:
            default = None
        fields[key] = (Optional[py_type], default)
    model = create_model("Inputs", __base__=_PixieInputsBase, **fields)
    model._schema_defaults = defaults_set
    return model


Inputs = _build_inputs_model(SCHEMA)


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
    app = FastAPI(title=SCHEMA["name"])
    pending: dict[str, list[ChatMessage]] = {}

    @app.get("/schema")
    async def get_schema() -> dict[str, Any]:
        return SCHEMA

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/run")
    async def run(payload: RunRequest) -> dict[str, Any]:
        run_id = payload.run_id or str(uuid.uuid4())
        # Validate any non-message inputs (temperature etc.) through the
        # dynamic Inputs model so schema defaults are honoured.
        _ = Inputs.model_validate(payload.inputs or {})
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
