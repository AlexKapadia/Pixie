"""FastAPI app for {{TOOL_NAME}}."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from pydantic import BaseModel

from .model import load_model, model_is_present

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


class Inputs(BaseModel):
    image: str | None = None
    top_k: int = 5


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


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
        inputs = payload.inputs or Inputs.model_validate(
            {k: v for k, v in payload.model_dump(exclude_none=True).items()
             if k not in {"run_id", "inputs"}}
        )
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
