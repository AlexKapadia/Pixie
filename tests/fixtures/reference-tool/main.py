"""Square-root reference tool.

Tiny synchronous tool used by the test suite to exercise check #12
(reference_fixtures_match). Honours the Pixie HTTP contract: ``/schema``,
``/run`` (wrapped or flat inputs), ``/healthz``, ``/stream``.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel

TOOL_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = TOOL_DIR / "tool.json"


class RunInputs(BaseModel):
    x: float


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: RunInputs | None = None


def _compute(payload: RunInputs) -> dict[str, Any]:
    x = float(payload.x)
    result = math.sqrt(x)
    return {
        "result": round(result, 6),
        "summary": f"sqrt({x}) = {result:.6f}",
    }


load_dotenv(TOOL_DIR / ".env", override=False)
app = FastAPI()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/schema")
def schema() -> Response:
    return Response(
        content=SCHEMA_PATH.read_text(encoding="utf-8"),
        media_type="application/json",
    )


@app.post("/run")
def run(body: RunRequest) -> dict[str, Any]:
    if body.inputs is not None:
        return _compute(body.inputs)
    extras = body.model_dump(exclude={"run_id", "inputs"})
    return _compute(RunInputs(**extras))


@app.get("/stream")
def stream() -> Response:
    return Response("event: end\ndata: {}\n\n", media_type="text/event-stream")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
