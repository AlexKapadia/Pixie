"""FastAPI app for the Bayesian A/B test tool."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel

from .analysis import analyse

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class Inputs(BaseModel):
    control_conversions: int = 100
    control_total: int = 1000
    variant_conversions: int = 130
    variant_total: int = 1000
    prior_strength: float = 2.0


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _decision_markdown(result: Any, inputs: Inputs) -> str:
    p = result.p_variant_better
    if p >= 0.95:
        verdict = "**Ship the variant.** The posterior probability that the variant outperforms control is at least 95%."
    elif p <= 0.05:
        verdict = "**Stop the test.** The posterior probability that the variant outperforms control is below 5%."
    elif result.rope_loss > 0.8:
        verdict = "**Effect is practically zero.** Most posterior mass falls within ±1 percentage point — collect more data or call the test inconclusive."
    else:
        verdict = "**Inconclusive — keep collecting.** Posterior mass is not yet concentrated enough to ship or stop."
    return (
        f"### Decision\n\n{verdict}\n\n"
        "### Posterior summary\n\n"
        f"- Control rate posterior mean: **{result.control_mean*100:.2f}%** "
        f"(Beta α={result.control_alpha:.1f}, β={result.control_beta:.1f})\n"
        f"- Variant rate posterior mean: **{result.variant_mean*100:.2f}%** "
        f"(Beta α={result.variant_alpha:.1f}, β={result.variant_beta:.1f})\n"
        f"- P(variant > control): **{result.p_variant_better*100:.2f}%**\n"
        f"- Expected relative lift: **{result.expected_lift*100:.2f}%**\n"
        f"- P(|variant − control| < 1pp): **{result.rope_loss*100:.2f}%**\n"
        f"- Prior strength used: **{inputs.prior_strength:.1f}**\n"
    )


def _compute(inputs: Inputs) -> dict[str, Any]:
    result = analyse(
        int(inputs.control_conversions),
        int(inputs.control_total),
        int(inputs.variant_conversions),
        int(inputs.variant_total),
        prior_strength=float(inputs.prior_strength),
    )
    posteriors = {
        "x": [round(v, 5) for v in result.grid.tolist()],
        "series": [
            {"name": "control", "y": [round(v, 4) for v in result.control_density.tolist()]},
            {"name": "variant", "y": [round(v, 4) for v in result.variant_density.tolist()]},
        ],
        "x_label": "conversion rate",
        "y_label": "density",
    }
    return {
        "posteriors": posteriors,
        "p_variant_better": round(result.p_variant_better, 6),
        "expected_lift": round(result.expected_lift, 6),
        "recommendation": _decision_markdown(result, inputs),
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
