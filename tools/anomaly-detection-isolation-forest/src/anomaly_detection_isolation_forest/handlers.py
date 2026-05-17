"""FastAPI app for the isolation-forest anomaly detector."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel

from .detector import detect

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))
MAX_PLOT_POINTS = 2000


class FilePayload(BaseModel):
    model_config = {"extra": "allow"}
    name: str | None = None
    content_base64: str | None = None
    content: str | None = None
    text: str | None = None


class Inputs(BaseModel):
    model_config = {"extra": "allow"}
    csv_file: FilePayload | str | dict[str, Any] | None = None
    value_column: str = "value"
    timestamp_column: str = "timestamp"
    contamination: float = 5.0
    top_n: int = 20


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _read_csv(payload: Any) -> pd.DataFrame:
    text = _payload_to_text(payload)
    if text is None:
        return _synthetic()
    try:
        df = pd.read_csv(io.StringIO(text))
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError):
        return _synthetic()
    return df if not df.empty else _synthetic()


def _payload_to_text(payload: Any) -> str | None:
    if payload is None:
        return None
    if isinstance(payload, str):
        if payload.startswith("data:"):
            _, _, b64 = payload.partition(",")
            try:
                return base64.b64decode(b64).decode("utf-8", errors="replace")
            except (ValueError, UnicodeDecodeError):
                return None
        return payload
    if isinstance(payload, dict):
        payload = FilePayload(**payload)
    if payload.text:
        return payload.text
    if payload.content:
        return payload.content
    if payload.content_base64:
        try:
            return base64.b64decode(payload.content_base64).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError):
            return None
    return None


def _synthetic(n: int = 500) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    t = pd.date_range("2025-01-01", periods=n, freq="h")
    base = 10 + 2 * np.sin(np.arange(n) * 2 * np.pi / 24) + rng.normal(0, 0.5, n)
    anomaly_idx = rng.choice(n, size=15, replace=False)
    base[anomaly_idx] += rng.choice([-1, 1], size=15) * rng.uniform(5, 10, 15)
    return pd.DataFrame({"timestamp": t.astype(str), "value": base})


def _downsample(values: list[Any], limit: int = MAX_PLOT_POINTS) -> list[Any]:
    if len(values) <= limit:
        return values
    step = len(values) // limit + 1
    return values[::step]


def _compute(inputs: Inputs) -> dict[str, Any]:
    df = _read_csv(inputs.csv_file)
    if inputs.value_column not in df.columns:
        df = _synthetic()
        value_col, timestamp_col = "value", "timestamp"
    else:
        value_col = inputs.value_column
        timestamp_col = inputs.timestamp_column or None
    result = detect(
        df,
        value_col,
        timestamp_col,
        contamination=float(inputs.contamination) / 100.0,
    )

    n_total = int(result.values.size)
    n_anomalies = int(result.anomalies.sum())

    timestamps = result.timestamps.tolist()
    values = result.values.tolist()
    scores = result.scores.tolist()
    flags = result.anomalies.tolist()

    plot_x = _downsample(timestamps)
    plot_values = _downsample(values)
    plot_anomaly = _downsample([v if f else None for v, f in zip(values, flags)])

    series_chart = {
        "x": plot_x,
        "series": [
            {"name": "value", "y": plot_values},
            {"name": "anomaly", "y": plot_anomaly, "mode": "markers"},
        ],
        "x_label": timestamp_col or "index",
        "y_label": value_col,
    }

    ranked = sorted(
        zip(timestamps, values, scores, flags),
        key=lambda row: row[2],
        reverse=True,
    )
    top = [r for r in ranked if r[3]][: int(inputs.top_n)]
    if not top:
        top = ranked[: int(inputs.top_n)]
    top_rows = [
        {
            "timestamp": ts,
            "value": round(float(v), 4),
            "score": round(float(s), 4),
            "flagged": bool(f),
        }
        for ts, v, s, f in top
    ]

    histogram = {
        "values": [round(float(v), 6) for v in result.scores.tolist()],
        "x_label": "anomaly score",
        "y_label": "count",
    }

    summary = {"pairs": {
        "samples": n_total,
        "anomalies": n_anomalies,
        "anomaly_rate_percent": round(100.0 * n_anomalies / max(n_total, 1), 3),
        "max_score": round(float(result.scores.max()), 4),
        "mean_score": round(float(result.scores.mean()), 4),
    }}

    return {
        "series": series_chart,
        "top_anomalies": {
            "columns": [
                {"key": "timestamp", "label": "Timestamp", "type": "string"},
                {"key": "value", "label": "Value", "type": "number"},
                {"key": "score", "label": "Anomaly score", "type": "number"},
                {"key": "flagged", "label": "Flagged", "type": "boolean"},
            ],
            "rows": top_rows,
            "downloadable": True,
        },
        "summary": summary,
        "score_distribution": histogram,
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
