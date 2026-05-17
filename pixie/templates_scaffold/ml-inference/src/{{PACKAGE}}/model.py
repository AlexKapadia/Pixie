"""Lazy model loader for {{TOOL_NAME}}.

Models are large and slow to load; we cache the loaded model at module
scope and reuse it across requests for the lifetime of the worker. The
warm-keep window in ``tool.json`` is set to 30 minutes for this reason.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("{{PACKAGE}}.model")

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
MODELS_DIR = TOOL_DIR / "models"

_MODEL_CACHE: dict[str, Any] = {}


def model_path(name: str = "classifier.onnx") -> Path:
    return MODELS_DIR / name


def model_is_present(name: str = "classifier.onnx") -> bool:
    path = model_path(name)
    return path.is_file() and path.stat().st_size > 0


def load_model(name: str = "classifier.onnx") -> Any | None:
    """Return a loaded model or ``None`` if the weights are not on disk.

    The default scaffold ships *without* model weights so the tool
    validates immediately on a fresh clone. Run
    ``uv run python scripts/download-model.py`` to fetch a real model
    and re-enable inference.
    """

    cached = _MODEL_CACHE.get(name)
    if cached is not None:
        return cached

    path = model_path(name)
    if not path.is_file():
        logger.info("model %s missing; falling back to deterministic stub", path)
        return None

    # Real loading lives here when the author swaps in their framework.
    # The stub below treats the file's sha256 as the model identity so
    # the cache key changes when the file changes.
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    loaded = {"identity": digest, "path": str(path)}
    _MODEL_CACHE[name] = loaded
    return loaded
