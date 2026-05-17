"""Download the model weights for {{TOOL_NAME}}.

Run once on a fresh clone:

    uv run python scripts/download-model.py

The default implementation pulls a small placeholder (~1 KB) so the
script is testable offline. Replace the URL with your real model when
ready, and update ``MODEL_FILENAME`` to match.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

MODEL_URL = (
    "https://raw.githubusercontent.com/onnx/models/main/"
    "validated/vision/classification/mnist/model/mnist-12.onnx"
)
MODEL_FILENAME = "classifier.onnx"
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"


def main() -> int:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    target = MODEL_DIR / MODEL_FILENAME
    if target.exists() and target.stat().st_size > 0:
        print(f"already downloaded: {target} ({target.stat().st_size} bytes)")
        return 0
    print(f"downloading {MODEL_URL} -> {target}")
    try:
        urllib.request.urlretrieve(MODEL_URL, target)
    except Exception as exc:
        print(f"download failed: {exc}", file=sys.stderr)
        return 1
    print(f"done ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
