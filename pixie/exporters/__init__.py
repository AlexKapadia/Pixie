"""Pixie exporters -- one output type, many formats.

Every Pixie output type ships with an exporter module under this package.
Modules register themselves at import time via :func:`register_exporter`;
the dispatcher (:func:`export`) is the only public entry point used by
routes, the validator's ``--export-check`` flag, and the run-report
zipper.

Heavy optional libraries (Pillow, openpyxl, pyarrow, kaleido, soundfile,
pikepdf, markdown-it-py, pygments, networkx) are imported **lazily**
inside each exporter so a user without ``ffmpeg`` can still export
text/JSON/CSV without a missing-import crash.

Error contract:

* :class:`ExporterError` -- generic exporter failure (returned as 422).
* :class:`ExporterMissingDependency` -- optional library / system binary
  missing; the message contains the recommended fix and a
  ``pixie doctor`` hint.
* :class:`ExporterUnsupported` -- the requested ``(type, format)`` pair
  was never registered (returned as 415).
* :class:`ExporterTooLarge` -- the payload exceeds the format's safe cap
  (returned as 413).
* :class:`ExporterDegraded` -- soft-fail; we successfully exported but
  to a different format than asked.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from pixie.errors import PixieError

logger = logging.getLogger("pixie.exporters")


# --- exceptions --------------------------------------------------------------


class ExporterError(PixieError):
    code = "exporter_error"


class ExporterMissingDependency(ExporterError):
    code = "exporter_missing_dependency"


class ExporterUnsupported(ExporterError):
    code = "exporter_unsupported"


class ExporterTooLarge(ExporterError):
    code = "exporter_too_large"


class ExporterDegraded(ExporterError):
    """We exported successfully, but to a different format than asked."""

    code = "exporter_degraded"

    def __init__(
        self,
        message: str,
        *,
        payload: bytes,
        filename: str,
        actual_format: str,
        hint: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.payload = payload
        self.filename = filename
        self.actual_format = actual_format


# --- registry ----------------------------------------------------------------


ExporterFn = Callable[..., "tuple[bytes, str] | Awaitable[tuple[bytes, str]]"]

_REGISTRY: dict[tuple[str, str], ExporterFn] = {}
_DEFAULTS: dict[str, str] = {}
_SUPPORTED: dict[str, list[str]] = {}


def register_exporter(
    output_type: str,
    format: str,
    fn: ExporterFn,
    *,
    default: bool = False,
) -> None:
    """Register an exporter callable for ``(output_type, format)``."""

    _REGISTRY[(output_type, format)] = fn
    if format not in _SUPPORTED.setdefault(output_type, []):
        _SUPPORTED[output_type].append(format)
    if default or output_type not in _DEFAULTS:
        _DEFAULTS[output_type] = format


def default_format(output_type: str) -> str:
    if output_type not in _DEFAULTS:
        raise ExporterUnsupported(
            f"no exporter registered for output type {output_type!r}"
        )
    return _DEFAULTS[output_type]


def supported_formats(output_type: str) -> list[str]:
    if output_type not in _SUPPORTED:
        raise ExporterUnsupported(
            f"no exporter registered for output type {output_type!r}"
        )
    return list(_SUPPORTED[output_type])


def supports(output_type: str, format: str) -> bool:
    return (output_type, format) in _REGISTRY


# --- provenance --------------------------------------------------------------


def make_provenance(
    *,
    tool_id: str | None,
    run_id: str | None,
    output_key: str | None,
    when: datetime | None = None,
) -> str:
    ts = (when or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = ["Exported from Pixie"]
    if tool_id:
        parts.append(f"tool={tool_id}")
    if run_id:
        parts.append(f"run={run_id}")
    if output_key:
        parts.append(f"output={output_key}")
    parts.append(f"ts={ts}")
    return " | ".join(parts)


# --- filename sanitisation ---------------------------------------------------


_WIN_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)
_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f/\\:*?\"<>|]")


def safe_filename(
    hint: str | None,
    output_key: str,
    fmt: str,
    *,
    fallback: str | None = None,
) -> str:
    """Cross-platform-safe filename; always ends in ``.<fmt>``."""

    raw = hint or fallback or f"{output_key or 'output'}.{fmt}"
    raw = unicodedata.normalize("NFKC", raw)
    raw = _BAD_CHARS.sub("_", raw)
    raw = raw.lstrip(".").replace(" ", "_")
    base = Path(raw).stem or (output_key or "output")
    if _WIN_RESERVED.match(base):
        base = "_" + base
    base = base[: max(1, 240 - len(fmt) - 1)]
    return f"{base}.{fmt}"


# --- dispatcher --------------------------------------------------------------


async def export(
    value: Any,
    output_type: str,
    *,
    format: str | None = None,
    opts: dict[str, Any] | None = None,
    provenance: str | None = None,
    output_key: str | None = None,
    tool_id: str | None = None,
    run_id: str | None = None,
    spec: dict[str, Any] | None = None,
) -> tuple[bytes, str]:
    """Convert ``value`` of declared ``output_type`` into ``format`` bytes.

    ``value`` may be the in-memory value, an artefact-row dict (with
    ``rel_path`` / ``abs_path``), or a Path. Each per-type exporter
    decides which shapes it accepts.
    """

    fmt = format or default_format(output_type)
    if not supports(output_type, fmt):
        raise ExporterUnsupported(
            f"format {fmt!r} not supported for output type {output_type!r}; "
            f"supported: {supported_formats(output_type)}"
        )
    fn = _REGISTRY[(output_type, fmt)]
    prov = provenance or make_provenance(
        tool_id=tool_id, run_id=run_id, output_key=output_key,
    )
    result = fn(
        value,
        prov=prov,
        opts=opts or {},
        output_key=output_key or "output",
        spec=spec or {},
    )
    if hasattr(result, "__await__"):
        result = await result  # type: ignore[assignment]
    payload, filename = result  # type: ignore[misc]
    safe = safe_filename(
        (opts or {}).get("filename_hint"),
        output_key or output_type,
        fmt,
        fallback=filename,
    )
    return payload, safe


# --- bootstrap ---------------------------------------------------------------


def _bootstrap() -> None:
    """Import every sibling module so they self-register."""

    for module in pkgutil.iter_modules(__path__):
        if module.name.startswith("_"):
            continue
        importlib.import_module(f"{__name__}.{module.name}")


_bootstrap()
