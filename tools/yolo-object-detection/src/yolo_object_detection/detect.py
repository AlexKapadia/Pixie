"""YOLO detection wrapper with a deterministic numpy fallback for when
ultralytics is not installed (keeps the tool validating without 1GB of
torch wheels)."""
from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
MODELS_DIR = TOOL_DIR / "models"


def _decode_image(value: str | None) -> Image.Image:
    if not value:
        # generate a deterministic placeholder so the tool always returns *something*
        arr = (np.indices((240, 320)).sum(axis=0) % 255).astype(np.uint8)
        return Image.fromarray(arr, mode="L").convert("RGB")
    raw: bytes
    if value.startswith("data:"):
        try:
            _, encoded = value.split(",", 1)
            raw = base64.b64decode(encoded)
        except (ValueError, base64.binascii.Error):
            raw = b""
    else:
        try:
            raw = base64.b64decode(value)
        except (ValueError, base64.binascii.Error):
            raw = b""
    if not raw:
        arr = (np.indices((240, 320)).sum(axis=0) % 255).astype(np.uint8)
        return Image.fromarray(arr, mode="L").convert("RGB")
    return Image.open(io.BytesIO(raw)).convert("RGB")


def _encode_image(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _ultralytics_available() -> bool:
    try:
        import ultralytics  # noqa: F401
        return True
    except Exception:
        return False


def _run_ultralytics(image: Image.Image, model_name: str, confidence: float) -> list[dict[str, Any]]:
    from ultralytics import YOLO  # type: ignore
    weights_path = MODELS_DIR / f"{model_name}.pt"
    model = YOLO(str(weights_path) if weights_path.exists() else f"{model_name}.pt")
    arr = np.array(image)
    results = model.predict(arr, conf=confidence / 100.0, verbose=False)
    out: list[dict[str, Any]] = []
    if not results:
        return out
    r = results[0]
    names = r.names if hasattr(r, "names") else {}
    boxes = getattr(r, "boxes", None)
    if boxes is None:
        return out
    for cls_idx, conf, xyxy in zip(boxes.cls.tolist(), boxes.conf.tolist(), boxes.xyxy.tolist(), strict=True):
        x1, y1, x2, y2 = xyxy
        out.append({
            "class_name": names.get(int(cls_idx), str(int(cls_idx))),
            "confidence": round(float(conf), 4),
            "x1": round(float(x1), 1),
            "y1": round(float(y1), 1),
            "x2": round(float(x2), 1),
            "y2": round(float(y2), 1),
        })
    return out


def _stub_detect(image: Image.Image, confidence: float) -> list[dict[str, Any]]:
    """Deterministic stub: returns two boxes derived from image size, so
    the wiring exercises end-to-end without weights on disk."""

    w, h = image.size
    seed_conf = ((w * h) % 1000) / 1000.0
    base = 0.95 - 0.4 * seed_conf
    detections = [
        {
            "class_name": "object", "confidence": round(base, 4),
            "x1": round(w * 0.1, 1), "y1": round(h * 0.1, 1),
            "x2": round(w * 0.5, 1), "y2": round(h * 0.5, 1),
        },
        {
            "class_name": "object", "confidence": round(base - 0.2, 4),
            "x1": round(w * 0.55, 1), "y1": round(h * 0.4, 1),
            "x2": round(w * 0.9, 1), "y2": round(h * 0.9, 1),
        },
    ]
    return [d for d in detections if d["confidence"] * 100 >= confidence]


def _annotate(image: Image.Image, detections: list[dict[str, Any]]) -> Image.Image:
    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for d in detections:
        coords = (d["x1"], d["y1"], d["x2"], d["y2"])
        draw.rectangle(coords, outline="red", width=3)
        label = f"{d['class_name']} {d['confidence']:.2f}"
        draw.text((d["x1"] + 4, d["y1"] + 4), label, fill="red", font=font)
    return annotated


def detect(image_value: str | None, confidence_threshold: float, model_name: str) -> dict[str, Any]:
    image = _decode_image(image_value)

    if _ultralytics_available():
        try:
            detections = _run_ultralytics(image, model_name, confidence_threshold)
            backend = "ultralytics"
        except Exception:
            detections = _stub_detect(image, confidence_threshold)
            backend = "stub (ultralytics call failed)"
    else:
        detections = _stub_detect(image, confidence_threshold)
        backend = "stub (ultralytics not installed)"

    annotated = _annotate(image, detections)

    counts: dict[str, int] = {}
    for d in detections:
        counts[d["class_name"]] = counts.get(d["class_name"], 0) + 1

    return {
        "annotated": _encode_image(annotated),
        "detections": {
            "columns": [
                {"key": "class_name", "label": "Class", "type": "string"},
                {"key": "confidence", "label": "Confidence", "type": "number"},
                {"key": "x1", "label": "x1", "type": "number"},
                {"key": "y1", "label": "y1", "type": "number"},
                {"key": "x2", "label": "x2", "type": "number"},
                {"key": "y2", "label": "y2", "type": "number"},
            ],
            "rows": detections,
            "downloadable": True,
        },
        "summary": {
            "pairs": {
                "backend": backend,
                "model": model_name,
                "image width": image.width,
                "image height": image.height,
                "detections": len(detections),
                "classes": len(counts),
            },
        },
    }
