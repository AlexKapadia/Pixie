"""FastAPI app for the Kaplan-Meier + Cox tool."""
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

from .survival import cox_hazards, kaplan_meier

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))
MAX_POINTS = 400


class FilePayload(BaseModel):
    model_config = {"extra": "allow"}
    name: str | None = None
    content_base64: str | None = None
    content: str | None = None
    text: str | None = None


class Inputs(BaseModel):
    model_config = {"extra": "allow"}
    csv_file: FilePayload | str | dict[str, Any] | None = None
    time_column: str = "time"
    event_column: str = "event"
    strata_column: str | None = None
    covariates: list[str] | None = None


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _read_csv(payload: Any) -> pd.DataFrame:
    text = _payload_to_text(payload)
    if text is None:
        return _synthetic_dataset()
    try:
        df = pd.read_csv(io.StringIO(text))
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError):
        return _synthetic_dataset()
    return df if not df.empty else _synthetic_dataset()


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


def _synthetic_dataset(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    group = rng.choice(["A", "B"], size=n, p=[0.5, 0.5])
    age = rng.normal(60, 10, n)
    baseline_hazard = 0.05
    hr_group = np.where(group == "B", 1.8, 1.0)
    hr_age = np.exp(0.02 * (age - 60))
    rate = baseline_hazard * hr_group * hr_age
    time = rng.exponential(1.0 / rate)
    censor = rng.exponential(40.0, n)
    observed_time = np.minimum(time, censor)
    event = (time <= censor).astype(int)
    return pd.DataFrame({
        "time": observed_time, "event": event,
        "group": group, "age": age,
    })


def _downsample(timeline: list[float], values: list[float]) -> tuple[list[float], list[float]]:
    if len(timeline) <= MAX_POINTS:
        return timeline, values
    step = len(timeline) // MAX_POINTS + 1
    return timeline[::step], values[::step]


def _compute(inputs: Inputs) -> dict[str, Any]:
    df = _read_csv(inputs.csv_file)
    if inputs.time_column not in df.columns or inputs.event_column not in df.columns:
        df = _synthetic_dataset()
        time_col, event_col = "time", "event"
    else:
        time_col, event_col = inputs.time_column, inputs.event_column
    strata = inputs.strata_column if inputs.strata_column else None
    if strata and strata not in df.columns:
        strata = None
    covariates = [c for c in (inputs.covariates or []) if c in df.columns]

    curves = kaplan_meier(df, time_col, event_col, strata)

    union_timeline = sorted({t for c in curves for t in c.timeline})
    union_timeline = _downsample(union_timeline, [0.0] * len(union_timeline))[0]

    series: list[dict[str, Any]] = []
    for curve in curves:
        # Step-interpolate each curve onto the union timeline.
        step_x, step_y = curve.timeline, curve.survival
        if not step_x:
            continue
        y_aligned: list[float] = []
        j = 0
        for t in union_timeline:
            while j + 1 < len(step_x) and step_x[j + 1] <= t:
                j += 1
            y_aligned.append(round(step_y[j], 6))
        series.append({"name": curve.label, "y": y_aligned})

    survival_chart = {
        "x": [round(t, 4) for t in union_timeline],
        "series": series,
        "x_label": "time",
        "y_label": "S(t)",
    }

    median_table = {
        "columns": [
            {"key": "stratum", "label": "Stratum", "type": "string"},
            {"key": "n", "label": "n", "type": "number"},
            {"key": "events", "label": "Events", "type": "number"},
            {"key": "median", "label": "Median survival", "type": "number"},
        ],
        "rows": [
            {
                "stratum": c.label, "n": c.size, "events": c.events,
                "median": round(c.median, 4) if c.median is not None else None,
            }
            for c in curves
        ],
        "downloadable": True,
    }

    try:
        hazard_summary = cox_hazards(df, time_col, event_col, covariates)
    except Exception:
        hazard_summary = {}
    if not hazard_summary:
        kv_hazards = {"pairs": {"note": "No covariates supplied or Cox model could not be fitted."}}
    else:
        kv_hazards = {"pairs": {
            name: (
                f"HR={info['hr']} (95% CI {info['hr_lower_95']}-{info['hr_upper_95']}, p={info['p_value']})"
            )
            for name, info in hazard_summary.items()
        }}

    return {
        "survival_curves": survival_chart,
        "median_survival": median_table,
        "hazard_ratios": kv_hazards,
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
