"""FastAPI app for {{TOOL_NAME}}.

Accepts a base64-encoded file input, materialises it under
``data/tmp/``, invokes the wrapped CLI, and returns the output as a
``file`` output (``{filename, data}``). The CLI binary's presence is
detected at request time so the tool boots even if the user hasn't
installed it yet.
"""
from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel, create_model, model_validator
from typing import ClassVar, Optional

from .runner import (
    CLI_NAME,
    CliFailedError,
    CliMissingError,
    find_cli,
    invoke,
)

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))
TMP_ROOT = TOOL_DIR / "data" / "tmp"


# --- dynamic per-tool Inputs model ------------------------------------------

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


def _materialise(value: str | None, target_dir: Path) -> Path | None:
    if not value:
        return None
    if value.startswith("data:"):
        try:
            _, encoded = value.split(",", 1)
        except ValueError:
            return None
    else:
        encoded = value
    try:
        raw = base64.b64decode(encoded)
    except (ValueError, base64.binascii.Error):
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    in_path = target_dir / "input.bin"
    in_path.write_bytes(raw)
    return in_path


def _file_output(name: str, payload: bytes) -> dict[str, Any]:
    return {
        "filename": name,
        "data": "data:application/octet-stream;base64,"
        + base64.b64encode(payload).decode("ascii"),
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

        if find_cli() is None:
            return {
                "result": _file_output(
                    "cli-missing.txt",
                    (
                        f"{CLI_NAME} is not installed on this machine.\n"
                        "Install it and re-run, or replace CLI_NAME in "
                        f"src/{{PACKAGE}}/runner.py with a different binary."
                    ).encode("utf-8"),
                ),
            }

        with tempfile.TemporaryDirectory(dir=str(TMP_ROOT), prefix="run-") if TMP_ROOT.exists() else tempfile.TemporaryDirectory(prefix="{{PACKAGE}}-") as tmp:
            tmp_path = Path(tmp)
            source = _materialise(inputs.source, tmp_path)
            if source is None:
                source = tmp_path / "input.bin"
                source.write_bytes(b"")
            output = tmp_path / "output.bin"
            try:
                invoke(source, output, inputs.extra_args)
            except CliMissingError as exc:
                return {
                    "result": _file_output(
                        "cli-missing.txt", str(exc).encode("utf-8")
                    ),
                }
            except CliFailedError as exc:
                return {
                    "result": _file_output(
                        "cli-error.txt", str(exc).encode("utf-8")
                    ),
                }
            payload_bytes = output.read_bytes() if output.exists() else b""
            return {"result": _file_output("output.bin", payload_bytes)}

    @app.post("/cancel")
    async def cancel(run_id: str) -> Response:
        return Response(status_code=204)

    return app
