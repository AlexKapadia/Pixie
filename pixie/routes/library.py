"""Library routes -- the cross-tool artefact gallery.

``GET /library`` renders the full page (sidebar + filters + grid +
empty state). ``GET /library/_grid`` returns the htmx fragment used by
infinite scroll and filter changes.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from pixie import db
from pixie.config import Settings
from pixie.discovery import discover_tools
from pixie.launcher import Launcher
from pixie.routes import dashboard

logger = logging.getLogger("pixie.routes.library")

router = APIRouter()


def get_launcher(request: Request) -> Launcher:
    return request.app.state.launcher


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


LauncherDep = Annotated[Launcher, Depends(get_launcher)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
TemplatesDep = Annotated[Jinja2Templates, Depends(get_templates)]


# --- helpers -----------------------------------------------------------------


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
        return ""
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


def _decorate(rows: list[dict[str, Any]], name_by_tool: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        art_id = row.get("id")
        out.append({
            **row,
            "starred": bool(row.get("starred")),
            "size_label": _format_size(row.get("size_bytes")),
            "relative": _relative(row.get("created_at")),
            "tool_name": name_by_tool.get(row.get("tool_id"), row.get("tool_id")),
            "file_url": f"/api/artefacts/{art_id}/file",
            "thumb_url": f"/api/artefacts/{art_id}/thumb",
            "preview_url": f"/api/artefacts/{art_id}/preview",
            "tags": row.get("tags") or [],
        })
    return out


async def _name_by_tool(settings: Settings) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for tool in discover_tools(settings.tools_dir):
        mapping[tool.tool_id] = tool.schema.name if tool.schema else tool.tool_id
    return mapping


async def _filter_options(settings: Settings) -> dict[str, Any]:
    name_by_tool = await _name_by_tool(settings)
    # Discover what mime families + tools currently have artefacts.
    rows = await db.list_artefacts(settings.db_path, limit=2000)
    mime_counts: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    label_set: set[str] = set()
    tag_counter: Counter[str] = Counter()
    for row in rows:
        family = (row.get("mime") or "").split("/", 1)[0] + "/"
        mime_counts[family] += 1
        tool_counts[row.get("tool_id") or "?"] += 1
        if row.get("label"):
            label_set.add(row["label"])
        for tag in row.get("tags") or []:
            if isinstance(tag, str) and not tag.startswith("_"):
                tag_counter[tag] += 1
    return {
        "tools": [
            {"id": tid, "name": name_by_tool.get(tid, tid), "count": count}
            for tid, count in tool_counts.most_common()
        ],
        "mimes": [
            {"family": family, "count": count}
            for family, count in mime_counts.most_common()
        ],
        "labels": sorted(label_set),
        "tags": [t for t, _ in tag_counter.most_common(40)],
        "total": len(rows),
    }


async def _load_artefacts(
    settings: Settings,
    *,
    tool: str | None,
    mime: str | None,
    starred: bool | None,
    label: str | None,
    tag: str | None,
    sort: str,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    mime_filter = (mime + "%") if mime else None
    rows = await db.list_artefacts(
        settings.db_path,
        tool_id=tool, mime=mime_filter, starred=starred,
        label=None, tag=tag, limit=limit, offset=offset,
    )
    if label:
        needle = label.lower()
        rows = [
            r for r in rows
            if needle in (r.get("label") or "").lower()
            or needle in (r.get("filename") or "").lower()
        ]
    if sort == "size_desc":
        rows.sort(key=lambda r: r.get("size_bytes") or 0, reverse=True)
    elif sort == "name":
        rows.sort(key=lambda r: (r.get("filename") or "").lower())
    elif sort == "tool":
        rows.sort(key=lambda r: r.get("tool_id") or "")
    # date_desc is the SQL default already.
    return rows


# --- routes ------------------------------------------------------------------


@router.get("/library", response_class=HTMLResponse)
async def library_index(
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
    templates: TemplatesDep,
    tool: str | None = None,
    mime: str | None = None,
    starred: bool | None = None,
    label: str | None = None,
    tag: str | None = None,
    sort: str = "date_desc",
    page: int = 1,
) -> HTMLResponse:
    sidebar = await dashboard._sidebar_context(settings, launcher)
    page_size = settings.library_page_size
    page = max(1, page)
    offset = (page - 1) * page_size
    rows = await _load_artefacts(
        settings, tool=tool, mime=mime, starred=starred, label=label,
        tag=tag, sort=sort, limit=page_size, offset=offset,
    )
    name_by_tool = await _name_by_tool(settings)
    cards = _decorate(rows, name_by_tool)
    options = await _filter_options(settings)
    ctx = {
        "request": request,
        "theme": settings.theme,
        "version": "0.1.0",
        "port": settings.port,
        "developer_mode": settings.developer_mode,
        "sidebar_groups": sidebar["sidebar_groups"],
        "running_count": sidebar["running_count"],
        "sidebar_workspaces": sidebar.get("sidebar_workspaces", []),
        "active_workspace_id": sidebar.get("active_workspace_id"),
        "active_workspace_name": sidebar.get("active_workspace_name"),
        "sidebar_favourites": sidebar.get("sidebar_favourites", []),
        "sidebar_recent": sidebar.get("sidebar_recent", []),
        "archived_count": sidebar.get("archived_count", 0),
        "sidebar_total_tools": sidebar.get("sidebar_total_tools", 0),
        "active_tool_id": "__library__",
        "library_count": options["total"],
        "library_cards": cards,
        "library_filters": options,
        "library_state": {
            "tool": tool, "mime": mime, "starred": starred,
            "label": label, "tag": tag, "sort": sort, "page": page,
        },
        "library_next_page": page + 1 if len(rows) == page_size else None,
    }
    return templates.TemplateResponse(request, "library.html", ctx)


@router.get("/library/_grid", response_class=HTMLResponse)
async def library_grid_fragment(
    request: Request,
    settings: SettingsDep,
    templates: TemplatesDep,
    tool: str | None = None,
    mime: str | None = None,
    starred: bool | None = None,
    label: str | None = None,
    tag: str | None = None,
    sort: str = "date_desc",
    page: int = 1,
) -> HTMLResponse:
    page_size = settings.library_page_size
    page = max(1, page)
    offset = (page - 1) * page_size
    rows = await _load_artefacts(
        settings, tool=tool, mime=mime, starred=starred, label=label,
        tag=tag, sort=sort, limit=page_size, offset=offset,
    )
    name_by_tool = await _name_by_tool(settings)
    cards = _decorate(rows, name_by_tool)
    options = await _filter_options(settings)
    state = {
        "tool": tool, "mime": mime, "starred": starred,
        "label": label, "tag": tag, "sort": sort, "page": page,
    }
    ctx = {
        "request": request,
        "library_cards": cards,
        "library_count": options["total"],
        "library_filters": options,
        "library_state": state,
        "library_next_page": page + 1 if len(rows) == page_size else None,
    }
    template = (
        "partials/library_grid.html" if cards
        else "partials/library_empty.html"
    )
    response = templates.TemplateResponse(request, template, ctx)
    # Surface the new total so the page header can keep its count in sync.
    response.headers["HX-Trigger"] = (
        '{"pixie:library-grid-updated":' f'{{"total":{options["total"]},"visible":{len(cards)}}}' "}"
    )
    return response
