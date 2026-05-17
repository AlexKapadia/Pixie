"""FastAPI app for the Lorenz ODE solver."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel

from .solver import integrate, poincare_section

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))
MAX_PLOT_POINTS = 5000


class Inputs(BaseModel):
    sigma: float = 10.0
    rho: float = 28.0
    beta: float = 8.0 / 3.0
    t_max: float = 40.0
    dt: float = 0.01


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _downsample(values: list[float], limit: int = MAX_PLOT_POINTS) -> list[float]:
    if len(values) <= limit:
        return values
    step = len(values) // limit + 1
    return values[::step]


def _compute(inputs: Inputs) -> dict[str, Any]:
    result = integrate(inputs.sigma, inputs.rho, inputs.beta, inputs.t_max, inputs.dt)
    t = _downsample(result.t.tolist())
    x = _downsample(result.x.tolist())
    y = _downsample(result.y.tolist())
    z = _downsample(result.z.tolist())
    px, py = poincare_section(result)

    time_series = {
        "x": t,
        "series": [
            {"name": "x", "y": x},
            {"name": "y", "y": y},
            {"name": "z", "y": z},
        ],
        "x_label": "t",
        "y_label": "value",
    }
    phase_portrait = {
        "series": [
            {
                "name": "trajectory",
                "points": [{"x": xi, "y": zi} for xi, zi in zip(x, z)],
            }
        ],
        "x_label": "x",
        "y_label": "z",
    }
    poincare = {
        "x": px.tolist(),
        "series": [{"name": "y at z=27", "y": py.tolist()}],
        "x_label": "x crossing",
        "y_label": "y crossing",
    }
    return {
        "time_series": time_series,
        "phase_portrait": phase_portrait,
        "poincare": poincare,
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
