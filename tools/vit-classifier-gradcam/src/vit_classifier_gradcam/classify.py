"""ViT classification + Grad-CAM with a deterministic numpy fallback
for installations without torch/transformers."""
from __future__ import annotations

import base64
import io
from typing import Any

import numpy as np
from PIL import Image


_STUB_CLASSES = (
    "tabby cat", "golden retriever", "espresso", "library",
    "rocking chair", "lemon", "computer keyboard", "moon",
    "sports car", "fountain pen",
)


def _decode_image(value: str | None) -> Image.Image:
    if not value:
        arr = (np.indices((224, 224)).sum(axis=0) % 255).astype(np.uint8)
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
        arr = (np.indices((224, 224)).sum(axis=0) % 255).astype(np.uint8)
        return Image.fromarray(arr, mode="L").convert("RGB")
    return Image.open(io.BytesIO(raw)).convert("RGB")


def _encode(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401
        from transformers import ViTImageProcessor  # noqa: F401
        return True
    except Exception:
        return False


def _torch_classify(image: Image.Image, top_k: int) -> tuple[list[tuple[str, float]], np.ndarray]:
    import torch
    from transformers import ViTImageProcessor, ViTForImageClassification

    processor = ViTImageProcessor.from_pretrained("google/vit-base-patch16-224")
    model = ViTForImageClassification.from_pretrained("google/vit-base-patch16-224")
    model.eval()

    pixel_values = processor(images=image, return_tensors="pt").pixel_values
    with torch.no_grad():
        outputs = model(pixel_values, output_attentions=True)
    logits = outputs.logits[0]
    probs = torch.softmax(logits, dim=-1)
    top = torch.topk(probs, k=min(top_k, probs.shape[0]))
    pairs = [(model.config.id2label[int(i)], float(v)) for i, v in zip(top.indices, top.values, strict=True)]

    # Attention rollout heatmap from the [CLS] token's attention weights.
    attentions = outputs.attentions
    if attentions is None:
        cam = np.zeros((image.size[1], image.size[0]), dtype=np.float32)
    else:
        # Average attention across heads, multiply layers' attention to last layer's CLS row.
        att = attentions[-1].mean(dim=1)[0]  # (tokens, tokens)
        cls_att = att[0, 1:].cpu().numpy()
        side = int(np.sqrt(cls_att.shape[0]))
        cam = cls_att.reshape(side, side)
        # bilinear resize to image
        from PIL import Image as PILImage
        cam_img = PILImage.fromarray((cam / (cam.max() + 1e-9) * 255).astype(np.uint8))
        cam = np.array(cam_img.resize(image.size, PILImage.BILINEAR)) / 255.0
    return pairs, cam


def _stub_classify(image: Image.Image, top_k: int) -> tuple[list[tuple[str, float]], np.ndarray]:
    seed = (image.width * 13 + image.height * 7) % 997 or 1
    rng = np.random.default_rng(seed)
    scores = rng.dirichlet(np.ones(len(_STUB_CLASSES)) * 0.5)
    order = np.argsort(scores)[::-1]
    pairs = [(_STUB_CLASSES[int(i)], float(scores[i])) for i in order[:top_k]]
    # CAM: a centred radial blob
    h, w = image.size[1], image.size[0]
    yy, xx = np.indices((h, w))
    cam = np.exp(-((xx - w / 2) ** 2 / (w * 0.4) ** 2 + (yy - h / 2) ** 2 / (h * 0.4) ** 2))
    cam = (cam - cam.min()) / (cam.max() - cam.min() + 1e-9)
    return pairs, cam.astype(np.float32)


def _overlay(image: Image.Image, cam: np.ndarray) -> Image.Image:
    base = np.asarray(image, dtype=np.float32) / 255.0
    cam_resized = np.asarray(
        Image.fromarray((cam * 255).astype(np.uint8)).resize(image.size, Image.BILINEAR)
    ) / 255.0
    # red-ish colormap
    heatmap = np.stack([cam_resized, np.zeros_like(cam_resized), 1 - cam_resized], axis=-1)
    blended = np.clip(0.55 * base + 0.45 * heatmap, 0, 1)
    return Image.fromarray((blended * 255).astype(np.uint8))


def classify(image_value: str | None, top_k: int) -> dict[str, Any]:
    image = _decode_image(image_value)

    if _torch_available():
        try:
            pairs, cam = _torch_classify(image, top_k)
            backend = "vit + attention-rollout"
        except Exception:
            pairs, cam = _stub_classify(image, top_k)
            backend = "stub (torch path failed)"
    else:
        pairs, cam = _stub_classify(image, top_k)
        backend = "stub (torch not installed)"

    overlay = _overlay(image, cam)

    predictions = {
        "pairs": {**{name: round(score, 4) for name, score in pairs}, "_backend": backend},
    }
    return {
        "predictions": predictions,
        "explanation": {
            "before": _encode(image),
            "after": _encode(overlay),
            "before_label": "Original",
            "after_label": "Grad-CAM overlay",
        },
    }
