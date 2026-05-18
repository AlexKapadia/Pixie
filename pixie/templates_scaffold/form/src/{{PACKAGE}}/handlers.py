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
        # The Inputs model is built dynamically from tool.json so a null
        # sent by the dashboard for a key with a schema default resolves
        # to the default. Legacy "flat" payloads (no wrapping inputs)
        # still work via the extra="allow" fall-back.
        raw = payload.inputs
        if raw is None:
            flat = payload.model_dump(exclude_none=True)
            flat.pop("run_id", None)
            flat.pop("inputs", None)
            raw = flat
        typed_inputs = Inputs.model_validate(raw or {})
        return compute(typed_inputs).model_dump()

    @app.post("/cancel")
    async def cancel(run_id: str) -> Response:
        return Response(status_code=204)

    return app
