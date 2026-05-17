"""FastAPI app for the Open-Meteo forecast tool."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from .client import describe, fetch_forecast

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class LocationInput(BaseModel):
    model_config = {"extra": "allow"}
    lat: float | None = None
    lng: float | None = None


class Inputs(BaseModel):
    model_config = {"extra": "allow"}
    location: Any = None
    days_ahead: int = 7


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _coords(location: Any) -> tuple[float, float]:
    if location is None:
        return (51.5074, -0.1278)
    if isinstance(location, (list, tuple)) and len(location) >= 2:
        return (float(location[0]), float(location[1]))
    if isinstance(location, dict):
        location = LocationInput(**location)
    lat = location.lat if location.lat is not None else 51.5074
    lng = location.lng if location.lng is not None else -0.1278
    return float(lat), float(lng)


async def _compute(inputs: Inputs) -> dict[str, Any]:
    lat, lng = _coords(inputs.location)
    try:
        data = await fetch_forecast(lat, lng, inputs.days_ahead)
    except httpx_error_types() as exc:  # type: ignore[misc]
        raise HTTPException(status_code=502, detail=f"Open-Meteo request failed: {exc}") from exc

    daily = data.get("daily") or {}
    dates: list[str] = daily.get("time") or []
    t_max: list[float] = daily.get("temperature_2m_max") or []
    t_min: list[float] = daily.get("temperature_2m_min") or []
    t_mean: list[float] = daily.get("temperature_2m_mean") or []
    precipitation: list[float] = daily.get("precipitation_sum") or []
    codes: list[int] = daily.get("weathercode") or []
    wind_max: list[float] = daily.get("windspeed_10m_max") or []
    current = data.get("current_weather") or {}

    temperature_chart = {
        "x": dates,
        "series": [
            {"name": "max", "y": t_max},
            {"name": "mean", "y": t_mean},
            {"name": "min", "y": t_min},
        ],
        "x_label": "date",
        "y_label": "°C",
    }
    precipitation_chart = {
        "x": dates,
        "series": [{"name": "precipitation", "y": precipitation}],
        "x_label": "date",
        "y_label": "mm",
    }

    today_summary = {"pairs": {
        "date": dates[0] if dates else "n/a",
        "conditions": describe(codes[0]) if codes else "n/a",
        "temperature_max_c": t_max[0] if t_max else None,
        "temperature_min_c": t_min[0] if t_min else None,
        "precipitation_mm": precipitation[0] if precipitation else None,
        "wind_max_kmh": wind_max[0] if wind_max else None,
        "current_temperature_c": current.get("temperature"),
    }}

    location_marker = {
        "points": [{
            "lat": lat,
            "lng": lng,
            "label": f"{lat:.4f}, {lng:.4f}",
        }],
    }

    return {
        "temperature": temperature_chart,
        "precipitation": precipitation_chart,
        "today": today_summary,
        "location_marker": location_marker,
    }


def httpx_error_types():
    import httpx
    return (httpx.HTTPError,)


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
        return await _compute(inputs)

    @app.post("/cancel")
    async def cancel(run_id: str) -> Response:
        return Response(status_code=204)

    return app
