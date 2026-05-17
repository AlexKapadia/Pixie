"""Image / audio / video comparators.

scikit-image and librosa are imported lazily so a Pixie install without
the ``accuracy`` extra still loads. When the dep is missing, the
comparator degrades to a ``size+sha256`` fallback and tags the diff's
metric so the report explains the weaker check.
"""

from __future__ import annotations

import base64
import hashlib
import io
from typing import Any

from pixie.comparators._base import Diff


# Lazy imports — set to None at module load; populated on first call.
_skimage = None
_pil = None
_librosa = None
_numpy = None
_DEGRADED_IMAGE_REASON: str | None = None
_DEGRADED_AUDIO_REASON: str | None = None


def _ensure_image_deps() -> str | None:
    """Return None if scikit-image+pillow are available, else degrade reason."""

    global _skimage, _pil, _numpy, _DEGRADED_IMAGE_REASON
    if _DEGRADED_IMAGE_REASON is not None:
        return _DEGRADED_IMAGE_REASON
    if _skimage is not None and _pil is not None and _numpy is not None:
        return None
    try:
        from skimage.metrics import structural_similarity  # noqa: F401
        from PIL import Image  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as exc:
        _DEGRADED_IMAGE_REASON = (
            f"degraded: {exc.name} not installed; "
            "pip install pixie[accuracy] for full SSIM"
        )
        return _DEGRADED_IMAGE_REASON
    from skimage.metrics import structural_similarity
    from PIL import Image
    import numpy
    _skimage = structural_similarity
    _pil = Image
    _numpy = numpy
    return None


def _ensure_audio_deps() -> str | None:
    global _librosa, _numpy, _DEGRADED_AUDIO_REASON
    if _DEGRADED_AUDIO_REASON is not None:
        return _DEGRADED_AUDIO_REASON
    if _librosa is not None and _numpy is not None:
        return None
    try:
        import librosa  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as exc:
        _DEGRADED_AUDIO_REASON = (
            f"degraded: {exc.name} not installed; "
            "pip install pixie[accuracy] for full spectrogram L2"
        )
        return _DEGRADED_AUDIO_REASON
    import librosa
    import numpy
    _librosa = librosa
    _numpy = numpy
    return None


def _decode_image_bytes(value: Any) -> bytes:
    """Accept a data URL, base64 string, or url string and return bytes.

    For plain URLs (http/https/file) the bytes ARE the URL string —
    comparison degrades to a string-level compare. Callers that want
    pixel-level comparison should provide data URLs.
    """

    if isinstance(value, dict):
        for key in ("data", "image", "value", "url"):
            if key in value:
                value = value[key]
                break
    if not isinstance(value, str):
        return repr(value).encode("utf-8")
    if value.startswith("data:") and "," in value:
        prefix, b64 = value.split(",", 1)
        try:
            return base64.b64decode(b64)
        except (ValueError, TypeError):
            return value.encode("utf-8")
    if value.startswith(("http://", "https://", "file://")):
        return value.encode("utf-8")
    # Try plain base64
    try:
        return base64.b64decode(value)
    except (ValueError, TypeError):
        return value.encode("utf-8")


def _sha256_size(data: bytes) -> tuple[str, int]:
    return hashlib.sha256(data).hexdigest(), len(data)


def compare_image(
    output_key: str,
    output_type: str,
    expected: Any,
    actual: Any,
    tolerance: dict[str, Any],
) -> Diff | None:
    """SSIM for ``image`` output type. Degrades to sha256+size."""

    if tolerance.get("compare") == "skip":
        return None

    min_ssim = float(tolerance.get("min_ssim", 0.95))
    degraded = tolerance.get("compare") == "size_sha256"
    reason = None
    if not degraded:
        reason = _ensure_image_deps()
    if degraded or reason is not None:
        return _image_fallback(output_key, output_type, expected, actual, reason)

    e_bytes = _decode_image_bytes(expected)
    a_bytes = _decode_image_bytes(actual)
    try:
        e_img = _pil.open(io.BytesIO(e_bytes)).convert("RGB")
        a_img = _pil.open(io.BytesIO(a_bytes)).convert("RGB")
    except Exception as exc:  # pillow / image parse problems
        return _image_fallback(
            output_key, output_type, expected, actual,
            f"could not decode image ({exc}); falling back to sha256",
        )

    if e_img.size != a_img.size:
        return Diff(
            output_key=output_key, output_type=output_type, comparator="image_ssim",
            expected=e_img.size, actual=a_img.size,
            metric=f"image sizes differ {e_img.size} vs {a_img.size}",
        )
    e_arr = _numpy.asarray(e_img)
    a_arr = _numpy.asarray(a_img)
    try:
        ssim = float(_skimage(e_arr, a_arr, channel_axis=-1, data_range=255))
    except Exception as exc:
        return _image_fallback(
            output_key, output_type, expected, actual,
            f"ssim failed ({exc}); falling back to sha256",
        )
    if ssim >= min_ssim:
        return None
    return Diff(
        output_key=output_key, output_type=output_type, comparator="image_ssim",
        expected=f"ssim>={min_ssim:.3f}", actual=f"ssim={ssim:.4f}",
        metric=(
            f"ssim {ssim:.4f} < min {min_ssim:.3f} "
            f"({e_img.size[0]}x{e_img.size[1]} vs {a_img.size[0]}x{a_img.size[1]}, mode RGB)"
        ),
    )


def _image_fallback(
    output_key: str, output_type: str,
    expected: Any, actual: Any, reason: str | None,
) -> Diff | None:
    e_bytes = _decode_image_bytes(expected)
    a_bytes = _decode_image_bytes(actual)
    e_hash, e_size = _sha256_size(e_bytes)
    a_hash, a_size = _sha256_size(a_bytes)
    if e_hash == a_hash and e_size == a_size:
        return None
    tag = f" [{reason}]" if reason else ""
    return Diff(
        output_key=output_key, output_type=output_type, comparator="image_size_sha256",
        expected=f"sha256={e_hash[:12]} size={e_size}",
        actual=f"sha256={a_hash[:12]} size={a_size}",
        metric=(
            f"sha256 differs: {e_hash[:8]}... vs {a_hash[:8]}... "
            f"(size {e_size} vs {a_size}){tag}"
        ),
    )


def compare_image_grid(
    output_key: str,
    output_type: str,
    expected: Any,
    actual: Any,
    tolerance: dict[str, Any],
) -> Diff | None:
    """Per-image SSIM over a grid of images."""

    e_imgs = expected.get("images") if isinstance(expected, dict) else expected
    a_imgs = actual.get("images") if isinstance(actual, dict) else actual
    if not isinstance(e_imgs, list) or not isinstance(a_imgs, list):
        return Diff(
            output_key=output_key, output_type=output_type, comparator="image_ssim_per_image",
            expected=e_imgs, actual=a_imgs,
            metric="image_grid expects .images: [...]",
        )
    if len(e_imgs) != len(a_imgs):
        return Diff(
            output_key=output_key, output_type=output_type, comparator="image_ssim_per_image",
            expected=len(e_imgs), actual=len(a_imgs),
            metric=f"image count differs: {len(e_imgs)} vs {len(a_imgs)}",
        )
    for i, (e_im, a_im) in enumerate(zip(e_imgs, a_imgs)):
        sub = compare_image(f"{output_key}[{i}]", output_type, e_im, a_im, tolerance)
        if sub is not None:
            return sub
    return None


def compare_image_compare(
    output_key: str,
    output_type: str,
    expected: Any,
    actual: Any,
    tolerance: dict[str, Any],
) -> Diff | None:
    """Compare both ``before`` and ``after`` images in an image_compare output."""

    for side in ("before", "after"):
        e_side = expected.get(side) if isinstance(expected, dict) else None
        a_side = actual.get(side) if isinstance(actual, dict) else None
        if e_side is None and a_side is None:
            continue
        sub = compare_image(f"{output_key}.{side}", output_type, e_side, a_side, tolerance)
        if sub is not None:
            return sub
    return None


def compare_audio(
    output_key: str,
    output_type: str,
    expected: Any,
    actual: Any,
    tolerance: dict[str, Any],
) -> Diff | None:
    """Audio mel-spectrogram L2 distance. Degrades to sha256+size."""

    if tolerance.get("compare") == "skip":
        return None

    max_l2 = float(tolerance.get("max_l2", 0.05))
    sr = int(tolerance.get("sample_rate", 22050))
    n_mels = int(tolerance.get("n_mels", 128))

    degraded = tolerance.get("compare") == "size_sha256"
    reason = None
    if not degraded:
        reason = _ensure_audio_deps()
    if degraded or reason is not None:
        return _audio_fallback(output_key, output_type, expected, actual, reason)

    e_bytes = _decode_image_bytes(expected)
    a_bytes = _decode_image_bytes(actual)

    try:
        e_y, _ = _librosa.load(io.BytesIO(e_bytes), sr=sr, mono=True)
        a_y, _ = _librosa.load(io.BytesIO(a_bytes), sr=sr, mono=True)
    except Exception as exc:
        return _audio_fallback(
            output_key, output_type, expected, actual,
            f"could not decode audio ({exc}); falling back to sha256",
        )

    try:
        e_mel = _librosa.feature.melspectrogram(y=e_y, sr=sr, n_mels=n_mels)
        a_mel = _librosa.feature.melspectrogram(y=a_y, sr=sr, n_mels=n_mels)
        # Pad to identical shape with zero columns before L2.
        n = min(e_mel.shape[1], a_mel.shape[1])
        e_mel = e_mel[:, :n]
        a_mel = a_mel[:, :n]
        l2 = float(_numpy.linalg.norm(e_mel - a_mel) / max(_numpy.linalg.norm(e_mel), 1e-12))
    except Exception as exc:
        return _audio_fallback(
            output_key, output_type, expected, actual,
            f"spectrogram l2 failed ({exc}); falling back to sha256",
        )

    if l2 <= max_l2:
        return None
    return Diff(
        output_key=output_key, output_type=output_type, comparator="audio_spectrogram_l2",
        expected=f"l2<={max_l2:.3f}", actual=f"l2={l2:.4f}",
        metric=f"l2 {l2:.4f} > max {max_l2:.3f} (sr={sr}, n_mels={n_mels})",
    )


def _audio_fallback(
    output_key: str, output_type: str,
    expected: Any, actual: Any, reason: str | None,
) -> Diff | None:
    e_bytes = _decode_image_bytes(expected)
    a_bytes = _decode_image_bytes(actual)
    e_hash, e_size = _sha256_size(e_bytes)
    a_hash, a_size = _sha256_size(a_bytes)
    if e_hash == a_hash and e_size == a_size:
        return None
    tag = f" [{reason}]" if reason else ""
    return Diff(
        output_key=output_key, output_type=output_type, comparator="audio_size_sha256",
        expected=f"sha256={e_hash[:12]} size={e_size}",
        actual=f"sha256={a_hash[:12]} size={a_size}",
        metric=(
            f"sha256 differs: {e_hash[:8]}... vs {a_hash[:8]}... "
            f"(size {e_size} vs {a_size}){tag}"
        ),
    )


def compare_video(
    output_key: str,
    output_type: str,
    expected: Any,
    actual: Any,
    tolerance: dict[str, Any],
) -> Diff | None:
    """Video comparison is opt-in. Skipped by default per RESEARCH §2."""

    mode = tolerance.get("compare", "skip")
    if mode == "skip":
        return None
    # When per_frame_ssim_mean is requested we degrade to size+sha256: a
    # robust frame-decoder would pull in ffmpeg, far outside the
    # ``accuracy`` extra's footprint. The diff metric surfaces this.
    return _image_fallback(
        output_key, output_type, expected, actual,
        "video per-frame ssim requires ffmpeg; falling back to size+sha256",
    )
