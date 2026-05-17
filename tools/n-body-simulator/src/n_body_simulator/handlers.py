"""FastAPI app for the N-body simulator."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel

from .simulate import simulate

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))
MAX_TRACE_POINTS = 600


class Inputs(BaseModel):
    n_bodies: int = 5
    mass_range: float = 2.0
    time_steps: int = 1500
    dt: float = 0.005
    seed: int = 42


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _downsample(series: list[float], limit: int = MAX_TRACE_POINTS) -> list[float]:
    if len(series) <= limit:
        return series
    step = len(series) // limit + 1
    return series[::step]


def _compute(inputs: Inputs) -> dict[str, Any]:
    result = simulate(
        inputs.n_bodies, inputs.mass_range, inputs.time_steps, inputs.dt, inputs.seed,
    )
    n_bodies = inputs.n_bodies
    last = result.positions[-1]

    final_positions = {
        "series": [
            {
                "name": f"body {i}",
                "points": [{"x": float(last[i, 0]), "y": float(last[i, 1])}],
            }
            for i in range(n_bodies)
        ],
        "x_label": "x",
        "y_label": "y",
    }

    t_axis = list(range(result.energy.shape[0]))
    energy = {
        "x": _downsample(t_axis),
        "series": [
            {"name": "total energy", "y": _downsample(result.energy.tolist())},
        ],
        "x_label": "step",
        "y_label": "E",
    }

    trajectories = {
        "x": _downsample(t_axis),
        "series": [
            {
                "name": f"body {i} x",
                "y": _downsample(result.positions[:, i, 0].tolist()),
            }
            for i in range(n_bodies)
        ],
        "x_label": "step",
        "y_label": "x position",
    }

    return {
        "final_positions": final_positions,
        "energy": energy,
        "trajectories": trajectories,
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
