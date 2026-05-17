"""FastAPI app for the quantum circuit simulator."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from .simulator import ascii_diagram, parse, sample, simulate

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class Inputs(BaseModel):
    model_config = {"extra": "allow"}
    circuit: str = "qubits 3\nH 0\nCX 0 1\nCX 1 2"
    shots: int = 1024
    success_state: str | None = "000"


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _compute(inputs: Inputs) -> dict[str, Any]:
    try:
        parsed = parse(inputs.circuit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    state = simulate(parsed)
    counts = sample(state, parsed.n_qubits, int(inputs.shots))

    success_prob = None
    if inputs.success_state:
        target = inputs.success_state.strip()
        if len(target) == parsed.n_qubits and set(target).issubset({"0", "1"}):
            index = int(target, 2)
            success_prob = float(np.abs(state[index]) ** 2)

    chart = {
        "x": list(counts.keys()),
        "series": [{"name": "counts", "y": list(counts.values())}],
        "x_label": "bitstring",
        "y_label": "counts",
    }
    summary_pairs: dict[str, Any] = {
        "qubits": parsed.n_qubits,
        "gates_applied": len(parsed.gates),
        "shots": int(inputs.shots),
        "most_likely_outcome": max(counts.items(), key=lambda kv: kv[1])[0],
    }
    if success_prob is not None:
        summary_pairs["success_probability"] = round(success_prob, 6)
    summary = {"pairs": summary_pairs}

    diagram_md = (
        "```text\n"
        f"{ascii_diagram(parsed)}\n"
        "```\n"
        f"\n_{parsed.n_qubits} qubits, {len(parsed.gates)} gates._"
    )
    return {"counts": chart, "summary": summary, "diagram": diagram_md}


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
