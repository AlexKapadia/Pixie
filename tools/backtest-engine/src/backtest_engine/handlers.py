"""FastAPI app for backtest-engine."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel

from .backtest import backtest

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class Inputs(BaseModel):
    ohlc_csv: str | None = None
    fast_ma: int = 20
    slow_ma: int = 50
    initial_cash: float = 100000.0
    commission_bps: float = 5.0


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


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
        return backtest(
            inputs.ohlc_csv,
            inputs.fast_ma,
            inputs.slow_ma,
            inputs.initial_cash,
            inputs.commission_bps,
        )

    @app.post("/cancel")
    async def cancel(run_id: str) -> Response:
        return Response(status_code=204)

    return app
