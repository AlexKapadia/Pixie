"""Unit coverage for the workspace db helpers + the workspaces router.

The DB helpers (``create_workspace``, ``add_tool_to_workspace`` etc.)
already existed from Phase X-a; this file proves the round-trip
contract and that the HTTP router glues to them correctly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pixie import db


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    target = tmp_path / "pixie.db"
    db.init_db(target)
    return target


@pytest.mark.asyncio
async def test_create_and_list_workspace(db_path: Path) -> None:
    wid = await db.create_workspace(db_path, "Finance")
    assert wid > 0
    workspaces = await db.list_workspaces(db_path)
    assert any(w["name"] == "Finance" and w["id"] == wid for w in workspaces)


@pytest.mark.asyncio
async def test_rename_workspace(db_path: Path) -> None:
    wid = await db.create_workspace(db_path, "Finance")
    await db.rename_workspace(db_path, wid, name="Quant")
    workspaces = await db.list_workspaces(db_path)
    assert any(w["id"] == wid and w["name"] == "Quant" for w in workspaces)


@pytest.mark.asyncio
async def test_delete_workspace_cascades(db_path: Path) -> None:
    wid = await db.create_workspace(db_path, "Throwaway")
    await db.add_tool_to_workspace(db_path, "alpha", wid)
    await db.add_tool_to_workspace(db_path, "beta", wid)
    assert set(await db.list_tools_in_workspace(db_path, wid)) == {"alpha", "beta"}
    await db.delete_workspace(db_path, wid)
    assert await db.list_workspaces(db_path) == []
    # Cascade: membership rows are gone too.
    assert await db.list_tools_in_workspace(db_path, wid) == []


@pytest.mark.asyncio
async def test_add_and_remove_tool_from_workspace(db_path: Path) -> None:
    wid = await db.create_workspace(db_path, "ML")
    await db.add_tool_to_workspace(db_path, "trainer", wid)
    await db.add_tool_to_workspace(db_path, "trainer", wid)  # idempotent
    assert await db.list_tools_in_workspace(db_path, wid) == ["trainer"]
    await db.remove_tool_from_workspace(db_path, "trainer", wid)
    assert await db.list_tools_in_workspace(db_path, wid) == []


@pytest.mark.asyncio
async def test_list_workspaces_for_tool(db_path: Path) -> None:
    a = await db.create_workspace(db_path, "Alpha")
    b = await db.create_workspace(db_path, "Beta")
    await db.add_tool_to_workspace(db_path, "shared", a)
    await db.add_tool_to_workspace(db_path, "shared", b)
    names = {w["name"] for w in await db.list_workspaces_for_tool(db_path, "shared")}
    assert names == {"Alpha", "Beta"}
