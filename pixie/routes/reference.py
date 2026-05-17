"""Reference-fixture HTTP routes (check #12 surface).

* ``GET  /api/tools/{id}/reference-fixtures`` — picker payload.
* ``POST /api/tools/{id}/reference-check``    — run the accuracy check.

Kept in a separate module to avoid merge conflicts with parallel work
on ``pixie/routes/api.py`` (see RESEARCH_reference_validator.md §4).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from pixie.comparators import list_reference_fixtures
from pixie.config import Settings
from pixie.discovery import discover_tools
from pixie.validator import update_reference_fixtures, validate_tool

logger = logging.getLogger("pixie.routes.reference")

router = APIRouter(prefix="/api")


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


# In-process lock keyed by tool_id to prevent two concurrent
# reference-checks against the same tool clobbering each other's warm
# subprocess (per RESEARCH §8 "concurrent guard").
_LOCKS: dict[str, asyncio.Lock] = {}


def _lock_for(tool_id: str) -> asyncio.Lock:
    lock = _LOCKS.get(tool_id)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[tool_id] = lock
    return lock


class ReferenceCheckRequest(BaseModel):
    fixtures: list[str] | None = None
    tags: list[str] | None = None
    update_expected: bool = False
    yes: bool = False


def _resolve_tool(tool_id: str, settings: Settings):
    discovered = {t.tool_id: t for t in discover_tools(settings.tools_dir)}
    folder_index = {tool.path.name: tool for tool in discovered.values()}
    tool = discovered.get(tool_id) or folder_index.get(tool_id)
    if tool is not None:
        return tool
    candidate = settings.tools_dir / tool_id
    if not candidate.is_dir():
        raise HTTPException(status_code=404, detail=f"tool {tool_id!r} not found")
    # Build a minimal stand-in: caller still gets a valid path.
    return None


@router.get("/tools/{tool_id}/reference-fixtures")
async def get_reference_fixtures(
    tool_id: str, settings: SettingsDep,
) -> dict[str, Any]:
    """List fixture filenames + tags so the skill UI can offer a picker."""

    tool = _resolve_tool(tool_id, settings)
    tool_path = tool.path if tool is not None else (settings.tools_dir / tool_id)
    fixtures = list_reference_fixtures(tool_path / "reference")
    return {
        "tool_id": tool_id,
        "tool_path": str(tool_path),
        "has_reference_folder": (tool_path / "reference").is_dir(),
        "fixtures": fixtures,
        "count": len(fixtures),
    }


@router.post("/tools/{tool_id}/reference-check")
async def post_reference_check(
    tool_id: str,
    settings: SettingsDep,
    body: ReferenceCheckRequest | None = None,
) -> dict[str, Any]:
    """Run check #12 against ``tool_id`` and return the report.

    Mirrors the JSON shape of ``GET /api/tools/{id}/validate`` so the
    skill/UI can reuse rendering code. Returns 409 if a check for the
    same tool is already in flight.
    """

    request_body = body or ReferenceCheckRequest()
    tool = _resolve_tool(tool_id, settings)
    tool_path = tool.path if tool is not None else (settings.tools_dir / tool_id)

    lock = _lock_for(tool_id)
    if lock.locked():
        raise HTTPException(
            status_code=409,
            detail=f"reference-check for {tool_id!r} already in flight",
        )

    async with lock:
        try:
            if request_body.update_expected:
                if not request_body.yes:
                    update_payload = await update_reference_fixtures(
                        tool_path,
                        fixture_filter=request_body.fixtures,
                        dry_run=True,
                    )
                    return {
                        "tool_id": tool_id,
                        "tool_path": str(tool_path),
                        "mode": "update-fixtures-dry-run",
                        "result": update_payload,
                    }
                update_payload = await update_reference_fixtures(
                    tool_path,
                    fixture_filter=request_body.fixtures,
                    dry_run=False,
                )
                return {
                    "tool_id": tool_id,
                    "tool_path": str(tool_path),
                    "mode": "update-fixtures",
                    "result": update_payload,
                }

            report = await validate_tool(
                tool_path,
                save_to_db=True,
                reference_only=True,
                fixture_filter=request_body.fixtures,
                tag_filter=request_body.tags,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    payload = json.loads(report.model_dump_json())
    ref_check = next(
        (c for c in payload.get("checks", [])
         if c.get("name") == "reference_fixtures_match"),
        None,
    )
    return {
        "tool_id": tool_id,
        "tool_path": str(tool_path),
        "ran_at": payload.get("timestamp"),
        "overall": payload.get("overall"),
        "check": ref_check,
        "report": payload,
    }
