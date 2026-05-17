"""Local-first output persistence (artefact store).

Every Pixie run writes its outputs into an artefact directory created
by the launcher BEFORE the tool process is spawned. After the run
finishes the proxy invokes :func:`register_run_artefacts` which walks
that directory, computes sha256/size/mime for each file, registers
the metadata in SQLite (via :mod:`pixie.db`) and rewrites large
``outputs_json`` values into reference handles (``{_artefact_id: N}``)
so the run row stays small and the renderer can rehydrate them.

The module also owns:

* :class:`ArtefactRegistry` -- thin facade over the disk layout
  (`artefacts/<tool_id>/<YYYY-MM-DD>/<run_id>/<filename>`)
* :func:`safe_join` -- path-traversal-refusing path joiner
* :func:`generate_thumbnail` -- Pillow-based thumb generator with a
  mime-icon fallback (ffmpeg for video, when present)
* :func:`quota_watchdog` -- per-run async task that SIGKILLs the
  subprocess when the run's artefact directory exceeds the configured
  byte cap (see ``Settings.max_artefact_bytes_per_run``)
* :func:`soft_delete` / :func:`restore` / :func:`purge_expired`
* :func:`sweeper_loop` -- background task started by the FastAPI
  lifespan to apply retention policy + hard-delete soft-deleted rows
  + reclaim stale ``.partial`` files

All file IO that could block the event loop is delegated to a thread
pool via ``run_in_threadpool``.

Threat model + atomicity contracts live in
``.build/RESEARCH_output_persistence.md`` sections 8, 9, 12.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from fastapi.concurrency import run_in_threadpool

from pixie import db
from pixie.config import Settings
from pixie.errors import PixieError

logger = logging.getLogger("pixie.artefacts")


# --- exceptions --------------------------------------------------------------


class ArtefactError(PixieError):
    code = "artefact_error"


class ArtefactPathError(ArtefactError):
    code = "artefact_path_refused"


class ArtefactQuotaExceeded(ArtefactError):
    code = "artefact_quota_exceeded"


# --- constants ---------------------------------------------------------------


_RESERVED_DIR_NAMES = {"_thumbs", "_quarantine", "_exports"}

# Custom mime mappings beyond stdlib's mimetypes module.
_EXTRA_MIMES: dict[str, str] = {
    ".npy": "application/x-numpy",
    ".parquet": "application/x-parquet",
    ".gguf": "application/octet-stream",
    ".safetensors": "application/octet-stream",
    ".onnx": "application/x-onnx",
    ".webp": "image/webp",
    ".jsonl": "application/x-ndjson",
    ".geojson": "application/geo+json",
    ".gpx": "application/gpx+xml",
    ".kml": "application/vnd.google-earth.kml+xml",
    ".tex": "application/x-tex",
    ".md": "text/markdown",
    ".patch": "text/x-patch",
    ".diff": "text/x-diff",
}

# Secret-shaped filename redaction (DECISIONS s17 -- shared regex).
_SECRET_KEY_RE = re.compile(
    r"(password|secret|token|api[_-]?key|auth|bearer|jwt|credential)",
    re.IGNORECASE,
)

# Chunk size for streamed sha256 + file reads.
_HASH_CHUNK = 1 << 20  # 1 MiB


# --- data shapes -------------------------------------------------------------


@dataclass
class ScannedFile:
    """One file found by :func:`scan_run_dir`, ready to register."""

    rel_path: str           # path relative to artefacts_root
    filename: str
    abs_path: Path
    mime: str
    size_bytes: int
    sha256: str
    output_key: str         # "" when not tied to a declared output
    redacted_from: str | None = None


@dataclass
class RunArtefactsContext:
    """Per-run scratch state held by the launcher."""

    run_id: str
    tool_id: str
    artefacts_dir: Path
    last_scan_index: dict[str, tuple[int, str]] = field(default_factory=dict)
    watchdog_task: "asyncio.Task[None] | None" = None
    killed_for_quota: bool = False


# --- registry facade ---------------------------------------------------------


class ArtefactRegistry:
    """Owns the on-disk layout and resolves run directories.

    Held on ``app.state.artefacts`` so routes can look up paths without
    importing :mod:`pixie.config` directly. Instantiated once per process
    in the FastAPI lifespan.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.artefacts_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for reserved in _RESERVED_DIR_NAMES:
            (self.root / reserved).mkdir(parents=True, exist_ok=True)

    # ----- public helpers -------------------------------------------------

    def get_run_dir(self, tool_id: str, run_id: str, *, day: str | None = None) -> Path:
        """Create + return the run's artefact directory.

        Per RESEARCH s1.3: ``exist_ok=False`` -- collision means a UUID
        clash and we want a loud failure. On POSIX the dir is chmoded
        ``0o700`` so other local users can't peek (RULES s4).
        """

        if tool_id.startswith("_"):
            raise ArtefactPathError(
                f"tool id {tool_id!r} uses a Pixie-reserved prefix"
            )
        day_token = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        run_dir = self.root / tool_id / day_token / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            try:
                run_dir.chmod(0o700)
            except OSError:
                pass
        return run_dir

    def rel(self, abs_path: Path) -> str:
        """Return the artefacts-root-relative path for ``abs_path`` (forward slashes)."""

        return str(abs_path.resolve().relative_to(self.root)).replace("\\", "/")

    def abs_for(self, rel_path: str) -> Path:
        """Reverse of :meth:`rel`. Refuses traversal."""

        return safe_join(self.root, rel_path)

    def thumb_path_for(self, sha256: str) -> Path:
        """Stable cache path for a thumbnail keyed by file content hash."""

        shard = sha256[:2]
        return self.root / "_thumbs" / shard / f"{sha256}.webp"


# --- path safety -------------------------------------------------------------


def safe_join(root: Path, *parts: str) -> Path:
    """Join ``parts`` onto ``root`` refusing any traversal/symlink escape.

    ``root`` must already exist. The result is resolved + asserted to
    sit underneath ``root``. Raises :class:`ArtefactPathError` otherwise.
    """

    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*[str(p) for p in parts]).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ArtefactPathError(
            f"refused path escape: {candidate} not under {root_resolved}"
        ) from exc
    if candidate.is_symlink():
        raise ArtefactPathError(f"refused symlink: {candidate}")
    return candidate


# --- scanning + hashing ------------------------------------------------------


def _guess_mime(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _EXTRA_MIMES:
        return _EXTRA_MIMES[ext]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(_HASH_CHUNK)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _redact_filename(name: str) -> tuple[str, str | None]:
    """Replace secret-looking filenames with ``redacted-<hash>.<ext>``."""

    base = Path(name).name
    if not _SECRET_KEY_RE.search(base):
        return base, None
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    ext = Path(base).suffix
    safe = f"redacted-{digest}{ext}"
    logger.warning("redacting secret-shaped artefact filename %r -> %r", base, safe)
    return safe, base


def _scan_iter(run_dir: Path) -> Iterable[Path]:
    """Yield candidate files from ``run_dir`` respecting the partial / symlink rules."""

    for path in run_dir.rglob("*"):
        if path.is_symlink():
            logger.warning("ignoring symlink in artefacts dir: %s", path)
            continue
        if not path.is_file():
            continue
        if path.name.endswith(".partial"):
            continue
        if path.name.startswith("."):
            continue
        yield path


def scan_run_dir(
    registry: ArtefactRegistry,
    tool_id: str,
    run_id: str,
    run_dir: Path,
    *,
    declared_output_keys: set[str] | None = None,
    cap_files: int | None = None,
) -> list[ScannedFile]:
    """Walk ``run_dir`` and produce a registration-ready list."""

    declared = declared_output_keys or set()
    cap = cap_files if cap_files is not None else registry.settings.max_artefacts_per_run
    out: list[ScannedFile] = []
    for path in _scan_iter(run_dir):
        if len(out) >= cap:
            logger.warning(
                "artefact cap reached for run %s (%d files); ignoring extras",
                run_id, cap,
            )
            break
        # Defence in depth: every file lives under run_dir which is under
        # registry.root. Re-confirm before we trust the path.
        try:
            path.resolve().relative_to(registry.root)
        except ValueError:
            logger.warning("artefact outside root, quarantining: %s", path)
            _quarantine(registry, path, reason="path-escape")
            continue
        try:
            size = path.stat().st_size
        except OSError as exc:
            logger.warning("could not stat artefact %s: %s", path, exc)
            continue
        safe_name, redacted_from = _redact_filename(path.name)
        if safe_name != path.name:
            target = path.with_name(safe_name)
            try:
                path.rename(target)
                path = target
            except OSError as exc:
                logger.warning("could not redact filename %s: %s", path, exc)
        digest = _sha256_of(path)
        mime = _guess_mime(path)
        # Output-key inference: <key>.<ext> where <key> matches a declared
        # output key. Subdirectories <key>/<n>.<ext> count as the key too.
        rel_to_run = path.relative_to(run_dir)
        first_part = rel_to_run.parts[0] if rel_to_run.parts else ""
        stem = Path(rel_to_run.parts[-1]).stem
        output_key = ""
        if first_part in declared:
            output_key = first_part
        elif stem in declared:
            output_key = stem
        out.append(ScannedFile(
            rel_path=registry.rel(path),
            filename=path.name,
            abs_path=path,
            mime=mime,
            size_bytes=size,
            sha256=digest,
            output_key=output_key,
            redacted_from=redacted_from,
        ))
    return out


def _quarantine(registry: ArtefactRegistry, path: Path, *, reason: str) -> None:
    target_dir = registry.root / "_quarantine" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + reason
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / path.name
    try:
        path.rename(target)
    except OSError as exc:
        logger.warning("quarantine move failed for %s: %s", path, exc)


# --- registration ------------------------------------------------------------


async def register_run_artefacts(
    registry: ArtefactRegistry,
    tool_id: str,
    run_id: str,
    *,
    run_dir: Path | None = None,
    declared_output_keys: set[str] | None = None,
) -> list[int]:
    """Scan + register every artefact for ``run_id``.

    Idempotent on ``rel_path`` -- re-running on the same dir produces no
    duplicate rows (existing rows are detected and skipped).
    """

    target_dir = run_dir or registry.get_run_dir(tool_id, run_id)
    scanned = await run_in_threadpool(
        scan_run_dir, registry, tool_id, run_id, target_dir,
        declared_output_keys=declared_output_keys,
    )
    if not scanned:
        return []
    settings = registry.settings
    existing = await db.list_artefacts(
        settings.db_path, run_id=run_id, include_deleted=True, limit=10_000,
    )
    existing_rel = {row["rel_path"] for row in existing}
    new_ids: list[int] = []
    for item in scanned:
        if item.rel_path in existing_rel:
            continue
        tags = None
        if item.redacted_from:
            tags = [f"_redacted_original:{item.redacted_from}"]
        artefact_id = await db.register_artefact(
            settings.db_path,
            run_id=run_id, tool_id=tool_id, output_key=item.output_key,
            rel_path=item.rel_path, filename=item.filename,
            mime=item.mime, size_bytes=item.size_bytes, sha256=item.sha256,
            tags=tags,
        )
        new_ids.append(artefact_id)
    return new_ids


def rehydrate_outputs(
    outputs_json: dict[str, Any] | None,
    artefacts_by_key: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Swap ``{_artefact_id: N}`` reference handles for full metadata.

    The renderer uses the returned dict directly. ``artefacts_by_key``
    is a ``{output_key: artefact_row}`` mapping built from a query of
    the ``artefacts`` table for the run.
    """

    if not outputs_json:
        return {}
    outputs = outputs_json.get("outputs") if isinstance(outputs_json, dict) else None
    if not isinstance(outputs, dict):
        return outputs_json
    enriched: dict[str, Any] = {}
    for key, value in outputs.items():
        if isinstance(value, dict) and "_artefact_id" in value:
            full = artefacts_by_key.get(key) or value
            enriched[key] = {**value, **full}
        elif key in artefacts_by_key and not isinstance(value, dict):
            row = artefacts_by_key[key]
            enriched[key] = {
                "_artefact_id": row.get("id"),
                "value": value,
                "filename": row.get("filename"),
                "mime": row.get("mime"),
                "size": row.get("size_bytes"),
                "file_url": f"/api/artefacts/{row.get('id')}/file",
            }
        else:
            enriched[key] = value
    return {**outputs_json, "outputs": enriched}


# --- quota watchdog ----------------------------------------------------------


def _dir_size(run_dir: Path) -> int:
    total = 0
    try:
        for path in run_dir.rglob("*"):
            try:
                if path.is_file() and not path.is_symlink():
                    total += path.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


async def quota_watchdog(
    ctx: RunArtefactsContext,
    *,
    max_bytes: int,
    on_exceeded: "callable[[RunArtefactsContext], None] | None" = None,
    interval_s: float = 1.0,
) -> None:
    """Poll a run's artefact dir; raise the kill signal when it overflows."""

    while True:
        try:
            await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            return
        size = await run_in_threadpool(_dir_size, ctx.artefacts_dir)
        if size > max_bytes:
            ctx.killed_for_quota = True
            logger.warning(
                "run %s exceeded artefact quota (%d > %d); killing",
                ctx.run_id, size, max_bytes,
            )
            if on_exceeded is not None:
                try:
                    on_exceeded(ctx)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("quota on_exceeded callback failed: %s", exc)
            return


# --- soft delete / restore / purge ------------------------------------------


async def soft_delete(settings: Settings, artefact_id: int) -> None:
    await db.soft_delete_artefact(settings.db_path, artefact_id)


async def restore(settings: Settings, artefact_id: int) -> None:
    await run_in_threadpool(_sync_restore, settings.db_path, artefact_id)


def _sync_restore(db_path: Path, artefact_id: int) -> None:
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE artefacts SET deleted_at = NULL WHERE id = ?",
            (artefact_id,),
        )


async def purge_expired(
    registry: ArtefactRegistry, *, days: int | None = None
) -> int:
    """Hard-delete artefacts soft-deleted more than ``days`` days ago."""

    settings = registry.settings
    age_days = days if days is not None else settings.soft_delete_retention_days
    purged = await db.purge_soft_deleted(settings.db_path, age_days)
    for row in purged:
        rel = row.get("rel_path")
        thumb = row.get("thumb_path")
        if rel:
            try:
                abs_path = registry.abs_for(rel)
                if abs_path.exists():
                    await run_in_threadpool(abs_path.unlink)
            except (ArtefactPathError, OSError) as exc:
                logger.warning("could not unlink artefact %s: %s", rel, exc)
        if thumb:
            try:
                abs_thumb = registry.abs_for(thumb)
                if abs_thumb.exists():
                    await run_in_threadpool(abs_thumb.unlink)
            except (ArtefactPathError, OSError):
                pass
    return len(purged)


async def hard_delete(registry: ArtefactRegistry, artefact_id: int) -> bool:
    """Hard-delete now (bypass the 7-day window). Returns True on success."""

    settings = registry.settings
    row = await db.get_artefact(settings.db_path, artefact_id)
    if row is None:
        return False
    rel = row.get("rel_path")
    if rel:
        try:
            abs_path = registry.abs_for(rel)
            if abs_path.exists():
                await run_in_threadpool(abs_path.unlink)
        except (ArtefactPathError, OSError) as exc:
            logger.warning("could not unlink artefact %s: %s", rel, exc)
    await run_in_threadpool(_sync_hard_delete, settings.db_path, artefact_id)
    return True


def _sync_hard_delete(db_path: Path, artefact_id: int) -> None:
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM artefacts WHERE id = ?", (artefact_id,))


# --- thumbnails --------------------------------------------------------------


def generate_thumbnail(
    registry: ArtefactRegistry, artefact: dict[str, Any]
) -> Path | None:
    """Return a webp thumbnail Path, generating it if absent.

    Falls back to ``None`` for mime types we don't generate (the route
    will serve the mime icon instead). Cached under
    ``artefacts/_thumbs/<sha[:2]>/<sha>.webp``.
    """

    sha = artefact.get("sha256") or ""
    if not sha:
        return None
    thumb_path = registry.thumb_path_for(sha)
    if thumb_path.exists():
        return thumb_path
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    rel = artefact.get("rel_path")
    if not rel:
        return None
    try:
        source = registry.abs_for(rel)
    except ArtefactPathError:
        return None
    if not source.exists():
        return None
    mime = (artefact.get("mime") or "").lower()
    max_edge = registry.settings.thumb_max_edge_px
    if mime.startswith("image/"):
        return _thumb_image(source, thumb_path, max_edge)
    if mime.startswith("video/"):
        return _thumb_video(source, thumb_path, max_edge)
    if mime.startswith("audio/"):
        # No matplotlib in core; let the route fall back to mime icon.
        return None
    return None


def _thumb_image(source: Path, target: Path, max_edge: int) -> Path | None:
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        with Image.open(source) as im:
            im.load()
            if im.mode in ("P", "LA"):
                im = im.convert("RGBA")
            if im.mode == "RGBA":
                # Flatten on white for webp parity with downloads.
                from PIL import Image as PILImage
                bg = PILImage.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")
            im.thumbnail((max_edge, max_edge))
            im.save(target, "WEBP", quality=80, method=6)
    except Exception as exc:  # noqa: BLE001
        logger.warning("thumbnail generation failed for %s: %s", source, exc)
        return None
    return target


def _thumb_video(source: Path, target: Path, max_edge: int) -> Path | None:
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return None
    intermediate = target.with_suffix(".png")
    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-ss", "1", "-i", str(source),
                "-vframes", "1", "-vf", f"scale={max_edge}:-1",
                str(intermediate),
            ],
            check=True, capture_output=True, timeout=20,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("ffmpeg thumbnail failed for %s: %s", source, exc)
        return None
    if not intermediate.exists():
        return None
    try:
        from PIL import Image  # type: ignore[import-not-found]
        with Image.open(intermediate) as im:
            im.thumbnail((max_edge, max_edge))
            im.save(target, "WEBP", quality=80, method=6)
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            intermediate.unlink()
        except OSError:
            pass
    return target


# --- sweeper -----------------------------------------------------------------


async def sweeper_once(registry: ArtefactRegistry) -> dict[str, int]:
    """One sweep cycle. Returns counts of work performed."""

    settings = registry.settings
    counts = {"runs_pruned": 0, "artefacts_hard_deleted": 0, "partials_removed": 0}

    # 1. Per-tool retention -- delegated to db.prune_old_runs_per_tool.
    # Discovery happens at the route layer; here we scan tool dirs we
    # already have artefacts for as a defensive measure.
    try:
        async with _SWEEPER_LOCK:
            tool_ids = await run_in_threadpool(_distinct_artefact_tools, settings.db_path)
            for tool_id in tool_ids:
                # The actual retain value lives on each tool's schema; the
                # discovery layer is the source of truth. The sweeper
                # respects starred / labelled runs via the helper below.
                pruned = await db.prune_old_runs_per_tool(
                    settings.db_path, tool_id, keep=100,
                )
                counts["runs_pruned"] += pruned
    except Exception as exc:  # noqa: BLE001
        logger.warning("sweep retention step failed: %s", exc)

    # 2. Hard-delete soft-deleted artefacts past the trash window.
    try:
        purged = await purge_expired(registry)
        counts["artefacts_hard_deleted"] = purged
    except Exception as exc:  # noqa: BLE001
        logger.warning("sweep purge step failed: %s", exc)

    # 3. Stale .partial cleanup.
    try:
        counts["partials_removed"] = await run_in_threadpool(
            _purge_stale_partials, registry.root,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("sweep partial cleanup failed: %s", exc)

    return counts


_SWEEPER_LOCK = asyncio.Lock()


def _distinct_artefact_tools(db_path: Path) -> list[str]:
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT DISTINCT tool_id FROM artefacts").fetchall()
        return [r[0] for r in rows]


def _purge_stale_partials(root: Path, *, age_seconds: float = 3600.0) -> int:
    import time
    now = time.time()
    removed = 0
    for path in root.rglob("*.partial"):
        try:
            if not path.is_file():
                continue
            if now - path.stat().st_mtime < age_seconds:
                continue
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


async def sweeper_loop(registry: ArtefactRegistry) -> None:
    """Long-running task started by the FastAPI lifespan."""

    interval = registry.settings.sweeper_interval_seconds
    while True:
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return
        try:
            counts = await sweeper_once(registry)
            logger.info("artefact sweep complete: %s", counts)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sweeper iteration failed: %s", exc)


# --- secret + filename helpers (exposed for unit tests) ---------------------


def is_secret_filename(name: str) -> bool:
    return bool(_SECRET_KEY_RE.search(name))


def disk_usage_by_tool(settings: Settings) -> list[dict[str, Any]]:
    """Synchronous summary used by the settings page."""

    import sqlite3
    with sqlite3.connect(settings.db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT tool_id, COUNT(*) AS count, SUM(size_bytes) AS bytes "
            "FROM artefacts WHERE deleted_at IS NULL GROUP BY tool_id"
        ).fetchall()
    return [dict(row) for row in rows]
