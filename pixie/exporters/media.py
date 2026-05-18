"""image, image_grid, image_compare, audio, video, file exporters."""

from __future__ import annotations

import io
import json
import math
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from pixie.exporters import (
    ExporterError,
    ExporterMissingDependency,
    ExporterTooLarge,
    register_exporter,
)
from pixie.exporters._common import coerce_path, coerce_value


# --- image -------------------------------------------------------------------


def _image_path(raw: Any) -> Path:
    candidate = coerce_path(raw)
    if candidate is None:
        if isinstance(raw, dict):
            for key in ("file_url", "rel_path"):
                val = raw.get(key)
                if isinstance(val, str) and Path(val).exists():
                    return Path(val)
        raise ExporterError("image export requires a file path; got an inline value")
    return candidate


def _image_convert(raw, *, fmt: str, prov: str, output_key: str, opts: dict[str, Any]) -> tuple[bytes, str]:
    try:
        from PIL import Image, PngImagePlugin  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ExporterMissingDependency(
            "Pillow is required for image format conversion",
            hint="run `uv add pillow`",
        ) from exc
    source = _image_path(raw)
    out = io.BytesIO()
    with Image.open(source) as im:
        im.load()
        if opts.get("resize"):
            try:
                w, h = (int(x) for x in str(opts["resize"]).lower().split("x"))
                im.thumbnail((w, h), Image.LANCZOS)
            except (ValueError, TypeError):
                pass
        save_kwargs: dict[str, Any] = {}
        target = fmt.upper()
        if fmt == "jpg":
            target = "JPEG"
            if im.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1] if im.mode != "P" else None)
                im = bg
            save_kwargs = {"quality": int(opts.get("quality", 92)), "optimize": True,
                            "progressive": True}
        elif fmt == "webp":
            save_kwargs = {"quality": int(opts.get("quality", 90)), "method": 6}
        elif fmt == "pdf":
            if im.mode == "RGBA":
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            save_kwargs = {"resolution": 150}
        elif fmt == "png":
            info = PngImagePlugin.PngInfo()
            info.add_text("pixie_provenance", prov)
            save_kwargs = {"pnginfo": info}
        im.save(out, format=target, **save_kwargs)
    return out.getvalue(), f"{output_key}.{fmt}"


for _fmt in ("png", "jpg", "webp", "pdf"):
    def _make(fmt=_fmt):
        def fn(raw, *, prov, output_key, opts, **_):
            return _image_convert(raw, fmt=fmt, prov=prov, output_key=output_key, opts=opts or {})
        return fn
    register_exporter("image", _fmt, _make(), default=(_fmt == "png"))


def image_original(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    source = _image_path(raw)
    return source.read_bytes(), source.name


register_exporter("image", "original", image_original)


# --- image_grid --------------------------------------------------------------


def _image_paths(raw: Any) -> list[Path]:
    value = coerce_value(raw)
    paths: list[Path] = []
    if isinstance(value, list):
        for entry in value:
            candidate = coerce_path(entry)
            if candidate is not None:
                paths.append(candidate)
    elif isinstance(value, dict) and "items" in value:
        for entry in value["items"] or []:
            candidate = coerce_path(entry)
            if candidate is not None:
                paths.append(candidate)
    return paths


def image_grid_to_zip(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    paths = _image_paths(raw)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("PIXIE_PROVENANCE.txt", prov)
        for idx, path in enumerate(paths):
            zf.write(path, arcname=f"{idx:03d}_{path.name}")
    return buf.getvalue(), f"{output_key}.zip"


def image_grid_to_png(raw, *, prov, output_key, opts, **_) -> tuple[bytes, str]:
    try:
        from PIL import Image, PngImagePlugin  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ExporterMissingDependency(
            "Pillow is required for image grid mosaic",
            hint="run `uv add pillow`",
        ) from exc
    paths = _image_paths(raw)
    if not paths:
        raise ExporterError("image_grid has no images to mosaic")
    ims = [Image.open(p).convert("RGB") for p in paths]
    cols = int((opts or {}).get("cols") or math.ceil(math.sqrt(len(ims))))
    rows = math.ceil(len(ims) / cols)
    tw = max(i.width for i in ims)
    th = max(i.height for i in ims)
    if tw * cols > 16_000 or th * rows > 16_000:
        raise ExporterTooLarge(
            f"mosaic would be {tw * cols}x{th * rows}; export as zip instead",
        )
    canvas = Image.new("RGB", (tw * cols, th * rows), (255, 255, 255))
    for idx, im in enumerate(ims):
        r, c = divmod(idx, cols)
        canvas.paste(im, (c * tw, r * th))
        im.close()
    out = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    info.add_text("pixie_provenance", prov)
    canvas.save(out, "PNG", pnginfo=info)
    return out.getvalue(), f"{output_key}.png"


register_exporter("image_grid", "zip", image_grid_to_zip, default=True)
register_exporter("image_grid", "png", image_grid_to_png)


# --- image_compare -----------------------------------------------------------


def image_compare_to_png(raw, *, prov, output_key, opts, **_) -> tuple[bytes, str]:
    try:
        from PIL import Image, ImageDraw, ImageFont, PngImagePlugin  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ExporterMissingDependency(
            "Pillow is required for image_compare export",
            hint="run `uv add pillow`",
        ) from exc
    value = coerce_value(raw) or {}
    before = coerce_path(value.get("before")) if isinstance(value, dict) else None
    after = coerce_path(value.get("after")) if isinstance(value, dict) else None
    if before is None or after is None:
        raise ExporterError("image_compare needs 'before' and 'after' image paths")
    a = Image.open(before).convert("RGB")
    b = Image.open(after).convert("RGB")
    layout = (opts or {}).get("layout", "horizontal")
    if layout == "vertical":
        w = max(a.width, b.width)
        canvas = Image.new("RGB", (w, a.height + b.height + 24), (255, 255, 255))
        canvas.paste(a, (0, 24))
        canvas.paste(b, (0, a.height + 24))
    else:
        h = max(a.height, b.height)
        canvas = Image.new("RGB", (a.width + b.width + 4, h + 24), (255, 255, 255))
        canvas.paste(a, (0, 24))
        canvas.paste(b, (a.width + 4, 24))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 14)
    except OSError:
        font = ImageFont.load_default()
    draw.text((4, 4), "before", fill=(0, 0, 0), font=font)
    draw.text((a.width + 8 if layout != "vertical" else 4,
               4 if layout != "vertical" else a.height + 4),
              "after", fill=(0, 0, 0), font=font)
    out = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    info.add_text("pixie_provenance", prov)
    canvas.save(out, "PNG", pnginfo=info)
    return out.getvalue(), f"{output_key}.png"


def image_compare_to_zip(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    value = coerce_value(raw) or {}
    before = coerce_path(value.get("before"))
    after = coerce_path(value.get("after"))
    if before is None or after is None:
        raise ExporterError("image_compare needs 'before' and 'after' image paths")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("PIXIE_PROVENANCE.txt", prov)
        zf.write(before, arcname=f"before{before.suffix}")
        zf.write(after, arcname=f"after{after.suffix}")
    return buf.getvalue(), f"{output_key}.zip"


register_exporter("image_compare", "png", image_compare_to_png, default=True)
register_exporter("image_compare", "zip", image_compare_to_zip)


# --- audio -------------------------------------------------------------------


def _audio_path(raw: Any) -> Path:
    candidate = coerce_path(raw)
    if candidate is None:
        raise ExporterError("audio export requires a file path; got an inline value")
    return candidate


def _audio_convert(raw, *, fmt: str, prov: str, output_key: str) -> tuple[bytes, str]:
    source = _audio_path(raw)
    if shutil.which("ffmpeg") is None:
        return _audio_fallback(source, fmt, prov, output_key)
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / f"audio.{fmt}"
        cmd = ["ffmpeg", "-loglevel", "error", "-y", "-i", str(source),
                "-metadata", f"comment={prov[:200]}"]
        if fmt == "mp3":
            cmd += ["-codec:a", "libmp3lame", "-q:a", "2"]
        elif fmt == "ogg":
            cmd += ["-codec:a", "libvorbis", "-q:a", "5"]
        elif fmt == "flac":
            cmd += ["-codec:a", "flac"]
        elif fmt == "wav":
            cmd += ["-codec:a", "pcm_s16le"]
        cmd.append(str(target))
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=300)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ExporterError(
                f"ffmpeg failed for {fmt} export: {exc}",
                hint="check that ffmpeg is recent (>= 4.4)",
            ) from exc
        payload = target.read_bytes()
    return payload, f"{output_key}.{fmt}"


def _audio_fallback(source: Path, fmt: str, prov: str, output_key: str) -> tuple[bytes, str]:
    if fmt == "mp3":
        raise ExporterMissingDependency(
            "ffmpeg is required for .mp3 export",
            hint="install ffmpeg via `pixie doctor` then retry",
        )
    try:
        import soundfile as sf  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ExporterMissingDependency(
            "ffmpeg is missing and soundfile is unavailable",
            hint="install ffmpeg via `pixie doctor` for full audio support",
        ) from exc
    data, sr = sf.read(str(source))
    buf = io.BytesIO()
    sf.write(buf, data, sr, format=fmt.upper())
    return buf.getvalue(), f"{output_key}.{fmt}"


def audio_original(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    source = _audio_path(raw)
    return source.read_bytes(), source.name


for _fmt in ("wav", "mp3", "flac", "ogg"):
    def _make(fmt=_fmt):
        def fn(raw, *, prov, output_key, **_):
            return _audio_convert(raw, fmt=fmt, prov=prov, output_key=output_key)
        return fn
    register_exporter("audio", _fmt, _make(), default=(_fmt == "wav"))

register_exporter("audio", "original", audio_original)


# --- video -------------------------------------------------------------------


def _video_path(raw: Any) -> Path:
    candidate = coerce_path(raw)
    if candidate is None:
        raise ExporterError("video export requires a file path; got an inline value")
    return candidate


def _video_convert(raw, *, fmt: str, prov: str, output_key: str) -> tuple[bytes, str]:
    if shutil.which("ffmpeg") is None:
        raise ExporterMissingDependency(
            f"ffmpeg is required for video {fmt} export",
            hint="install ffmpeg via `pixie doctor` then retry",
        )
    source = _video_path(raw)
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / f"video.{fmt}"
        if fmt == "gif":
            palette = Path(tmp) / "palette.png"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
                 "-vf", "fps=12,scale=480:-1:flags=lanczos,palettegen",
                 str(palette)],
                check=True, capture_output=True, timeout=600,
            )
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(source), "-i", str(palette),
                "-lavfi",
                "fps=12,scale=480:-1:flags=lanczos[x];[x][1:v]paletteuse",
                "-metadata", f"comment={prov[:200]}",
                str(target),
            ]
        else:
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
                    "-metadata", f"comment={prov[:200]}"]
            if fmt == "mp4":
                cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "23",
                         "-movflags", "+faststart"]
            elif fmt == "webm":
                cmd += ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0"]
            cmd.append(str(target))
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=900)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ExporterError(f"ffmpeg failed for video {fmt}: {exc}") from exc
        payload = target.read_bytes()
    return payload, f"{output_key}.{fmt}"


def video_original(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    source = _video_path(raw)
    return source.read_bytes(), source.name


for _fmt in ("mp4", "webm", "gif"):
    def _make(fmt=_fmt):
        def fn(raw, *, prov, output_key, **_):
            return _video_convert(raw, fmt=fmt, prov=prov, output_key=output_key)
        return fn
    register_exporter("video", _fmt, _make(), default=(_fmt == "mp4"))

register_exporter("video", "original", video_original)


# --- file --------------------------------------------------------------------


def file_original(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    candidate = coerce_path(raw)
    if candidate is None:
        # Inline-style file output: serialise the value.
        value = coerce_value(raw)
        if isinstance(value, (bytes, bytearray)):
            return bytes(value), f"{output_key}.bin"
        payload = json.dumps(value, indent=2, default=str).encode("utf-8")
        return payload, f"{output_key}.json"
    return candidate.read_bytes(), candidate.name


register_exporter("file", "original", file_original, default=True)
