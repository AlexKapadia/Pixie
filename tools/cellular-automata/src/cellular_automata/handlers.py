"""FastAPI app for the cellular automata explorer."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from PIL import Image
from pydantic import BaseModel

from .automata import evolve

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class Inputs(BaseModel):
    rule: str = "conway"
    width: int = 120
    generations: int = 120
    seed: str = "42"


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _grid_to_data_url(grid_uint8) -> str:
    image = Image.fromarray(grid_uint8.astype("uint8"), mode="L")
    # upscale to a comfortable display size, preserving the pixel-art look
    max_side = 600
    scale = max(1, max_side // max(image.width, image.height))
    if scale > 1:
        image = image.resize((image.width * scale, image.height * scale), Image.NEAREST)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _parse_seed(raw: str) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _compute(inputs: Inputs) -> dict[str, Any]:
    seed = _parse_seed(inputs.seed)
    result = evolve(inputs.rule, inputs.width, inputs.generations, seed)
    image_url = _grid_to_data_url(result.grid)
    counts_chart = {
        "x": list(range(len(result.counts))),
        "series": [{"name": "live cells", "y": result.counts}],
        "x_label": "generation",
        "y_label": "cells alive",
    }
    return {"evolved": image_url, "cell_count": counts_chart}


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
