"""FastAPI app for the causal ATE estimator."""
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

from .estimator import estimate

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class FilePayload(BaseModel):
    model_config = {"extra": "allow"}
    name: str | None = None
    content_base64: str | None = None
    content: str | None = None
    text: str | None = None


class Inputs(BaseModel):
    model_config = {"extra": "allow"}
    csv_file: FilePayload | str | dict[str, Any] | None = None
    treatment: str = "treatment"
    outcome: str = "outcome"
    confounders: list[str] | None = None


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _read_csv(payload: Any) -> pd.DataFrame:
    text = _payload_to_text(payload)
    if text is None:
        return _synthetic_dataset()
    try:
        return pd.read_csv(io.StringIO(text))
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError):
        return _synthetic_dataset()


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


def _synthetic_dataset(n: int = 600, true_ate: float = 1.5) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    age = rng.normal(40, 10, n)
    income = rng.normal(30, 5, n)
    logits = -2.0 + 0.04 * age + 0.05 * income
    p = 1.0 / (1.0 + np.exp(-logits))
    treatment = (rng.random(n) < p).astype(float)
    outcome = (
        0.3 * age + 0.4 * income + true_ate * treatment
        + rng.normal(0, 2.0, n)
    )
    return pd.DataFrame({
        "age": age, "income": income,
        "treatment": treatment, "outcome": outcome,
    })


def _compute(inputs: Inputs) -> dict[str, Any]:
    df = _read_csv(inputs.csv_file)
    confounders = list(inputs.confounders or [])
    if inputs.treatment not in df.columns or inputs.outcome not in df.columns:
        df = _synthetic_dataset()
        if inputs.treatment != "treatment" or inputs.outcome != "outcome":
            confounders = ["age", "income"]
    est = estimate(df, "treatment" if inputs.treatment not in df.columns else inputs.treatment,
                   "outcome" if inputs.outcome not in df.columns else inputs.outcome,
                   confounders)

    refutations = {
        "x": ["OLS", "IPW", "Doubly robust", "Placebo treatment", "Random 80% subset"],
        "series": [{
            "name": "ATE",
            "y": [
                round(est.ate_ols, 4),
                round(est.ate_ipw, 4),
                round(est.ate_doubly_robust, 4),
                round(est.placebo_ate, 4),
                round(est.subset_ate, 4),
            ],
        }],
        "y_label": "ATE",
    }
    explanation = (
        "### Identification assumptions\n\n"
        f"- **Treatment column:** `{inputs.treatment}`\n"
        f"- **Outcome column:** `{inputs.outcome}`\n"
        f"- **Confounders adjusted for:** {', '.join(confounders) if confounders else 'none'}\n\n"
        "Assumes the listed confounders block all backdoor paths between treatment and outcome "
        "(no unmeasured confounding), positivity, and consistency. The placebo refutation "
        "should be close to zero; the subset refutation should be close to the headline ATE.\n\n"
        f"- Sample size after row drop: **{est.sample_size}**\n"
        f"- OLS ATE: **{est.ate_ols:.4f}** (95% CI {est.ci_lower:.4f} to {est.ci_upper:.4f})\n"
        f"- IPW ATE: **{est.ate_ipw:.4f}**\n"
        f"- Doubly robust ATE: **{est.ate_doubly_robust:.4f}**\n"
        f"- Placebo (permuted treatment) ATE: **{est.placebo_ate:.4f}**\n"
        f"- 80% subset ATE: **{est.subset_ate:.4f}**\n"
    )
    return {
        "ate": round(est.ate, 4),
        "ci_lower": round(est.ci_lower, 4),
        "ci_upper": round(est.ci_upper, 4),
        "refutations": refutations,
        "explanation": explanation,
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
