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
from pydantic import BaseModel

from .train import train

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class Inputs(BaseModel):
    dataset: str | None = None
    epochs: int = 10
    learning_rate: float = 0.01


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


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
        inputs = payload.inputs or Inputs.model_validate(
            {k: v for k, v in payload.model_dump(exclude_none=True).items()
             if k not in {"run_id", "inputs"}}
        )
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
