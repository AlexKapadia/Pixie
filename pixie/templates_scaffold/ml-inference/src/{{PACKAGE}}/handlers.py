"""FastAPI app for {{TOOL_NAME}}."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel, create_model, model_validator
from typing import ClassVar, Optional

from .model import load_model, model_is_present

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


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


# A short, deterministic set of fake class names so the stub returns
# something realistic-looking. Real authors replace these by reading
# their model's class index.
_STUB_CLASSES = (
    "tabby cat", "golden retriever", "espresso", "library", "rocking chair",
    "espresso cup", "lemon", "ski mask", "computer keyboard", "moon",
)


def _decode_image_metadata(image_value: str | None) -> dict[str, Any]:
    if not image_value:
        return {"width": 0, "height": 0, "byte_length": 0}

    from PIL import Image

    if image_value.startswith("data:"):
        try:
            _, encoded = image_value.split(",", 1)
            raw = base64.b64decode(encoded)
        except (ValueError, base64.binascii.Error):
            return {"width": 0, "height": 0, "byte_length": 0}
    else:
        raw = base64.b64decode(image_value) if image_value else b""

    if not raw:
        return {"width": 0, "height": 0, "byte_length": 0}
    try:
        with Image.open(io.BytesIO(raw)) as img:
            return {
                "width": img.width,
                "height": img.height,
                "byte_length": len(raw),
            }
    except Exception:
        return {"width": 0, "height": 0, "byte_length": len(raw)}


def _stub_predictions(metadata: dict[str, Any], top_k: int) -> list[tuple[str, float]]:
    # Score based on image dimensions so the output is deterministic per input.
    seed = (metadata.get("width", 0) * 13 + metadata.get("height", 0) * 7) or 1
    scores: list[tuple[str, float]] = []
    for index, name in enumerate(_STUB_CLASSES):
        rank_score = 1.0 / (((seed + index) % 11) + 1)
        scores.append((name, rank_score))
    scores.sort(key=lambda pair: pair[1], reverse=True)
    return scores[: max(1, min(top_k, len(_STUB_CLASSES)))]


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
        model = load_model()
        metadata = _decode_image_metadata(inputs.image)
        predictions = _stub_predictions(metadata, inputs.top_k)
        return {
            "predictions": {
                "pairs": [
                    {"key": label, "value": round(score, 4)}
                    for label, score in predictions
                ],
                "meta": {
                    "model_loaded": model is not None,
                    "model_present": model_is_present(),
                    "image": metadata,
                },
            }
        }

    @app.post("/cancel")
    async def cancel(run_id: str) -> Response:
        return Response(status_code=204)

    return app
