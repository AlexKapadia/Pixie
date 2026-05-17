"""Pydantic models for {{TOOL_NAME}}."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Inputs(BaseModel):
    scale: float = 100.0
    intensity: float = 1.5
    shape: str = "linear"


class RunRequest(BaseModel):
    # Pixie sends {"run_id": "...", "inputs": {...}} per the decisions log.
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


class Outputs(BaseModel):
    peak_value: float
    growth_chart: dict[str, Any]
    breakdown: dict[str, Any]
