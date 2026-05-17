"""FastAPI app for the TSP route optimiser."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel

from .solver import distance_matrix, haversine_km, solve

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class CityPoint(BaseModel):
    model_config = {"extra": "allow"}
    lat: float
    lng: float
    label: str | None = None


class Inputs(BaseModel):
    model_config = {"extra": "allow"}
    cities: Any = None
    return_to_start: bool = True


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _extract_points(cities: Any) -> list[CityPoint]:
    if cities is None:
        return []
    if isinstance(cities, dict):
        raw = cities.get("points") or cities.get("cities") or []
    else:
        raw = cities
    out: list[CityPoint] = []
    for entry in raw:
        if isinstance(entry, CityPoint):
            out.append(entry)
        elif isinstance(entry, dict):
            out.append(CityPoint(**entry))
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            out.append(CityPoint(lat=float(entry[0]), lng=float(entry[1])))
    return out


def _compute(inputs: Inputs) -> dict[str, Any]:
    cities = _extract_points(inputs.cities)
    if len(cities) < 2:
        return {
            "route_map": {"points": [{"lat": c.lat, "lng": c.lng, "label": c.label} for c in cities]},
            "total_distance_km": 0.0,
            "legs": {
                "columns": [
                    {"key": "from", "label": "From", "type": "string"},
                    {"key": "to", "label": "To", "type": "string"},
                    {"key": "km", "label": "Distance (km)", "type": "number"},
                ],
                "rows": [],
                "downloadable": True,
            },
        }

    points = [(c.lat, c.lng) for c in cities]
    order = solve(points, inputs.return_to_start)
    matrix = distance_matrix(points)

    route_points: list[dict[str, Any]] = []
    legs_rows: list[dict[str, Any]] = []
    total = 0.0
    for step, idx in enumerate(order):
        c = cities[idx]
        route_points.append({
            "lat": c.lat,
            "lng": c.lng,
            "label": c.label or f"City {idx + 1}",
        })
        if step > 0:
            prev = order[step - 1]
            d = float(matrix[prev, idx])
            total += d
            legs_rows.append({
                "from": cities[prev].label or f"City {prev + 1}",
                "to": cities[idx].label or f"City {idx + 1}",
                "km": round(d, 2),
            })

    return {
        "route_map": {"points": route_points},
        "total_distance_km": round(total, 2),
        "legs": {
            "columns": [
                {"key": "from", "label": "From", "type": "string"},
                {"key": "to", "label": "To", "type": "string"},
                {"key": "km", "label": "Distance (km)", "type": "number"},
            ],
            "rows": legs_rows,
            "downloadable": True,
        },
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
