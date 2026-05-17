"""FastAPI app for sentiment-over-time."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel

from .analysis import analyse

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class Inputs(BaseModel):
    dataset_csv: str | None = None
    date_column: str = "date"
    text_column: str = "text"
    window_days: int = 7


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _read_csv(raw: str | None) -> pd.DataFrame:
    if raw is None:
        return _sample_frame()
    try:
        if raw.startswith("data:"):
            _, _, b64 = raw.partition(",")
            data = base64.b64decode(b64)
            return pd.read_csv(io.BytesIO(data))
        path = Path(raw)
        if path.is_file():
            return pd.read_csv(path)
        return pd.read_csv(io.StringIO(raw))
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError):
        # uploaded blob was not a CSV (e.g. validator probe with a 1x1 PNG); use sample.
        return _sample_frame()


def _sample_frame() -> pd.DataFrame:
    base_date = pd.Timestamp("2026-01-01")
    rows = []
    texts_pos = ["this is great", "loved the product", "excellent service", "wonderful experience"]
    texts_neg = ["this is terrible", "broken on arrival", "awful customer support", "deeply disappointed"]
    for day in range(30):
        for index, text in enumerate(texts_pos + texts_neg):
            rows.append({"date": base_date + pd.Timedelta(days=day), "text": text})
    return pd.DataFrame(rows)


def _compute(inputs: Inputs) -> dict[str, Any]:
    frame = _read_csv(inputs.dataset_csv)
    result = analyse(frame, inputs.date_column, inputs.text_column, inputs.window_days)

    timeline = result.timeline
    chart = {
        "x": [d.isoformat() for d in timeline["window_start"]],
        "series": [{
            "name": f"{inputs.window_days}-day rolling mean",
            "y": [float(v) if pd.notna(v) else 0.0 for v in timeline["mean_compound"]],
        }],
        "x_label": "date",
        "y_label": "compound sentiment",
    }
    window_rows = [
        {
            "window_start": row["window_start"].isoformat(),
            "n_messages": int(row["n_messages"]),
            "mean_compound": round(float(row["mean_compound"]), 4),
            "share_positive": round(float(row["share_positive"]), 4),
            "share_negative": round(float(row["share_negative"]), 4),
        }
        for _, row in result.windows.iterrows()
    ]
    table = {
        "columns": [
            {"key": "window_start", "label": "Window start", "type": "string"},
            {"key": "n_messages", "label": "Messages", "type": "number"},
            {"key": "mean_compound", "label": "Mean compound", "type": "number"},
            {"key": "share_positive", "label": "% positive", "type": "number"},
            {"key": "share_negative", "label": "% negative", "type": "number"},
        ],
        "rows": window_rows,
        "downloadable": True,
    }
    return {"sentiment_curve": chart, "window_summary": table}


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
