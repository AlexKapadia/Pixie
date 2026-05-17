"""Compound interest calculator — canonical Pixie example tool.

Standalone FastAPI app honouring the Pixie HTTP contract. Binds 127.0.0.1 only.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel

TOOL_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = TOOL_DIR / "tool.json"
INFLATION_RATE = 0.025

logger = logging.getLogger("compound_interest")


class RunInputs(BaseModel):
    principal: float
    annual_rate: float
    years: int
    compounding: int
    monthly_contribution: float
    inflation_adjusted: bool = False


class RunRequest(BaseModel):
    # Pixie sends {"run_id": "...", "inputs": {...}} per DECISIONS #1.
    # `model_config` extra is allow so older callers can still POST flat.
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: RunInputs | None = None


def _compute(payload: RunInputs) -> dict[str, Any]:
    periods_per_year = int(payload.compounding)
    period_rate = payload.annual_rate / 100.0 / periods_per_year
    per_period_contribution = payload.monthly_contribution * 12.0 / periods_per_year

    balance = float(payload.principal)
    total_contributed = float(payload.principal)
    yearly_rows: list[dict[str, float]] = []
    series_y: list[float] = [balance]

    for year_index in range(1, payload.years + 1):
        start_balance = balance
        year_contributions = 0.0
        year_interest = 0.0
        for _ in range(periods_per_year):
            interest = balance * period_rate
            balance += interest + per_period_contribution
            year_interest += interest
            year_contributions += per_period_contribution
            total_contributed += per_period_contribution
        yearly_rows.append({
            "year": year_index,
            "start_balance": round(start_balance, 2),
            "contributions": round(year_contributions, 2),
            "interest": round(year_interest, 2),
            "end_balance": round(balance, 2),
        })
        series_y.append(balance)

    if payload.inflation_adjusted:
        deflator = [(1.0 + INFLATION_RATE) ** y for y in range(payload.years + 1)]
        series_y = [v / deflator[i] for i, v in enumerate(series_y)]
        for row in yearly_rows:
            year_factor = (1.0 + INFLATION_RATE) ** row["year"]
            for col in ("start_balance", "contributions", "interest", "end_balance"):
                row[col] = round(row[col] / year_factor, 2)
        final_value = series_y[-1]
        total_interest = final_value - total_contributed / ((1.0 + INFLATION_RATE) ** payload.years)
    else:
        final_value = series_y[-1]
        total_interest = final_value - total_contributed

    series_name = "Balance (real, today's £)" if payload.inflation_adjusted else "Balance"

    return {
        "final_value": round(final_value, 2),
        "total_contributions": round(total_contributed, 2),
        "total_interest": round(total_interest, 2),
        "growth_chart": {
            "x": list(range(payload.years + 1)),
            "series": [{"name": series_name, "y": [round(v, 2) for v in series_y]}],
            "x_label": "Year",
            "y_label": "Balance (£)",
        },
        "yearly_breakdown": {
            "columns": [
                {"key": "year", "label": "Year", "type": "number"},
                {"key": "start_balance", "label": "Start balance", "type": "number"},
                {"key": "contributions", "label": "Contributions", "type": "number"},
                {"key": "interest", "label": "Interest", "type": "number"},
                {"key": "end_balance", "label": "End balance", "type": "number"},
            ],
            "rows": yearly_rows,
            "downloadable": True,
        },
    }


def build_app() -> FastAPI:
    load_dotenv(TOOL_DIR / ".env")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    app = FastAPI(title=schema["name"])

    @app.get("/schema")
    async def get_schema() -> dict[str, Any]:
        return schema

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/run")
    async def run(payload: RunRequest) -> dict[str, Any]:
        # Accept both shapes: new {run_id, inputs} envelope, or flat inputs.
        if payload.inputs is not None:
            return _compute(payload.inputs)
        flat = payload.model_dump(exclude_none=True)
        flat.pop("run_id", None)
        flat.pop("inputs", None)
        return _compute(RunInputs.model_validate(flat))

    @app.post("/cancel")
    async def cancel(run_id: str) -> Response:
        return Response(status_code=204)

    return app


app = build_app()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
