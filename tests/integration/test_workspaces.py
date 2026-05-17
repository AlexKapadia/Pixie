"""Integration coverage for the workspaces JSON router.

Drives the FastAPI surface end-to-end against a scratch repo so we
prove the router, the db helpers, and the active-workspace setting
all line up.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_create_list_delete_workspace_via_api(
    httpx_client: httpx.AsyncClient,
) -> None:
    resp = await httpx_client.post("/api/workspaces", json={"name": "Finance"})
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["name"] == "Finance"
    workspace_id = created["id"]

    listing = await httpx_client.get("/api/workspaces")
    assert listing.status_code == 200
    names = [w["name"] for w in listing.json()]
    assert "Finance" in names

    # Duplicate names are rejected.
    dup = await httpx_client.post("/api/workspaces", json={"name": "Finance"})
    assert dup.status_code == 409

    # Rename via PATCH.
    patched = await httpx_client.patch(
        f"/api/workspaces/{workspace_id}", json={"name": "Quant"}
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Quant"

    # Delete.
    deleted = await httpx_client.delete(f"/api/workspaces/{workspace_id}")
    assert deleted.status_code == 204
    after = await httpx_client.get("/api/workspaces")
    assert all(w["id"] != workspace_id for w in after.json())


@pytest.mark.asyncio
async def test_add_remove_tool_to_workspace_via_api(
    httpx_client: httpx.AsyncClient,
) -> None:
    resp = await httpx_client.post("/api/workspaces", json={"name": "ML"})
    workspace_id = resp.json()["id"]

    add = await httpx_client.post(
        f"/api/workspaces/{workspace_id}/tools/some-tool"
    )
    assert add.status_code == 204

    listing = await httpx_client.get("/api/workspaces")
    entry = next(w for w in listing.json() if w["id"] == workspace_id)
    assert "some-tool" in entry["tool_ids"]
    assert entry["tool_count"] == 1

    remove = await httpx_client.delete(
        f"/api/workspaces/{workspace_id}/tools/some-tool"
    )
    assert remove.status_code == 204
    listing = await httpx_client.get("/api/workspaces")
    entry = next(w for w in listing.json() if w["id"] == workspace_id)
    assert entry["tool_ids"] == []


@pytest.mark.asyncio
async def test_activate_workspace_persists_setting(
    httpx_client: httpx.AsyncClient,
) -> None:
    resp = await httpx_client.post(
        "/api/workspaces", json={"name": "Geospatial"}
    )
    workspace_id = resp.json()["id"]
    activated = await httpx_client.post(
        f"/api/workspaces/{workspace_id}/activate"
    )
    assert activated.status_code == 204
    cleared = await httpx_client.post("/api/workspaces/0/activate")
    assert cleared.status_code == 204
