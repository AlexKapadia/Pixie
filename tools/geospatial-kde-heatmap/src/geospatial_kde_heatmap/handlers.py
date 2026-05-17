"""FastAPI app for the geospatial KDE heatmap."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel

from .kde import estimate, parse_csv

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))
MAX_HEATMAP_CELLS = 2500


class FilePayload(BaseModel):
    model_config = {"extra": "allow"}
    name: str | None = None
    content_base64: str | None = None
    content: str | None = None
    text: str | None = None


class Inputs(BaseModel):
    model_config = {"extra": "allow"}
    csv_file: FilePayload | str | dict[str, Any] | None = None
    bandwidth: float = 1.0
    grid_resolution: int = 60


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _read_csv_text(payload: Any) -> str:
    if payload is None:
        return _default_csv()
    if isinstance(payload, str):
        # Accept a data URL or a raw CSV string; data URLs aren't CSV so fall back.
        if payload.startswith("data:"):
            _, _, b64 = payload.partition(",")
            try:
                decoded = base64.b64decode(b64).decode("utf-8", errors="replace")
            except (ValueError, UnicodeDecodeError):
                return _default_csv()
            return decoded if "lat" in decoded.lower() else _default_csv()
        return payload
    if isinstance(payload, dict):
        payload = FilePayload(**payload)
    if payload.text:
        return payload.text
    if payload.content:
        return payload.content
    if payload.content_base64:
        try:
            decoded = base64.b64decode(payload.content_base64).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError):
            return _default_csv()
        return decoded if "lat" in decoded.lower() else _default_csv()
    return _default_csv()


def _default_csv() -> str:
    # Small London-ish point cloud so a no-file run still produces output.
    rows = ["lat,lng,weight"]
    rng = np.random.default_rng(0)
    centres = [(51.51, -0.12), (51.49, -0.07), (51.55, -0.18)]
    for lat0, lng0 in centres:
        for _ in range(40):
            lat = lat0 + float(rng.normal(0, 0.015))
            lng = lng0 + float(rng.normal(0, 0.02))
            rows.append(f"{lat:.5f},{lng:.5f},1")
    return "\n".join(rows)


def _heatmap_points(result: Any) -> list[dict[str, float]]:
    density = result.density
    g_lats, g_lngs = result.grid_lats, result.grid_lngs
    total_cells = density.size
    stride = max(1, int(np.ceil(np.sqrt(total_cells / MAX_HEATMAP_CELLS))))
    points: list[dict[str, float]] = []
    threshold = float(density.max()) * 0.05
    for i in range(0, density.shape[0], stride):
        for j in range(0, density.shape[1], stride):
            w = float(density[i, j])
            if w < threshold:
                continue
            points.append({
                "lat": float(g_lats[i]),
                "lng": float(g_lngs[j]),
                "weight": round(w, 6),
            })
    return points


def _compute(inputs: Inputs) -> dict[str, Any]:
    csv_text = _read_csv_text(inputs.csv_file)
    lats, lngs, weights = parse_csv(csv_text)
    result = estimate(lats, lngs, weights, inputs.bandwidth, int(inputs.grid_resolution))

    flat_density = result.density.ravel()
    sample_values = flat_density[flat_density > flat_density.max() * 0.01].tolist()

    return {
        "heatmap": {"points": _heatmap_points(result)},
        "peak": {"pairs": {
            "latitude": round(result.peak_lat, 6),
            "longitude": round(result.peak_lng, 6),
            "peak_density": round(result.peak_density, 6),
            "sample_count": int(lats.size),
        }},
        "density_histogram": {
            "values": [round(float(v), 6) for v in sample_values],
            "x_label": "density",
            "y_label": "cell count",
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
