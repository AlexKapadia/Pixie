"""JSON API used by Claude Code skills and the validator CLI.

Hosts ``GET /api/tools`` (sidebar list), ``POST /api/tools/{id}/stop``
(skill-driven shutdown), and ``GET /api/tools/{id}/validate`` (runs the
validator on demand and returns the report).
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from pixie import db
from pixie.config import Settings
from pixie.discovery import DiscoveredTool, discover_tools
from pixie.launcher import Launcher
from pixie.validator import validate_tool

logger = logging.getLogger("pixie.routes.api")

router = APIRouter(prefix="/api")


def get_launcher(request: Request) -> Launcher:
    return request.app.state.launcher


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


LauncherDep = Annotated[Launcher, Depends(get_launcher)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def _validation_status(report: dict[str, Any] | None) -> str:
    if report is None:
        return "unchecked"
    overall = report.get("overall")
    if overall in {"pass", "warn", "fail"}:
        return overall
    return "unchecked"


def _runtime_status(launcher: Launcher, tool: DiscoveredTool) -> str:
    if tool.schema is None:
        return "failed"
    if launcher.is_running(tool.tool_id):
        return "running"
    return "dormant"


@router.get("/tools")
async def list_tools(launcher: LauncherDep, settings: SettingsDep) -> list[dict[str, Any]]:
    """Return the sidebar list: id, name, category, runtime + validation state."""

    discovered = discover_tools(settings.tools_dir)
    out: list[dict[str, Any]] = []
    for tool in discovered:
        report = await db.latest_validation_report(settings.db_path, tool.tool_id)
        if tool.schema is not None:
            name = tool.schema.name
            category = tool.schema.category
        else:
            name = tool.tool_id
            category = None
        out.append({
            "id": tool.tool_id,
            "name": name,
            "category": category,
            "status": _runtime_status(launcher, tool),
            "validation": _validation_status(report),
        })
    return out


@router.post("/tools/{tool_id}/stop")
async def stop_tool(tool_id: str, launcher: LauncherDep) -> dict[str, str]:
    await launcher.stop(tool_id)
    return {"status": "stopped", "tool_id": tool_id}


@router.get("/tools/{tool_id}/validate")
async def validate_tool_route(
    tool_id: str, settings: SettingsDep
) -> dict[str, Any]:
    """Run the validator on demand and return the report as JSON."""

    discovered = {t.tool_id: t for t in discover_tools(settings.tools_dir)}
    # Fall back to the folder name so broken tools (where schema.id can't be
    # parsed) are still routable by their on-disk directory name.
    folder_index = {tool.path.name: tool for tool in discovered.values()}
    tool = discovered.get(tool_id) or folder_index.get(tool_id)
    if tool is None:
        candidate = settings.tools_dir / tool_id
        if not candidate.is_dir():
            raise HTTPException(status_code=404, detail=f"tool {tool_id!r} not found")
        report = await validate_tool(candidate, save_to_db=True)
    else:
        report = await validate_tool(tool.path, save_to_db=True)
    return json.loads(report.model_dump_json())
