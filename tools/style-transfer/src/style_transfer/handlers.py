"""FastAPI app for style-transfer. Streams loss per iteration."""
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

from .transfer import encode_image, torch_available, transfer

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class Inputs(BaseModel):
    content_image: str | None = None
    style_image: str | None = None
    strength: float = 60.0
    iterations: int = 100
    image_size: int = 128


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _empty_chart() -> dict[str, Any]:
    return {
        "x": [],
        "series": [{"name": "loss", "y": []}],
        "x_label": "Iteration",
        "y_label": "Loss",
    }


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
        return {
            "run_id": run_id,
            "styled": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNgAAIAAAUAAen63NgAAAAASUVORK5CYII=",
            "loss_curve": _empty_chart(),
            "summary": {"pairs": {"status": "transfer started", "backend": "torch" if torch_available() else "fallback"}},
        }

    @app.get("/stream")
    async def stream(run_id: str, request: Request) -> StreamingResponse:
        inputs = pending.pop(run_id, Inputs())

        async def event_stream() -> AsyncIterator[bytes]:
            losses: list[float] = []
            final_src = ""
            try:
                async for step, image in transfer(
                    inputs.content_image, inputs.style_image,
                    inputs.strength, inputs.iterations, inputs.image_size,
                ):
                    if await request.is_disconnected():
                        return
                    if step is not None:
                        losses.append(step.loss)
                        payload = {
                            "iteration": step.iteration,
                            "loss_curve": {"x": step.iteration, "y": step.loss},
                            "done": False,
                        }
                        yield f"data: {json.dumps(payload)}\n\n".encode("utf-8")
                    elif image is not None:
                        final_src = encode_image(image)
                final = {
                    "done": True,
                    "styled": final_src,
                    "summary": {
                        "pairs": {
                            "backend": "torch" if torch_available() else "fallback",
                            "iterations completed": len(losses),
                            "final loss": losses[-1] if losses else 0.0,
                            "image size": inputs.image_size,
                            "strength (%)": inputs.strength,
                        }
                    },
                }
                yield f"data: {json.dumps(final)}\n\n".encode("utf-8")
            except asyncio.CancelledError:
                raise

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/cancel")
    async def cancel(run_id: str) -> Response:
        pending.pop(run_id, None)
        return Response(status_code=204)

    return app
