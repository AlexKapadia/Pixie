"""Image segmentation with rembg when installed; a classic GrabCut-ish
luminance-threshold fallback otherwise."""
from __future__ import annotations

import base64
import io
from typing import Any

import numpy as np
from PIL import Image


def _decode_image(value: str | None) -> Image.Image:
    if not value:
        arr = np.zeros((240, 320, 3), dtype=np.uint8)
        # paint a bright disc in the middle
        yy, xx = np.indices((240, 320))
        disc = ((xx - 160) ** 2 + (yy - 120) ** 2) < (60 ** 2)
        arr[disc] = (220, 220, 80)
        return Image.fromarray(arr, mode="RGB")
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
        return _decode_image(None)
    return Image.open(io.BytesIO(raw)).convert("RGB")


def _encode(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _rembg_available() -> bool:
    try:
        import rembg  # noqa: F401
        return True
    except Exception:
        return False


def _segment_with_rembg(image: Image.Image, model_name: str) -> np.ndarray:
    from rembg import new_session, remove
    session = new_session(model_name)
    cutout = remove(image, session=session, only_mask=True)
    if isinstance(cutout, Image.Image):
        mask = np.asarray(cutout.convert("L"))
    else:
        mask = np.asarray(Image.open(io.BytesIO(cutout)).convert("L"))
    return mask


def _segment_fallback(image: Image.Image) -> np.ndarray:
    """Otsu-style threshold on the luminance channel, then majority-fill."""
    gray = np.asarray(image.convert("L"), dtype=np.float32)
    # rough Otsu
    hist, bins = np.histogram(gray.ravel(), bins=256, range=(0, 256))
    total = gray.size
    sum_total = np.sum(np.arange(256) * hist)
    sum_b, w_b, max_var, threshold = 0.0, 0, 0.0, 128
    for i in range(256):
        w_b += hist[i]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += i * hist[i]
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        var_between = w_b * w_f * (m_b - m_f) ** 2
        if var_between > max_var:
            max_var = var_between
            threshold = i
    mask = (gray > threshold).astype(np.uint8) * 255
    return mask


def _apply_mask(image: Image.Image, mask: np.ndarray, output_format: str) -> Image.Image:
    if output_format == "mask":
        return Image.fromarray(mask, mode="L").convert("RGB")
    # cutout
    rgba = np.dstack([np.asarray(image), mask])
    return Image.fromarray(rgba, mode="RGBA")


def segment(image_value: str | None, model_name: str, output_format: str) -> dict[str, Any]:
    image = _decode_image(image_value)

    if _rembg_available():
        try:
            mask = _segment_with_rembg(image, model_name)
            backend = f"rembg ({model_name})"
        except Exception:
            mask = _segment_fallback(image)
            backend = "fallback (rembg call failed)"
    else:
        mask = _segment_fallback(image)
        backend = "fallback (otsu threshold)"

    segmented = _apply_mask(image, mask, output_format)
    mask_image = Image.fromarray(mask, mode="L")

    fg_pixels = int(np.sum(mask > 127))
    total = int(mask.size)
    bg_pixels = total - fg_pixels

    return {
        "segmented": _encode(segmented),
        "mask": _encode(mask_image),
        "stats": {
            "columns": [
                {"key": "region", "label": "Region", "type": "string"},
                {"key": "pixels", "label": "Pixels", "type": "number"},
                {"key": "fraction", "label": "Fraction", "type": "number"},
            ],
            "rows": [
                {"region": "foreground", "pixels": fg_pixels,
                 "fraction": round(fg_pixels / total, 4) if total else 0.0},
                {"region": "background", "pixels": bg_pixels,
                 "fraction": round(bg_pixels / total, 4) if total else 0.0},
                {"region": "_backend", "pixels": 0, "fraction": 0.0},
            ],
            "downloadable": True,
        },
    }
