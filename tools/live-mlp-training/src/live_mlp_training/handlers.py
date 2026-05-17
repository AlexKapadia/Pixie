"""FastAPI app for live-mlp-training. Streams per-epoch updates over SSE."""
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

from .dataset import load as load_dataset
from .train import train

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class Inputs(BaseModel):
    dataset_csv: str | None = None
    target_column: str = "target"
    hidden_sizes: str = "32,16"
    epochs: int = 20
    learning_rate: float = 0.01
    batch_size: int = 32
    seed: int = 42


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _empty_chart(name: str, y_label: str) -> dict[str, Any]:
    return {
        "x": [],
        "series": [{"name": name, "y": []}],
        "x_label": "Epoch",
        "y_label": y_label,
    }


def _empty_table() -> dict[str, Any]:
    return {
        "columns": [
            {"key": "epoch", "label": "Epoch", "type": "number"},
            {"key": "train_loss", "label": "Train loss", "type": "number"},
            {"key": "val_loss", "label": "Val loss", "type": "number"},
            {"key": "train_acc", "label": "Train acc", "type": "number"},
            {"key": "val_acc", "label": "Val acc", "type": "number"},
        ],
        "rows": [],
        "downloadable": True,
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
            "loss_curve": _empty_chart("loss", "Cross-entropy"),
            "accuracy_curve": _empty_chart("accuracy", "Accuracy"),
            "final_metrics": {"pairs": {"status": "training started"}},
            "epoch_summary": _empty_table(),
        }

    @app.get("/stream")
    async def stream(run_id: str, request: Request) -> StreamingResponse:
        inputs = pending.pop(run_id, Inputs())

        async def event_stream() -> AsyncIterator[bytes]:
            dataset = load_dataset(inputs.dataset_csv, inputs.target_column, inputs.seed)
            rows: list[dict[str, Any]] = []
            try:
                async for result in train(
                    dataset, inputs.hidden_sizes, inputs.epochs,
                    inputs.learning_rate, inputs.batch_size, inputs.seed,
                ):
                    if await request.is_disconnected():
                        return
                    row = {
                        "epoch": result.epoch,
                        "train_loss": result.train_loss,
                        "val_loss": result.val_loss,
                        "train_acc": result.train_acc,
                        "val_acc": result.val_acc,
                    }
                    rows.append(row)
                    payload = {
                        "epoch": result.epoch,
                        "loss_curve": {"x": result.epoch, "y": result.train_loss, "val_y": result.val_loss},
                        "accuracy_curve": {"x": result.epoch, "y": result.train_acc, "val_y": result.val_acc},
                        "done": False,
                    }
                    yield f"data: {json.dumps(payload)}\n\n".encode("utf-8")
                final = {
                    "done": True,
                    "final_metrics": {
                        "pairs": {
                            "final train loss": rows[-1]["train_loss"] if rows else 0.0,
                            "final val loss": rows[-1]["val_loss"] if rows else 0.0,
                            "final train acc": rows[-1]["train_acc"] if rows else 0.0,
                            "final val acc": rows[-1]["val_acc"] if rows else 0.0,
                            "epochs run": len(rows),
                            "features": dataset.n_features,
                            "classes": dataset.n_classes,
                        }
                    },
                    "epoch_summary": {**_empty_table(), "rows": rows},
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
