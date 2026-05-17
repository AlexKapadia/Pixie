"""FastAPI app for the graph algorithms playground."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from .algorithms import (
    layout, parse_edges, run_communities, run_dijkstra, run_max_flow,
)

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class Inputs(BaseModel):
    model_config = {"extra": "allow"}
    edges: str = "a-b:1\nb-c:2\na-c:5\nc-d:1\nb-d:4"
    algorithm: str = "dijkstra"
    source: str = "a"
    sink: str | None = "d"


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _network_payload(graph, pos, highlighted_edges, membership) -> dict[str, Any]:
    palette = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6"]
    nodes = []
    for n in graph.nodes:
        x, y = pos.get(n, (0.0, 0.0))
        node_payload = {"id": n, "label": n, "x": x, "y": y}
        if membership and n in membership:
            node_payload["color"] = palette[membership[n] % len(palette)]
        nodes.append(node_payload)
    edges = []
    for u, v, data in graph.edges(data=True):
        edge_payload = {
            "source": u, "target": v,
            "weight": round(float(data.get("weight", 1.0)), 4),
        }
        if tuple(sorted([u, v])) in highlighted_edges:
            edge_payload["color"] = "#ef4444"
            edge_payload["highlighted"] = True
        edges.append(edge_payload)
    return {"nodes": nodes, "edges": edges}


def _compute(inputs: Inputs) -> dict[str, Any]:
    try:
        graph = parse_edges(inputs.edges)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if len(graph) == 0:
        raise HTTPException(status_code=422, detail="No edges supplied.")

    pos = layout(graph)
    highlighted: set = set()
    membership: dict[str, int] = {}

    if inputs.algorithm == "dijkstra":
        if inputs.source not in graph:
            raise HTTPException(status_code=422, detail=f"source {inputs.source!r} not in graph")
        outcome = run_dijkstra(graph, inputs.source)
        highlighted = outcome["highlighted_edges"]
        table_columns = [
            {"key": "node", "label": "Node", "type": "string"},
            {"key": "distance", "label": "Distance", "type": "number"},
            {"key": "path", "label": "Path", "type": "string"},
        ]
        rows = outcome["rows"]
        summary = outcome["summary"]
    elif inputs.algorithm == "max_flow":
        if inputs.source not in graph or (inputs.sink or "") not in graph:
            raise HTTPException(status_code=422, detail="source and sink must both be nodes in the graph")
        outcome = run_max_flow(graph, inputs.source, inputs.sink or "")
        highlighted = outcome["highlighted_edges"]
        table_columns = [
            {"key": "from", "label": "From", "type": "string"},
            {"key": "to", "label": "To", "type": "string"},
            {"key": "flow", "label": "Flow", "type": "number"},
        ]
        rows = outcome["rows"]
        summary = outcome["summary"]
    elif inputs.algorithm == "community_detection":
        outcome = run_communities(graph)
        membership = outcome["membership"]
        table_columns = [
            {"key": "node", "label": "Node", "type": "string"},
            {"key": "community", "label": "Community", "type": "number"},
        ]
        rows = outcome["rows"]
        summary = outcome["summary"]
    else:
        raise HTTPException(status_code=422, detail=f"unknown algorithm {inputs.algorithm!r}")

    return {
        "graph_view": _network_payload(graph, pos, highlighted, membership),
        "details": {"columns": table_columns, "rows": rows, "downloadable": True},
        "summary": {"pairs": summary},
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
