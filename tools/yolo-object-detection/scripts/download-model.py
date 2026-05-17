"""Pre-download the YOLOv8 weights into ./models/.

Run with: ``uv run python scripts/download-model.py``
"""
from __future__ import annotations

import sys
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"


def main() -> int:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError:
        print("ultralytics not installed. Run `uv sync --group models` first.", file=sys.stderr)
        return 1
    for name in ("yolov8n", "yolov8s"):
        target = MODELS_DIR / f"{name}.pt"
        if target.exists():
            print(f"{target} already present, skipping")
            continue
        print(f"Fetching {name} weights via ultralytics...")
        model = YOLO(f"{name}.pt")
        # ultralytics caches into ~/.cache/ultralytics by default; copy into ./models/
        cached = Path(model.ckpt_path) if getattr(model, "ckpt_path", None) else None
        if cached and cached.is_file():
            target.write_bytes(cached.read_bytes())
            print(f"Saved -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
