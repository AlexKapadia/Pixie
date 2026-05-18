"""FastAPI app for {{TOOL_NAME}}.

Contract:

* ``POST /run`` kicks training off as a background task and returns
  ``{run_id, loss_curve: {...}, summary: {...}}`` with stub data so the
  initial frame renders immediately.
* ``GET /stream?run_id=...`` yields per-epoch SSE events with
  ``{"epoch", "loss", "val_loss"}`` payloads. The renderer appends each
  point to the chart.
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

from .train import train

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


# --- dynamic per-tool Inputs model ------------------------------------------

_PY_TYPE: dict[str, type] = {
    "text": str, "textarea": str, "select": str, "radio": str,
    "colour": str, "date": str, "time": str, "datetime": str,
    "number": float, "slider": float,
    "checkbox": bool, "toggle": bool,
    "multiselect": list, "date_range": list,
    "file": str, "image": str, "audio": str,
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


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: dict[str, Any] | None = None


def _empty_chart() -> dict[str, Any]:
    return {
        "x": [],
        "series": [
            {"name": "loss", "y": []},
            {"name": "val_loss", "y": []},
        ],
        "x_label": "Epoch",
        "y_label": "Loss",
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "columns": [
            {"key": "epoch", "label": "Epoch", "type": "number"},
            {"key": "loss", "label": "Loss", "type": "number"},
            {"key": "val_loss", "label": "Val loss", "type": "number"},
        ],
        "rows": [],
    }


def build_app() -> FastAPI:
    load_dotenv(TOOL_DIR / ".env")
    app = FastAPI(title=SCHEMA["name"])
    pending_inputs: dict[str, Inputs] = {}

    @app.get("/schema")
    async def get_schema() -> dict[str, Any]:
        return SCHEMA

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/run")
    async def run(payload: RunRequest) -> dict[str, Any]:
        run_id = payload.run_id or str(uuid.uuid4())
        raw = payload.inputs
        if raw is None:
            raw = {k: v for k, v in payload.model_dump(exclude_none=True).items()
                   if k not in {"run_id", "inputs"}}
        inputs = Inputs.model_validate(raw or {})
        pending_inputs[run_id] = inputs
        return {
            "run_id": run_id,
            "loss_curve": _empty_chart(),
            "summary": _empty_summary(),
        }

    @app.get("/stream")
    async def stream(run_id: str, request: Request) -> StreamingResponse:
        inputs = pending_inputs.pop(run_id, Inputs())

        async def event_stream() -> AsyncIterator[bytes]:
            try:
                async for epoch_result in train(inputs.epochs, inputs.learning_rate):
                    if await request.is_disconnected():
                        return
                    payload = {
                        "epoch": epoch_result.epoch,
                        "loss": epoch_result.loss,
                        "val_loss": epoch_result.val_loss,
                        "done": False,
                    }
                    yield f"data: {json.dumps(payload)}\n\n".encode("utf-8")
                yield b"data: " + json.dumps({"done": True}).encode("utf-8") + b"\n\n"
            except asyncio.CancelledError:
                raise

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/cancel")
    async def cancel(run_id: str) -> Response:
        pending_inputs.pop(run_id, None)
        return Response(status_code=204)

    return app
