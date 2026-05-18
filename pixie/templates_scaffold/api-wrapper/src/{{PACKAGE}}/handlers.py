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
from pydantic import BaseModel, create_model, model_validator
from typing import ClassVar, Optional

from .client import UpstreamError, call_upstream

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))

DEFAULT_UPSTREAM_URL = os.environ.get(
    "{{PACKAGE}}_UPSTREAM_URL", "https://httpbin.org/post"
)


# --- dynamic per-tool Inputs model ------------------------------------------
# Built from tool.json so schema defaults are honoured and the dashboard
# can send ``null`` for keys with defaults.

_PY_TYPE: dict[str, type] = {
    "text": str, "textarea": str, "select": str, "radio": str,
    "colour": str, "date": str, "time": str, "datetime": str,
    "number": float, "slider": float,
    "checkbox": bool, "toggle": bool,
    "multiselect": list, "date_range": list,
    "file": str, "image": str, "audio": str,
}


def _resolve_numeric_type(spec: dict[str, Any]) -> type:
    """Return int when a number/slider has integer-valued step and bounds."""
    step = spec.get("step")
    default = spec.get("default")
    candidates = [step, default, spec.get("min"), spec.get("max")]
    if any(isinstance(v, float) and not v.is_integer() for v in candidates if v is not None):
        return float
    if isinstance(step, int) or (isinstance(step, float) and step.is_integer()):
        return int
    return float


class _PixieInputsBase(BaseModel):
    """Base for the dynamic Inputs model. Drops ``None`` for keys with a
    schema default so the pydantic default kicks in."""
    _schema_defaults: ClassVar[set[str]] = set()

    @model_validator(mode="before")
    @classmethod
    def _drop_none_with_default(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items()
                    if not (v is None and k in cls._schema_defaults)}
        return data


def _build_inputs_model(schema: dict[str, Any]) -> type[BaseModel]:
    defaults_set: set[str] = set()
    fields: dict[str, tuple[Any, Any]] = {}
    for spec in schema.get("inputs", []) or []:
        key = spec.get("key")
        if not key:
            continue
        kind = spec.get("type")
        if kind in {"number", "slider"}:
            py_type = _resolve_numeric_type(spec)
        else:
            py_type = _PY_TYPE.get(kind, Any)
        if "default" in spec:
            default = spec["default"]
            defaults_set.add(key)
        else:
            default = None
        fields[key] = (Optional[py_type], default)
    model = create_model("Inputs", __base__=_PixieInputsBase, **fields)
    model._schema_defaults = defaults_set
    return model


Inputs = _build_inputs_model(SCHEMA)


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: dict[str, Any] | None = None


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
        raw = payload.inputs
        if raw is None:
            raw = {k: v for k, v in payload.model_dump(exclude_none=True).items()
                   if k not in {"run_id", "inputs"}}
        inputs = Inputs.model_validate(raw or {})

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
