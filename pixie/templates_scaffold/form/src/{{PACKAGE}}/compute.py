"""Core computation for {{TOOL_NAME}}.

Replace ``compute()`` with your own logic. Keep it pure and synchronous
so it's easy to test.
"""
from __future__ import annotations

from typing import Any

from .models import Inputs, Outputs

STEP_COUNT = 24


def _series(inputs: Inputs) -> list[float]:
    values: list[float] = []
    for step in range(STEP_COUNT):
        normalised = step / max(STEP_COUNT - 1, 1)
        if inputs.shape == "quadratic":
            base = normalised ** 2
        elif inputs.shape == "exponential":
            base = (2.71828 ** (normalised * inputs.intensity)) - 1.0
        else:
            base = normalised * inputs.intensity
        values.append(inputs.scale * base)
    return values


def compute(inputs: Inputs) -> Outputs:
    values = _series(inputs)
    peak = max(values) if values else 0.0

    chart = {
        "x": list(range(STEP_COUNT)),
        "series": [{"name": inputs.shape.title(), "y": [round(v, 4) for v in values]}],
        "x_label": "Step",
        "y_label": "Value",
    }
    breakdown: dict[str, Any] = {
        "columns": [
            {"key": "step", "label": "Step", "type": "number"},
            {"key": "value", "label": "Value", "type": "number"},
        ],
        "rows": [
            {"step": step, "value": round(value, 4)}
            for step, value in enumerate(values)
        ],
    }
    return Outputs(
        peak_value=round(peak, 4),
        growth_chart=chart,
        breakdown=breakdown,
    )
