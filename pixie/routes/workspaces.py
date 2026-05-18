"""Workspace API routes — create/list/rename/delete + membership.

Workspaces partition a user's tools into focused buckets so the
sidebar stays scannable past N=20. Each tool may belong to zero,
one, or many workspaces; the sidebar shows one at a time.

The DB helpers (``create_workspace``, ``list_workspaces``,
``add_tool_to_workspace`` etc.) already exist in ``pixie/db.py``
from the X-a scaffold pass; this router wires them to the public
JSON surface defined in ``RESEARCH_scale.md`` s16.5.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from pixie import db
from pixie.config import Settings

logger = logging.getLogger("pixie.routes.workspaces")

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    colour: str | None = None
    sort_order: int = 0


class WorkspacePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    colour: str | None = None
    sort_order: int | None = None
    collapsed: bool | None = None


async def _workspace_summary(
    db_path, row: dict[str, Any]
) -> dict[str, Any]:
    """Decorate a workspace row with its current tool-id membership."""

    member_ids = await db.list_tools_in_workspace(db_path, row["id"])
    return {
        "id": row["id"],
        "name": row["name"],
        "colour": row.get("colour"),
        "sort_order": row.get("sort_order", 0),
        "collapsed": bool(row.get("collapsed")),
        "created_at": row.get("created_at"),
        "tool_count": len(member_ids),
        "tool_ids": member_ids,
    }


@router.get("")
async def list_workspaces_route(settings: SettingsDep) -> list[dict[str, Any]]:
    rows = await db.list_workspaces(settings.db_path)
    return [await _workspace_summary(settings.db_path, row) for row in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workspace_route(
    payload: WorkspaceCreate, settings: SettingsDep
) -> dict[str, Any]:
    existing = {row["name"].lower() for row in await db.list_workspaces(settings.db_path)}
    if payload.name.lower() in existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"workspace {payload.name!r} already exists",
        )
    workspace_id = await db.create_workspace(
        settings.db_path,
        payload.name,
        colour=payload.colour,
        sort_order=payload.sort_order,
    )
    rows = await db.list_workspaces(settings.db_path)
    row = next((r for r in rows if r["id"] == workspace_id), None)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="workspace created but lookup failed",
        )
    return await _workspace_summary(settings.db_path, row)


@router.patch("/{workspace_id}")
async def patch_workspace_route(
    workspace_id: int, payload: WorkspacePatch, settings: SettingsDep
) -> dict[str, Any]:
    rows = await db.list_workspaces(settings.db_path)
    if not any(r["id"] == workspace_id for r in rows):
        raise HTTPException(status_code=404, detail=f"workspace {workspace_id} not found")
    await db.rename_workspace(
        settings.db_path,
        workspace_id,
        name=payload.name,
        colour=payload.colour,
        sort_order=payload.sort_order,
        collapsed=payload.collapsed,
    )
    rows = await db.list_workspaces(settings.db_path)
    row = next((r for r in rows if r["id"] == workspace_id), None)
    assert row is not None
    return await _workspace_summary(settings.db_path, row)


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_workspace_route(workspace_id: int, settings: SettingsDep) -> None:
    rows = await db.list_workspaces(settings.db_path)
    if not any(r["id"] == workspace_id for r in rows):
        raise HTTPException(status_code=404, detail=f"workspace {workspace_id} not found")
    await db.delete_workspace(settings.db_path, workspace_id)


@router.post(
    "/{workspace_id}/tools/{tool_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def add_tool_to_workspace_route(
    workspace_id: int, tool_id: str, settings: SettingsDep
) -> None:
    rows = await db.list_workspaces(settings.db_path)
    if not any(r["id"] == workspace_id for r in rows):
        raise HTTPException(status_code=404, detail=f"workspace {workspace_id} not found")
    await db.add_tool_to_workspace(settings.db_path, tool_id, workspace_id)


@router.delete(
    "/{workspace_id}/tools/{tool_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def remove_tool_from_workspace_route(
    workspace_id: int, tool_id: str, settings: SettingsDep
) -> None:
    rows = await db.list_workspaces(settings.db_path)
    if not any(r["id"] == workspace_id for r in rows):
        raise HTTPException(status_code=404, detail=f"workspace {workspace_id} not found")
    await db.remove_tool_from_workspace(settings.db_path, tool_id, workspace_id)


@router.post(
    "/{workspace_id}/activate",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def activate_workspace_route(
    workspace_id: int, settings: SettingsDep
) -> None:
    """Persist the active workspace; the sidebar reads this on every render."""

    if workspace_id <= 0:
        await db.set_setting(settings.db_path, "active_workspace_id", "")
        return
    rows = await db.list_workspaces(settings.db_path)
    if not any(r["id"] == workspace_id for r in rows):
        raise HTTPException(status_code=404, detail=f"workspace {workspace_id} not found")
    await db.set_setting(
        settings.db_path, "active_workspace_id", str(workspace_id)
    )
