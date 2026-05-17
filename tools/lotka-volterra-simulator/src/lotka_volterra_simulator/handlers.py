"""FastAPI app for the Lotka-Volterra simulator."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel

from .solver import equilibria, simulate

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))
MAX_PLOT_POINTS = 1500


class Inputs(BaseModel):
    alpha: float = 1.1
    beta: float = 0.4
    gamma: float = 0.4
    delta: float = 0.1
    initial_prey: float = 10.0
    initial_predator: float = 5.0
    t_max: float = 50.0


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
    result = simulate(
        inputs.alpha, inputs.beta, inputs.gamma, inputs.delta,
        inputs.initial_prey, inputs.initial_predator, inputs.t_max,
    )
    t = _downsample(result.t.tolist())
    prey = _downsample(result.prey.tolist())
    predator = _downsample(result.predator.tolist())

    populations = {
        "x": t,
        "series": [
            {"name": "prey", "y": prey},
            {"name": "predator", "y": predator},
        ],
        "x_label": "t",
        "y_label": "population",
    }
    phase_portrait = {
        "series": [
            {
                "name": "orbit",
                "points": [{"x": p, "y": q} for p, q in zip(prey, predator)],
            }
        ],
        "x_label": "prey",
        "y_label": "predator",
    }
    fixed = equilibria(inputs.alpha, inputs.beta, inputs.gamma, inputs.delta)
    eq_summary = {"pairs": {
        "trivial": f"prey={fixed['trivial']['prey']:.2f}, predator={fixed['trivial']['predator']:.2f}",
        "coexistence": f"prey={fixed['coexistence']['prey']:.4f}, predator={fixed['coexistence']['predator']:.4f}",
        "final_prey": round(float(result.prey[-1]), 4),
        "final_predator": round(float(result.predator[-1]), 4),
    }}
    return {
        "populations": populations,
        "phase_portrait": phase_portrait,
        "equilibria": eq_summary,
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
