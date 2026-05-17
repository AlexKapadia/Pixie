"""FastAPI app for {{TOOL_NAME}}.

When ``API_KEY`` is not set, ``/run`` returns a structured
``secret_missing`` error so the Pixie renderer can deep-link the user
to the settings page. The validator's sample run uses the configured
key when present; without one it gets the same friendly error and the
overall verdict stays at ``warn`` (set the secret to unlock ``pass``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel

from .client import UpstreamError, call_upstream

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))

DEFAULT_UPSTREAM_URL = os.environ.get(
    "{{PACKAGE}}_UPSTREAM_URL", "https://httpbin.org/post"
)


class Inputs(BaseModel):
    prompt: str = "ping"


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _result_pairs(values: dict[str, Any]) -> dict[str, Any]:
    return {
        "pairs": [
            {"key": key, "value": value} for key, value in values.items()
        ]
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
        inputs = payload.inputs or Inputs.model_validate(
            {k: v for k, v in payload.model_dump(exclude_none=True).items()
             if k not in {"run_id", "inputs"}}
        )

        api_key = os.environ.get("API_KEY")
        if not api_key:
            return {
                "result": _result_pairs({
                    "status": "secret_missing",
                    "secret": "API_KEY",
                    "hint": "Set API_KEY via the Pixie settings page or the set-secret skill.",
                    "echo_prompt": inputs.prompt,
                }),
            }

        try:
            reply = await call_upstream(
                DEFAULT_UPSTREAM_URL,
                {"prompt": inputs.prompt},
                api_key=api_key,
            )
        except UpstreamError as exc:
            return {
                "result": _result_pairs({
                    "status": "upstream_error",
                    "error": str(exc),
                }),
            }

        body = reply.body if isinstance(reply.body, dict) else {"body": reply.body}
        flattened = {
            "status_code": reply.status_code,
            "attempts": reply.attempts,
        }
        for key, value in body.items():
            if isinstance(value, (str, int, float, bool)):
                flattened[key] = value
        return {"result": _result_pairs(flattened)}

    @app.post("/cancel")
    async def cancel(run_id: str) -> Response:
        return Response(status_code=204)

    return app
