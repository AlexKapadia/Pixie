"""Dashboard routes — the main UI shell.

Hosts ``GET /`` (full-page dashboard with sidebar + main area) and
``GET /tool/{tool_id}`` (per-tool view, htmx-swappable). Both routes
share the same context-building helpers so the sidebar always shows
the same data regardless of which URL the user lands on.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from pixie import db
from pixie.config import Settings
from pixie.discovery import DiscoveredTool, discover_tools
from pixie.launcher import Launcher

logger = logging.getLogger("pixie.routes.dashboard")

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


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------


def _runtime_status(launcher: Launcher, tool: DiscoveredTool) -> str:
    if tool.schema is None:
        return "failed"
    if launcher.is_running(tool.tool_id):
        return "running"
    return "dormant"


async def _sidebar_context(
    settings: Settings, launcher: Launcher
) -> dict[str, Any]:
    """Build the sidebar payload: grouped tools + running count.

    Honours the active workspace (stored under settings key
    ``active_workspace_id``) by filtering ``sidebar_groups`` to only
    workspace members. The full discovered list is still returned for
    callers that need the unfiltered surface (e.g. the recents query).
    """

    discovered = discover_tools(settings.tools_dir)

    # Resolve the active workspace + its membership.
    active_id_raw = await db.get_setting(settings.db_path, "active_workspace_id")
    active_workspace_id: int | None = None
    if active_id_raw and active_id_raw.isdigit():
        active_workspace_id = int(active_id_raw)
    workspaces = await db.list_workspaces(settings.db_path)
    active_workspace_name: str | None = None
    workspace_members: set[str] | None = None
    if active_workspace_id:
        for w in workspaces:
            if w["id"] == active_workspace_id:
                active_workspace_name = w["name"]
                break
        if active_workspace_name:
            workspace_members = set(
                await db.list_tools_in_workspace(
                    settings.db_path, active_workspace_id
                )
            )
        else:
            # Stale id — clear it silently.
            active_workspace_id = None

    sidebar_workspaces: list[dict[str, Any]] = []
    for w in workspaces:
        members = await db.list_tools_in_workspace(
            settings.db_path, w["id"]
        )
        sidebar_workspaces.append({
            "id": w["id"],
            "name": w["name"],
            "tool_count": len(members),
        })

    entries: list[dict[str, Any]] = []
    favourites: list[dict[str, Any]] = []
    archived_count = 0
    running_count = 0
    state_by_id: dict[str, dict[str, Any]] = {}
    for tool in discovered:
        state = await db.get_tool_state(settings.db_path, tool.tool_id) or {}
        state_by_id[tool.tool_id] = state
        if state.get("archived"):
            archived_count += 1
            continue
        report = await db.latest_validation_report(settings.db_path, tool.tool_id)
        validation = (report.get("overall") if report else None) or "unchecked"
        status = _runtime_status(launcher, tool)
        if status == "running":
            running_count += 1
        if tool.schema is not None:
            name = tool.schema.name
            category = tool.schema.category or "Uncategorised"
            description = tool.schema.description
            icon_name = tool.schema.icon
        else:
            name = tool.tool_id
            category = "Uncategorised"
            description = tool.parse_error or "Tool failed to parse"
            icon_name = "alert-triangle"
        entry = {
            "tool_id": tool.tool_id,
            "name": name,
            "category": category,
            "description": description,
            "icon": icon_name,
            "status": status,
            "validation": validation,
        }
        if state.get("pinned") or state.get("favourited"):
            favourites.append(entry)
        if workspace_members is not None and tool.tool_id not in workspace_members:
            continue
        entries.append(entry)

    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        groups.setdefault(entry["category"], []).append(entry)

    # Recent (top 5 distinct tools by most-recent started_at across all runs).
    recent: list[dict[str, Any]] = []
    try:
        raw_recent = await db.recent_runs_all_tools(settings.db_path, limit=20)
    except Exception:
        raw_recent = []
    seen: set[str] = set()
    by_id = {entry["tool_id"]: entry for entry in entries}
    for row in raw_recent:
        tid = row.get("tool_id")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        entry = by_id.get(tid)
        if entry is None:
            continue
        recent.append(entry)
        if len(recent) >= 5:
            break

    return {
        "sidebar_groups": list(groups.items()),
        "running_count": running_count,
        "discovered": discovered,
        "sidebar_workspaces": sidebar_workspaces,
        "active_workspace_id": active_workspace_id,
        "active_workspace_name": active_workspace_name,
        "sidebar_favourites": favourites[:10],
        "sidebar_recent": recent,
        "archived_count": archived_count,
        "sidebar_total_tools": len(entries),
    }


def _base_context(request: Request, settings: Settings) -> dict[str, Any]:
    return {
        "request": request,
        "theme": settings.theme,
        "version": "0.1.0",
        "port": settings.port,
        "developer_mode": settings.developer_mode,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _local_greeting() -> str:
    """Time-of-day greeting using the local clock. Sentence case, British."""

    from datetime import datetime

    hour = datetime.now().hour
    if hour < 5:
        return "Still up?"
    if hour < 12:
        return "Good morning."
    if hour < 18:
        return "Good afternoon."
    if hour < 22:
        return "Good evening."
    return "Late one?"


async def _recent_runs_across_tools(
    settings: Settings, discovered: list[DiscoveredTool], limit: int = 3
) -> list[dict[str, Any]]:
    """Best-effort: pull up to ``limit`` recent runs across all tools."""

    out: list[dict[str, Any]] = []
    name_by_id = {
        t.tool_id: (t.schema.name if t.schema is not None else t.tool_id)
        for t in discovered
    }
    fetcher = getattr(db, "recent_runs_all_tools", None)
    if callable(fetcher):
        try:
            rows = await fetcher(settings.db_path, limit=limit)
            for row in rows:
                out.append(
                    {
                        "tool_id": row.get("tool_id"),
                        "tool_name": name_by_id.get(row.get("tool_id"))
                        or row.get("tool_id"),
                        "run_id": row.get("run_id"),
                        "started_at": row.get("started_at"),
                        "summary": row.get("summary"),
                    }
                )
        except Exception:  # noqa: BLE001 — best-effort, never blocks render
            return []
    return out


@router.get("/", response_class=HTMLResponse)
async def dashboard_index(
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
    templates: TemplatesDep,
) -> HTMLResponse:
    sidebar = await _sidebar_context(settings, launcher)
    ctx = _base_context(request, settings)

    if not sidebar["sidebar_groups"]:
        # Pure-empty state: no tools on disk at all.
        ctx.update(
            sidebar_groups=[],
            running_count=0,
            active_tool_id=None,
            tools_dir=str(settings.tools_dir),
        )
        return templates.TemplateResponse(request, "empty_state.html", ctx)

    recent_runs = await _recent_runs_across_tools(
        settings, sidebar["discovered"], limit=3
    )
    ctx.update(
        sidebar_groups=sidebar["sidebar_groups"],
        running_count=sidebar["running_count"],
        sidebar_workspaces=sidebar.get("sidebar_workspaces", []),
        active_workspace_id=sidebar.get("active_workspace_id"),
        active_workspace_name=sidebar.get("active_workspace_name"),
        sidebar_favourites=sidebar.get("sidebar_favourites", []),
        sidebar_recent=sidebar.get("sidebar_recent", []),
        archived_count=sidebar.get("archived_count", 0),
        sidebar_total_tools=sidebar.get("sidebar_total_tools", 0),
        active_tool_id=None,
        greeting=_local_greeting(),
        recent_runs=recent_runs,
    )
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@router.get("/tool/{tool_id}", response_class=HTMLResponse)
async def tool_view(
    tool_id: str,
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
    templates: TemplatesDep,
) -> HTMLResponse:
    sidebar = await _sidebar_context(settings, launcher)
    discovered: list[DiscoveredTool] = sidebar["discovered"]
    folder_index = {t.path.name: t for t in discovered}
    by_id = {t.tool_id: t for t in discovered}
    tool = by_id.get(tool_id) or folder_index.get(tool_id)
    if tool is None:
        # Unknown tool — render a clean validation-shaped error rather than a 500/JSON 404.
        error_ctx = _base_context(request, settings)
        error_ctx.update(
            sidebar_groups=sidebar["sidebar_groups"],
            running_count=sidebar["running_count"],
            sidebar_workspaces=sidebar.get("sidebar_workspaces", []),
            active_workspace_id=sidebar.get("active_workspace_id"),
            active_workspace_name=sidebar.get("active_workspace_name"),
            sidebar_favourites=sidebar.get("sidebar_favourites", []),
            sidebar_recent=sidebar.get("sidebar_recent", []),
            archived_count=sidebar.get("archived_count", 0),
            sidebar_total_tools=sidebar.get("sidebar_total_tools", 0),
            active_tool_id=None,
            unknown_tool_id=tool_id,
        )
        return templates.TemplateResponse(
            request, "tool_not_found.html", error_ctx, status_code=404
        )
    if tool.schema is None:
        # Schema parse failure — surface a spawn-shape error inside the tool view shell.
        error_ctx = _base_context(request, settings)
        error_ctx.update(
            sidebar_groups=sidebar["sidebar_groups"],
            running_count=sidebar["running_count"],
            sidebar_workspaces=sidebar.get("sidebar_workspaces", []),
            active_workspace_id=sidebar.get("active_workspace_id"),
            active_workspace_name=sidebar.get("active_workspace_name"),
            sidebar_favourites=sidebar.get("sidebar_favourites", []),
            sidebar_recent=sidebar.get("sidebar_recent", []),
            archived_count=sidebar.get("archived_count", 0),
            sidebar_total_tools=sidebar.get("sidebar_total_tools", 0),
            active_tool_id=tool.tool_id,
            tool_id=tool.tool_id,
            tool_label=tool.tool_id,
            parse_error=tool.parse_error or "tool.json failed to parse",
        )
        template_name = (
            "tool_parse_error_fragment.html"
            if request.headers.get("hx-request", "").lower() == "true"
            else "tool_parse_error.html"
        )
        return templates.TemplateResponse(request, template_name, error_ctx)

    # Decorate the discovered tool with runtime info for the header partial.
    setattr(tool, "status", _runtime_status(launcher, tool))
    setattr(tool, "has_required_secrets_missing", False)
    setattr(tool, "port", None)
    setattr(tool, "pid", None)

    ctx = _base_context(request, settings)
    ctx.update(
        sidebar_groups=sidebar["sidebar_groups"],
        running_count=sidebar["running_count"],
        sidebar_workspaces=sidebar.get("sidebar_workspaces", []),
        active_workspace_id=sidebar.get("active_workspace_id"),
        active_workspace_name=sidebar.get("active_workspace_name"),
        sidebar_favourites=sidebar.get("sidebar_favourites", []),
        sidebar_recent=sidebar.get("sidebar_recent", []),
        archived_count=sidebar.get("archived_count", 0),
        sidebar_total_tools=sidebar.get("sidebar_total_tools", 0),
        active_tool_id=tool.tool_id,
        tool=tool,
        recent_runs=[],
        last_outputs=None,
    )

    # htmx fragment swap: return just the header + body so the existing
    # sidebar stays put. The fragment template renders into the same
    # #pixie-main-content slot but skips <html>/<head>.
    if request.headers.get("hx-request", "").lower() == "true":
        return templates.TemplateResponse(request, "tool_fragment.html", ctx)
    return templates.TemplateResponse(request, "tool.html", ctx)


@router.get("/tools-changed", response_class=HTMLResponse)
async def tools_changed(
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
    templates: TemplatesDep,
) -> HTMLResponse:
    """Re-render the sidebar fragment. Optional; for future watcher hooks."""

    sidebar = await _sidebar_context(settings, launcher)
    ctx = _base_context(request, settings)
    ctx.update(
        sidebar_groups=sidebar["sidebar_groups"],
        running_count=sidebar["running_count"],
        sidebar_workspaces=sidebar.get("sidebar_workspaces", []),
        active_workspace_id=sidebar.get("active_workspace_id"),
        active_workspace_name=sidebar.get("active_workspace_name"),
        sidebar_favourites=sidebar.get("sidebar_favourites", []),
        sidebar_recent=sidebar.get("sidebar_recent", []),
        archived_count=sidebar.get("archived_count", 0),
        sidebar_total_tools=sidebar.get("sidebar_total_tools", 0),
        active_tool_id=request.query_params.get("active"),
    )
    return templates.TemplateResponse(request, "partials/sidebar.html", ctx)


@router.get("/empty", response_class=HTMLResponse)
async def empty_state(
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
    templates: TemplatesDep,
) -> HTMLResponse:
    ctx = _base_context(request, settings)
    ctx.update(
        sidebar_groups=[],
        running_count=0,
        active_tool_id=None,
        tools_dir=str(settings.tools_dir),
    )
    return templates.TemplateResponse(request, "empty_state.html", ctx)
