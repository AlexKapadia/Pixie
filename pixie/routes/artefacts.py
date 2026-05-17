"""HTTP routes for the artefact registry.

All endpoints sit under ``/api/artefacts`` except the file-serving
routes which use the shorter ``/artefacts/{id}/file`` paths so the
``<img src>`` URLs the renderer emits stay short and cacheable.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from pixie import artefacts, db
from pixie.artefacts import ArtefactPathError, ArtefactRegistry
from pixie.config import Settings

logger = logging.getLogger("pixie.routes.artefacts")

router = APIRouter()


# --- dependencies ------------------------------------------------------------


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_registry(request: Request) -> ArtefactRegistry:
    return request.app.state.artefacts


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
RegistryDep = Annotated[ArtefactRegistry, Depends(get_registry)]


# --- pydantic shapes ---------------------------------------------------------


class ArtefactPatch(BaseModel):
    label: str | None = Field(None, max_length=120)
    tags: list[str] | None = Field(None, max_length=16)
    starred: bool | None = None


class BulkAction(BaseModel):
    ids: list[int] = Field(..., max_length=500)
    action: str
    label: str | None = Field(None, max_length=120)
    tags: list[str] | None = None


# --- listing -----------------------------------------------------------------


@router.get("/api/artefacts")
async def list_artefacts(
    settings: SettingsDep,
    tool: str | None = None,
    mime: str | None = None,
    starred: bool | None = None,
    label: str | None = None,
    tag: str | None = None,
    since: str | None = None,
    until: str | None = None,
    sort: str = "date_desc",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(limit, 250))
    offset = max(0, min(offset, 100_000))
    mime_filter = (mime + "%") if mime else None
    rows = await db.list_artefacts(
        settings.db_path,
        tool_id=tool, mime=mime_filter, starred=starred,
        label=None, tag=tag,
        limit=limit, offset=offset,
    )
    # Server-side label substring search (sqlite LIKE is in the helper; we
    # also widen it to filename here so the library's single search box covers
    # both).
    if label:
        needle = label.lower()
        rows = [
            r for r in rows
            if needle in (r.get("label") or "").lower()
            or needle in (r.get("filename") or "").lower()
        ]
    return {
        "items": [_serialise(r) for r in rows],
        "limit": limit, "offset": offset,
        "next_offset": offset + len(rows),
    }


def _serialise(row: dict[str, Any]) -> dict[str, Any]:
    art_id = row.get("id")
    return {
        "id": art_id,
        "run_id": row.get("run_id"),
        "tool_id": row.get("tool_id"),
        "output_key": row.get("output_key"),
        "filename": row.get("filename"),
        "mime": row.get("mime"),
        "size_bytes": row.get("size_bytes"),
        "sha256": row.get("sha256"),
        "created_at": row.get("created_at"),
        "starred": bool(row.get("starred")),
        "label": row.get("label"),
        "tags": row.get("tags") or [],
        "rel_path": row.get("rel_path"),
        "file_url": f"/api/artefacts/{art_id}/file",
        "thumb_url": f"/api/artefacts/{art_id}/thumb",
        "preview_url": f"/api/artefacts/{art_id}/preview",
    }


@router.get("/api/artefacts/{artefact_id}")
async def get_artefact(artefact_id: int, settings: SettingsDep) -> dict[str, Any]:
    row = await db.get_artefact(settings.db_path, artefact_id)
    if row is None or row.get("deleted_at"):
        raise HTTPException(404, f"artefact {artefact_id} not found")
    return _serialise(row)


# --- file / thumb / preview --------------------------------------------------


@router.get("/api/artefacts/{artefact_id}/file")
async def artefact_file(
    artefact_id: int,
    settings: SettingsDep,
    registry: RegistryDep,
    download: bool = False,
) -> Response:
    row = await db.get_artefact(settings.db_path, artefact_id)
    if row is None or row.get("deleted_at"):
        raise HTTPException(404, f"artefact {artefact_id} not found")
    try:
        path = registry.abs_for(row["rel_path"])
    except ArtefactPathError as exc:
        logger.warning("blocked artefact path serve: %s", exc)
        raise HTTPException(403, str(exc)) from exc
    if not path.exists():
        raise HTTPException(410, "artefact file no longer on disk")
    disposition = "attachment" if download else "inline"
    filename = row.get("filename") or path.name
    return FileResponse(
        path,
        media_type=row.get("mime") or "application/octet-stream",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.get("/api/artefacts/{artefact_id}/thumb")
async def artefact_thumb(
    artefact_id: int,
    settings: SettingsDep,
    registry: RegistryDep,
) -> Response:
    from fastapi.concurrency import run_in_threadpool

    row = await db.get_artefact(settings.db_path, artefact_id)
    if row is None or row.get("deleted_at"):
        raise HTTPException(404, "artefact not found")
    thumb_path = await run_in_threadpool(artefacts.generate_thumbnail, registry, row)
    if thumb_path is None:
        # Fallback: a 1x1 transparent gif so the client doesn't show a broken image.
        return Response(
            b"GIF87a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            media_type="image/gif",
            headers={"Cache-Control": "public, max-age=60"},
        )
    return FileResponse(
        thumb_path, media_type="image/webp",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/api/artefacts/{artefact_id}/preview")
async def artefact_preview(
    artefact_id: int,
    settings: SettingsDep,
    registry: RegistryDep,
    lines: int = 10,
) -> Response:
    from fastapi.concurrency import run_in_threadpool

    row = await db.get_artefact(settings.db_path, artefact_id)
    if row is None or row.get("deleted_at"):
        raise HTTPException(404, "artefact not found")
    mime = (row.get("mime") or "").lower()
    try:
        path = registry.abs_for(row["rel_path"])
    except ArtefactPathError as exc:
        raise HTTPException(403, str(exc)) from exc
    if not path.exists():
        raise HTTPException(410, "artefact file no longer on disk")
    lines_capped = max(1, min(lines, 200))
    if mime.startswith("text/") or mime in {"application/json", "application/x-ndjson"}:
        snippet = await run_in_threadpool(_read_head_lines, path, lines_capped)
        return Response(snippet, media_type="text/plain; charset=utf-8")
    if mime in {"text/csv", "application/csv", "text/tab-separated-values"}:
        snippet = await run_in_threadpool(_read_head_lines, path, lines_capped)
        return Response(snippet, media_type="text/csv; charset=utf-8")
    if mime.startswith("image/"):
        return Response(status_code=204, headers={"X-Preview-Hint": "use-thumb"})
    raise HTTPException(415, "preview unavailable for this mime type")


def _read_head_lines(path: Path, lines: int) -> str:
    out: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as fp:
        for idx, line in enumerate(fp):
            if idx >= lines:
                break
            out.append(line)
    return "".join(out)


# --- star / patch / delete / restore ----------------------------------------


@router.post("/api/artefacts/{artefact_id}/star")
async def star(artefact_id: int, settings: SettingsDep) -> dict[str, Any]:
    await db.star_artefact(settings.db_path, artefact_id, True)
    return {"id": artefact_id, "starred": True}


@router.post("/api/artefacts/{artefact_id}/unstar")
async def unstar(artefact_id: int, settings: SettingsDep) -> dict[str, Any]:
    await db.star_artefact(settings.db_path, artefact_id, False)
    return {"id": artefact_id, "starred": False}


@router.patch("/api/artefacts/{artefact_id}")
async def patch_artefact(
    artefact_id: int,
    patch: ArtefactPatch,
    settings: SettingsDep,
) -> dict[str, Any]:
    if patch.label is not None or patch.tags is not None:
        existing = await db.get_artefact(settings.db_path, artefact_id)
        if existing is None:
            raise HTTPException(404, "artefact not found")
        await db.label_artefact(
            settings.db_path, artefact_id,
            label=patch.label if patch.label is not None else existing.get("label"),
            tags=patch.tags if patch.tags is not None else (existing.get("tags") or []),
        )
    if patch.starred is not None:
        await db.star_artefact(settings.db_path, artefact_id, patch.starred)
    row = await db.get_artefact(settings.db_path, artefact_id)
    if row is None:
        raise HTTPException(404, "artefact not found")
    return _serialise(row)


@router.delete("/api/artefacts/{artefact_id}")
async def delete_artefact(
    artefact_id: int,
    settings: SettingsDep,
    registry: RegistryDep,
    hard: bool = False,
) -> dict[str, Any]:
    if hard:
        ok = await artefacts.hard_delete(registry, artefact_id)
        if not ok:
            raise HTTPException(404, "artefact not found")
        return {"id": artefact_id, "hard_deleted": True}
    await artefacts.soft_delete(settings, artefact_id)
    return {"id": artefact_id, "deleted_at": datetime.now(timezone.utc).isoformat()}


@router.post("/api/artefacts/{artefact_id}/restore")
async def restore_artefact(
    artefact_id: int,
    settings: SettingsDep,
    registry: RegistryDep,
) -> dict[str, Any]:
    await artefacts.restore(settings, artefact_id)
    row = await db.get_artefact(settings.db_path, artefact_id)
    if row is None:
        raise HTTPException(404, "artefact not found")
    return _serialise(row)


@router.post("/api/artefacts/purge-expired")
async def purge_expired(registry: RegistryDep, days: int = 7) -> dict[str, int]:
    purged = await artefacts.purge_expired(registry, days=days)
    return {"purged": purged}


# --- bulk --------------------------------------------------------------------


@router.post("/api/artefacts/bulk")
async def bulk_action(
    payload: BulkAction,
    settings: SettingsDep,
    registry: RegistryDep,
) -> dict[str, Any]:
    affected = 0
    if not payload.ids:
        return {"affected": 0}
    action = payload.action.lower()
    if action == "star":
        for art_id in payload.ids:
            await db.star_artefact(settings.db_path, art_id, True); affected += 1
    elif action == "unstar":
        for art_id in payload.ids:
            await db.star_artefact(settings.db_path, art_id, False); affected += 1
    elif action == "delete":
        for art_id in payload.ids:
            await artefacts.soft_delete(settings, art_id); affected += 1
    elif action == "hard_delete":
        for art_id in payload.ids:
            if await artefacts.hard_delete(registry, art_id):
                affected += 1
    elif action == "label":
        for art_id in payload.ids:
            await db.label_artefact(
                settings.db_path, art_id,
                label=payload.label, tags=payload.tags,
            )
            affected += 1
    else:
        raise HTTPException(422, f"unknown bulk action {action!r}")
    return {"affected": affected}
