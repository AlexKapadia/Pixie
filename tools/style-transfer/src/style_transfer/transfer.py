"""Style transfer with a torch VGG backend when installed and a
numpy histogram-matching fallback otherwise. Both report a streaming
per-iteration loss series so the wire protocol is identical."""
from __future__ import annotations

import asyncio
import base64
import io
from dataclasses import dataclass
from typing import AsyncIterator

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class IterationStep:
    iteration: int
    loss: float


def _decode_image(value: str | None, size: int, fallback_color: tuple[int, int, int]) -> Image.Image:
    if not value:
        arr = np.full((size, size, 3), fallback_color, dtype=np.uint8)
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
        arr = np.full((size, size, 3), fallback_color, dtype=np.uint8)
        return Image.fromarray(arr, mode="RGB")
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    return img.resize((size, size), Image.LANCZOS)


def _encode(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401
        import torchvision  # noqa: F401
        return True
    except Exception:
        return False


def _histogram_match(source: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Per-channel histogram matching — a poor man's style transfer."""

    out = np.zeros_like(source)
    for c in range(3):
        s = source[..., c].ravel()
        r = reference[..., c].ravel()
        s_values, s_counts = np.unique(s, return_counts=True)
        r_values, r_counts = np.unique(r, return_counts=True)
        s_quantiles = np.cumsum(s_counts).astype(np.float64) / s.size
        r_quantiles = np.cumsum(r_counts).astype(np.float64) / r.size
        interp_r_values = np.interp(s_quantiles, r_quantiles, r_values)
        mapped = np.interp(s.astype(np.float64), s_values, interp_r_values)
        out[..., c] = mapped.reshape(source[..., c].shape).astype(np.uint8)
    return out


async def transfer(
    content_value: str | None,
    style_value: str | None,
    strength: float,
    iterations: int,
    image_size: int,
) -> AsyncIterator[tuple[IterationStep | None, Image.Image | None]]:
    """Yields (step, None) per iteration; final value is (None, image)."""

    content = _decode_image(content_value, image_size, (200, 180, 160))
    style = _decode_image(style_value, image_size, (40, 80, 140))

    if _torch_available():
        async for item in _torch_transfer(content, style, strength, iterations):
            yield item
        return

    # Numpy fallback: blend hist-matched style into content over `iterations`.
    matched = _histogram_match(np.asarray(content), np.asarray(style))
    base = np.asarray(content, dtype=np.float32)
    target = matched.astype(np.float32)
    alpha = strength / 100.0
    n = max(2, int(iterations))
    for i in range(1, n + 1):
        progress = i / n
        weight = alpha * progress
        blend = (1 - weight) * base + weight * target
        loss = float(np.mean(np.abs(blend - target))) / 255.0
        yield IterationStep(iteration=i, loss=round(loss, 6)), None
        if i % 5 == 0:
            await asyncio.sleep(0)
    final = Image.fromarray(np.clip(blend, 0, 255).astype(np.uint8), mode="RGB")
    yield None, final


async def _torch_transfer(
    content_img: Image.Image,
    style_img: Image.Image,
    strength: float,
    iterations: int,
) -> AsyncIterator[tuple[IterationStep | None, Image.Image | None]]:
    """The Gatys-style algorithm — VGG19 features, content + Gram-matrix
    style losses, L-BFGS optimisation. Truncated to keep iterations bounded."""

    import torch
    import torch.nn.functional as F
    from torchvision import models, transforms

    device = torch.device("cpu")
    preprocess = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    deprocess = transforms.Normalize(
        mean=[-0.485 / 0.229, -0.456 / 0.224, -0.406 / 0.225],
        std=[1 / 0.229, 1 / 0.224, 1 / 0.225],
    )

    content_t = preprocess(content_img).unsqueeze(0).to(device)
    style_t = preprocess(style_img).unsqueeze(0).to(device)

    vgg = models.vgg19(weights=models.VGG19_Weights.DEFAULT).features.to(device).eval()
    for p in vgg.parameters():
        p.requires_grad_(False)

    content_layers = {21}  # conv4_2
    style_layers = {0, 5, 10, 19, 28}

    def extract(x: torch.Tensor) -> tuple[dict[int, torch.Tensor], dict[int, torch.Tensor]]:
        c: dict[int, torch.Tensor] = {}
        s: dict[int, torch.Tensor] = {}
        for i, layer in enumerate(vgg):
            x = layer(x)
            if i in content_layers:
                c[i] = x
            if i in style_layers:
                s[i] = x
        return c, s

    with torch.no_grad():
        _, style_features = extract(style_t)
        content_features, _ = extract(content_t)

    def gram(f: torch.Tensor) -> torch.Tensor:
        b, c, h, w = f.size()
        fl = f.view(b, c, h * w)
        return fl @ fl.transpose(1, 2) / (c * h * w)

    style_grams = {i: gram(f) for i, f in style_features.items()}

    target = content_t.clone().requires_grad_(True)
    optimiser = torch.optim.LBFGS([target], lr=1.0, max_iter=1)
    content_weight = max(1.0, 100.0 * (1.0 - strength / 100.0))
    style_weight = max(1.0, 1.0e5 * (strength / 100.0))

    losses: list[float] = []
    for i in range(1, max(2, iterations) + 1):
        def closure() -> torch.Tensor:
            optimiser.zero_grad()
            c_feats, s_feats = extract(target)
            c_loss = sum(F.mse_loss(c_feats[k], content_features[k]) for k in content_layers)
            s_loss = sum(F.mse_loss(gram(s_feats[k]), style_grams[k]) for k in style_layers)
            total = content_weight * c_loss + style_weight * s_loss
            total.backward()
            return total
        loss = optimiser.step(closure)
        loss_val = float(loss.detach().cpu().item())
        losses.append(loss_val)
        yield IterationStep(iteration=i, loss=round(loss_val, 6)), None
        if i % 5 == 0:
            await asyncio.sleep(0)

    with torch.no_grad():
        final = deprocess(target.squeeze(0).cpu()).clamp(0, 1)
    final_arr = (final.permute(1, 2, 0).numpy() * 255).astype(np.uint8)
    yield None, Image.fromarray(final_arr)


def encode_image(image: Image.Image) -> str:
    return _encode(image)


def torch_available() -> bool:
    return _torch_available()
