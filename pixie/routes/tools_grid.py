"""Full-screen ``/tools`` grid view + per-tool state mutations + disk audit.

The grid is the "complete surface" the sidebar never has to be:
filterable by tag/category/workspace/status, sortable by name/last-used,
bulk-select for archive/pin/tag. The disk audit is the storage-pressure
visibility surface specified in ``RESEARCH_scale.md`` s5.
"""

from __future__ import annotations

import logging
import os
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from pixie import db
from pixie.config import Settings
from pixie.discovery import DiscoveredTool, discover_tools
from pixie.launcher import Launcher
from pixie.routes import dashboard

logger = logging.getLogger("pixie.routes.tools_grid")

router = APIRouter()


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_launcher(request: Request) -> Launcher:
    return request.app.state.launcher


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
LauncherDep = Annotated[Launcher, Depends(get_launcher)]
TemplatesDep = Annotated[Jinja2Templates, Depends(get_templates)]


_TAG_RE_OK = "abcdefghijklmnopqrstuvwxyz0123456789-_"


def _normalise_tag(raw: str) -> str:
    cleaned = raw.strip().lower()
    if not cleaned or len(cleaned) > 32:
        raise HTTPException(status_code=400, detail="tag must be 1-32 chars")
    if any(ch not in _TAG_RE_OK for ch in cleaned):
        raise HTTPException(
            status_code=400, detail="tag may only contain a-z0-9-_"
        )
    return cleaned


def _format_size(value: int | None) -> str:
    if not value:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"


def _relative(value: str | None) -> str:
    if not value:
        return "never"
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    delta = datetime.now(timezone.utc) - when.astimezone(timezone.utc)
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 14:
        return f"{days}d ago"
    return when.date().isoformat()


def _walk_dir_bytes(path: Path) -> int:
    """Sum of file sizes under ``path``. Best-effort; missing dirs return 0."""

    if not path.exists():
        return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for fname in files:
            try:
                total += (Path(root) / fname).stat().st_size
            except OSError:
                continue
    return total


def _audit_one_tool(tool: DiscoveredTool) -> dict[str, Any]:
    venv_bytes = _walk_dir_bytes(tool.path / ".venv")
    data_bytes = _walk_dir_bytes(tool.path / "data")
    models_bytes = _walk_dir_bytes(tool.path / "models")
    cache_bytes = _walk_dir_bytes(tool.path / "__pycache__")
    total = venv_bytes + data_bytes + models_bytes + cache_bytes
    return {
        "tool_id": tool.tool_id,
        "venv_bytes": venv_bytes,
        "data_bytes": data_bytes,
        "models_bytes": models_bytes,
        "cache_bytes": cache_bytes,
        "total_bytes": total,
    }


async def _runtime_status(launcher: Launcher, tool: DiscoveredTool) -> str:
    if tool.schema is None:
        return "failed"
    if launcher.is_running(tool.tool_id):
        return "running"
    return "dormant"


async def _build_grid_cards(
    settings: Settings,
    launcher: Launcher,
    *,
    tag: str | None,
    category: str | None,
    workspace_id: int | None,
    status_filter: str | None,
    validation_filter: str | None,
    show_archived: bool,
    sort: str,
) -> dict[str, Any]:
    discovered = discover_tools(settings.tools_dir)
    workspace_tool_ids: set[str] | None = None
    if workspace_id is not None and workspace_id > 0:
        workspace_tool_ids = set(
            await db.list_tools_in_workspace(settings.db_path, workspace_id)
        )

    cards: list[dict[str, Any]] = []
    all_tags: set[str] = set()
    all_categories: set[str] = set()
    for tool in discovered:
        state = await db.get_tool_state(settings.db_path, tool.tool_id) or {}
        tags = await db.list_tags(settings.db_path, tool.tool_id)
        for entry in tags:
            all_tags.add(entry)
        archived = bool(state.get("archived"))
        if archived and not show_archived:
            continue
        if show_archived and not archived:
            # show_archived is an exclusive view
            continue
        tool_category = (
            tool.schema.category if tool.schema and tool.schema.category else None
        )
        if tool_category:
            all_categories.add(tool_category)
        if category and tool_category != category:
            continue
        if tag and tag not in tags:
            continue
        if workspace_tool_ids is not None and tool.tool_id not in workspace_tool_ids:
            continue
        status_val = await _runtime_status(launcher, tool)
        if status_filter and status_val != status_filter:
            continue
        report = await db.latest_validation_report(settings.db_path, tool.tool_id)
        validation = (report.get("overall") if report else None) or "unchecked"
        if validation_filter and validation != validation_filter:
            continue
        name = tool.schema.name if tool.schema else tool.tool_id
        description = (
            tool.schema.description if tool.schema else tool.parse_error
        ) or ""
        icon_name = (tool.schema.icon if tool.schema else None) or "bolt"
        disk_bytes = state.get("disk_bytes") or 0
        run_count_total = state.get("run_count_total") or 0
        last_run_at = state.get("last_run_at")
        cards.append({
            "tool_id": tool.tool_id,
            "name": name,
            "description": description,
            "icon": icon_name,
            "category": tool_category or "Uncategorised",
            "tags": tags,
            "status": status_val,
            "validation": validation,
            "archived": archived,
            "pinned": bool(state.get("pinned")),
            "pinned_warm": bool(state.get("pinned_warm")),
            "favourited": bool(state.get("favourited")),
            "run_count_total": run_count_total,
            "last_run_at": last_run_at,
            "last_run_label": _relative(last_run_at),
            "disk_bytes": disk_bytes,
            "disk_label": _format_size(disk_bytes),
        })

    # Sorting (default: last_run_at descending, NULLs last)
    def sort_key(card: dict[str, Any]):
        return card.get(sort)

    if sort == "name":
        cards.sort(key=lambda c: (c["name"] or "").lower())
    elif sort == "run_count_total":
        cards.sort(key=lambda c: c["run_count_total"], reverse=True)
    elif sort == "disk_bytes":
        cards.sort(key=lambda c: c["disk_bytes"], reverse=True)
    elif sort == "validation":
        order = {"fail": 0, "warn": 1, "unchecked": 2, "pass": 3}
        cards.sort(key=lambda c: order.get(c["validation"], 4))
    else:  # last_used (default)
        cards.sort(
            key=lambda c: c["last_run_at"] or "",
            reverse=True,
        )

    workspaces = await db.list_workspaces(settings.db_path)
    return {
        "cards": cards,
        "all_tags": sorted(all_tags),
        "all_categories": sorted(all_categories),
        "workspaces": workspaces,
        "total": len(cards),
    }


# ---------------------------------------------------------------------------
# Pages + fragments
# ---------------------------------------------------------------------------


@router.get("/tools", response_class=HTMLResponse)
async def tools_grid_page(
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
    templates: TemplatesDep,
    tag: str | None = None,
    category: str | None = None,
    workspace: int | None = None,
    status_filter: str | None = None,
    validation: str | None = None,
    archived: int = 0,
    sort: str = "last_run_at",
) -> HTMLResponse:
    sidebar = await dashboard._sidebar_context(settings, launcher)
    grid = await _build_grid_cards(
        settings, launcher,
        tag=tag, category=category, workspace_id=workspace,
        status_filter=status_filter, validation_filter=validation,
        show_archived=bool(archived), sort=sort,
    )
    ctx = {
        "request": request,
        "theme": settings.theme,
        "version": "0.1.0",
        "port": settings.port,
        "developer_mode": settings.developer_mode,
        "sidebar_groups": sidebar["sidebar_groups"],
        "running_count": sidebar["running_count"],
        "active_tool_id": "__tools_grid__",
        "grid": grid,
        "grid_state": {
            "tag": tag, "category": category, "workspace": workspace,
            "status_filter": status_filter, "validation": validation,
            "archived": int(bool(archived)), "sort": sort,
        },
    }
    return templates.TemplateResponse(request, "tools_grid.html", ctx)


@router.get("/tools/_grid", response_class=HTMLResponse)
async def tools_grid_fragment(
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
    templates: TemplatesDep,
    tag: str | None = None,
    category: str | None = None,
    workspace: int | None = None,
    status_filter: str | None = None,
    validation: str | None = None,
    archived: int = 0,
    sort: str = "last_run_at",
) -> HTMLResponse:
    grid = await _build_grid_cards(
        settings, launcher,
        tag=tag, category=category, workspace_id=workspace,
        status_filter=status_filter, validation_filter=validation,
        show_archived=bool(archived), sort=sort,
    )
    ctx = {
        "request": request,
        "grid": grid,
        "grid_state": {
            "tag": tag, "category": category, "workspace": workspace,
            "status_filter": status_filter, "validation": validation,
            "archived": int(bool(archived)), "sort": sort,
        },
    }
    return templates.TemplateResponse(
        request, "partials/tool_grid_cards.html", ctx
    )


# ---------------------------------------------------------------------------
# Per-tool state mutations
# ---------------------------------------------------------------------------


def _assert_tool_exists(settings: Settings, tool_id: str) -> None:
    folder = settings.tools_dir / tool_id
    if not folder.is_dir():
        # Also accept tool ids parsed from schema (tool_id != folder.name).
        for tool in discover_tools(settings.tools_dir):
            if tool.tool_id == tool_id:
                return
        raise HTTPException(status_code=404, detail=f"tool {tool_id!r} not found")


@router.post(
    "/api/tools/{tool_id}/archive", status_code=status.HTTP_204_NO_CONTENT
)
async def archive_tool_route(tool_id: str, settings: SettingsDep) -> None:
    _assert_tool_exists(settings, tool_id)
    await db.set_archived(settings.db_path, tool_id, True)


@router.post(
    "/api/tools/{tool_id}/unarchive", status_code=status.HTTP_204_NO_CONTENT
)
async def unarchive_tool_route(tool_id: str, settings: SettingsDep) -> None:
    _assert_tool_exists(settings, tool_id)
    await db.set_archived(settings.db_path, tool_id, False)


@router.post("/api/tools/{tool_id}/pin", status_code=status.HTTP_204_NO_CONTENT)
async def pin_tool_route(
    tool_id: str, settings: SettingsDep, launcher: LauncherDep
) -> None:
    _assert_tool_exists(settings, tool_id)
    await db.set_pinned_warm(settings.db_path, tool_id, True)
    launcher.set_pinned_warm(tool_id, True)


@router.post(
    "/api/tools/{tool_id}/unpin", status_code=status.HTTP_204_NO_CONTENT
)
async def unpin_tool_route(
    tool_id: str, settings: SettingsDep, launcher: LauncherDep
) -> None:
    _assert_tool_exists(settings, tool_id)
    await db.set_pinned_warm(settings.db_path, tool_id, False)
    launcher.set_pinned_warm(tool_id, False)


class TagBody(BaseModel):
    tag: str = Field(min_length=1, max_length=32)


@router.post("/api/tools/{tool_id}/tags", status_code=status.HTTP_204_NO_CONTENT)
async def add_tag_route(
    tool_id: str, payload: TagBody, settings: SettingsDep
) -> None:
    _assert_tool_exists(settings, tool_id)
    tag = _normalise_tag(payload.tag)
    await db.add_tag(settings.db_path, tool_id, tag)


@router.delete(
    "/api/tools/{tool_id}/tags/{tag}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_tag_route(
    tool_id: str, tag: str, settings: SettingsDep
) -> None:
    _assert_tool_exists(settings, tool_id)
    await db.remove_tag(settings.db_path, tool_id, _normalise_tag(tag))


# ---------------------------------------------------------------------------
# Hover-prewarm endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/api/tools/{tool_id}/prewarm", status_code=status.HTTP_202_ACCEPTED
)
async def prewarm_tool_route(
    tool_id: str, settings: SettingsDep, launcher: LauncherDep
) -> dict[str, Any]:
    """Fire-and-forget spawn used by hover-prewarm.

    Returns immediately. If the tool is already warm, this is a no-op
    that does refresh its LRU timestamp.
    """

    discovered = {t.tool_id: t for t in discover_tools(settings.tools_dir)}
    tool = discovered.get(tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"tool {tool_id!r} not found")
    if tool.schema is None:
        return {"queued": False, "reason": "schema invalid"}
    if launcher.is_running(tool_id):
        launcher.touch(tool_id)
        return {"queued": False, "reason": "already warm"}
    launcher.prewarm(tool)
    return {"queued": True}


# ---------------------------------------------------------------------------
# Disk usage audit
# ---------------------------------------------------------------------------


def _disk_cache_key() -> str:
    return "disk-usage-cache"


def _fmt_bytes(value: int) -> str:
    return _format_size(value)


@router.get("/settings/disk-usage-fragment", response_class=HTMLResponse)
async def disk_usage_fragment(
    request: Request,
    settings: SettingsDep,
    templates: TemplatesDep,
) -> HTMLResponse:
    """Render the Plotly treemap fragment for the settings Maintenance section."""

    payload = await disk_usage_route(request, settings, refresh=0)
    labels: list[str] = ["all"]
    parents: list[str] = [""]
    values: list[float] = [float(payload["totals"]["total"])]
    for entry in payload["tools"]:
        if entry["total_bytes"] <= 0:
            continue
        labels.append(entry["tool_id"])
        parents.append("all")
        values.append(float(entry["total_bytes"]))
    ctx = {
        "request": request,
        "tm_labels": labels,
        "tm_parents": parents,
        "tm_values": values,
        "totals_label": _fmt_bytes(payload["totals"]["total"]),
        "venv_label": _fmt_bytes(payload["totals"]["venv"]),
        "data_label": _fmt_bytes(payload["totals"]["data"]),
        "models_label": _fmt_bytes(payload["totals"]["models"]),
        "cache_label": _fmt_bytes(payload["totals"]["cache"]),
    }
    return templates.TemplateResponse(request, "partials/disk_treemap.html", ctx)


@router.get("/api/disk-usage")
async def disk_usage_route(
    request: Request,
    settings: SettingsDep,
    refresh: int = 0,
) -> dict[str, Any]:
    """Walk every tool's working tree and report disk-byte breakdown.

    Cached on app state for 5 minutes; pass ``?refresh=1`` to force a
    fresh walk. The walk is intentionally synchronous-in-threadpool —
    a 200-tool audit takes ~2 s and is rate-limited by the cache.
    """

    cache = getattr(request.app.state, "disk_audit_cache", None)
    now = _time.monotonic()
    if cache and not refresh and (now - cache["ts"]) < 300:
        return cache["payload"]
    discovered = discover_tools(settings.tools_dir)
    tools_breakdown: list[dict[str, Any]] = []
    archived_ids: list[str] = []
    totals = {"venv": 0, "data": 0, "models": 0, "cache": 0, "total": 0}
    for tool in discovered:
        state = await db.get_tool_state(settings.db_path, tool.tool_id) or {}
        entry = _audit_one_tool(tool)
        entry["archived"] = bool(state.get("archived"))
        if entry["archived"]:
            archived_ids.append(tool.tool_id)
        tools_breakdown.append(entry)
        totals["venv"] += entry["venv_bytes"]
        totals["data"] += entry["data_bytes"]
        totals["models"] += entry["models_bytes"]
        totals["cache"] += entry["cache_bytes"]
        totals["total"] += entry["total_bytes"]
        # Persist back so the grid view can show disk without re-walking.
        await db.update_disk_bytes(
            settings.db_path, tool.tool_id, entry["total_bytes"]
        )
    payload = {
        "tools": tools_breakdown,
        "totals": totals,
        "archived": archived_ids,
        "tools_dir": str(settings.tools_dir),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    request.app.state.disk_audit_cache = {"ts": now, "payload": payload}
    return payload
