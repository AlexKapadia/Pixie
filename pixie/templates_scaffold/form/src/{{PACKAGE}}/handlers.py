"""FastAPI app construction for {{TOOL_NAME}}."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Response

from .compute import compute
from .models import Inputs, RunRequest

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


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
        return compute(inputs).model_dump()

    @app.post("/cancel")
    async def cancel(run_id: str) -> Response:
        return Response(status_code=204)

    return app
