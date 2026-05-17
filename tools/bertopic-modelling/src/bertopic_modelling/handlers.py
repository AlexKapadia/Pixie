"""FastAPI app for BERTopic-based topic modelling."""
from __future__ import annotations

import base64
import io
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel

from .topics import fit

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class Inputs(BaseModel):
    dataset_csv: str | None = None
    text_column: str = "text"
    num_topics: int = 6


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _read_csv(raw: str | None) -> pd.DataFrame:
    if raw is None:
        return _sample()
    try:
        if raw.startswith("data:"):
            _, _, b64 = raw.partition(",")
            return pd.read_csv(io.BytesIO(base64.b64decode(b64)))
        path = Path(raw)
        if path.is_file():
            return pd.read_csv(path)
        return pd.read_csv(io.StringIO(raw))
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return _sample()


def _sample() -> pd.DataFrame:
    docs = [
        "the central bank raised interest rates to fight inflation",
        "monetary policy and interest rates dominate the headlines",
        "inflation continues to weigh on consumer confidence",
        "the new smartphone features an improved camera and battery",
        "smartphone launch event drew millions of viewers",
        "battery life and camera quality lead the upgrades this year",
        "researchers developed a new protein folding algorithm",
        "protein structure prediction is now faster than ever",
        "machine learning advances are accelerating drug discovery",
        "the football match ended in a dramatic last-minute goal",
        "the team secured a victory in the final seconds",
        "supporters celebrated the late comeback win at the stadium",
    ]
    return pd.DataFrame({"text": docs})


def _compute(inputs: Inputs) -> dict[str, Any]:
    frame = _read_csv(inputs.dataset_csv)
    if inputs.text_column not in frame.columns:
        raise KeyError(f"text column {inputs.text_column!r} missing")
    documents = [str(t) for t in frame[inputs.text_column].fillna("").tolist() if str(t).strip()]
    result = fit(documents, inputs.num_topics)

    counts = Counter(result.topic_per_document)
    topic_rows = []
    for topic_id in sorted(counts.keys()):
        words = result.top_words_per_topic.get(topic_id, [])
        topic_rows.append({
            "topic": int(topic_id),
            "count": int(counts[topic_id]),
            "top_words": ", ".join(words[:8]),
        })

    topics_table = {
        "columns": [
            {"key": "topic", "label": "Topic", "type": "number"},
            {"key": "count", "label": "Documents", "type": "number"},
            {"key": "top_words", "label": "Top words", "type": "string"},
        ],
        "rows": topic_rows,
    }
    topic_sizes = {
        "x": [str(row["topic"]) for row in topic_rows],
        "series": [{"name": "documents", "y": [row["count"] for row in topic_rows]}],
        "x_label": "topic",
        "y_label": "documents",
    }
    by_topic: dict[int, list[dict[str, float]]] = {}
    for topic_id, point in zip(result.topic_per_document, result.embedding_2d):
        by_topic.setdefault(int(topic_id), []).append({"x": float(point[0]), "y": float(point[1])})
    projection = {
        "series": [
            {"name": f"topic {topic_id}", "points": pts}
            for topic_id, pts in sorted(by_topic.items())
        ],
        "x_label": "dim 1",
        "y_label": "dim 2",
    }
    return {
        "topics_table": topics_table,
        "topic_sizes": topic_sizes,
        "projection": projection,
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
