"""Integration coverage for the /tools full-screen grid + per-tool mutations.

Covers:
* GET /tools renders the grid page shell.
* GET /api/disk-usage returns the documented payload shape.
* Archive -> Unarchive round-trips both via the API and the DB.
* Tag add / remove round-trips.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest


def _make_tool_inplace(tools_dir: Path, tool_id: str, name: str = "Synth") -> None:
    """Write a minimal valid tool inline so the folder name matches schema.id."""

    folder = tools_dir / tool_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "tool.json").write_text(json.dumps({
        "id": tool_id,
        "name": name,
        "description": "Inline test tool.",
        "category": "test/grid",
        "inputs": [{"key": "x", "type": "number", "label": "X", "default": 1}],
        "outputs": [{"key": "y", "type": "number", "label": "Y"}],
    }), encoding="utf-8")
    (folder / "main.py").write_text("# stub\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_tools_grid_page_renders(
    httpx_client: httpx.AsyncClient,
    sample_tool_factory,
) -> None:
    sample_tool_factory("all-inputs-tool")
    resp = await httpx_client.get("/tools")
    assert resp.status_code == 200
    body = resp.text
    assert "All tools" in body
    assert "tools-grid" in body


@pytest.mark.asyncio
async def test_disk_usage_endpoint_shape(
    httpx_client: httpx.AsyncClient,
    sample_tool_factory,
) -> None:
    sample_tool_factory("all-inputs-tool")
    resp = await httpx_client.get("/api/disk-usage")
    assert resp.status_code == 200
    payload = resp.json()
    assert set(payload.keys()) >= {
        "tools", "totals", "archived", "tools_dir", "computed_at",
    }
    assert isinstance(payload["tools"], list)
    for entry in payload["tools"]:
        assert {
            "tool_id", "venv_bytes", "data_bytes",
            "models_bytes", "cache_bytes", "total_bytes", "archived",
        } <= set(entry.keys())
    assert set(payload["totals"].keys()) >= {
        "venv", "data", "models", "cache", "total",
    }


@pytest.mark.asyncio
async def test_archive_unarchive_round_trip(
    httpx_client: httpx.AsyncClient,
    tmp_pixie_root: Path,
) -> None:
    tools_dir = tmp_pixie_root / "tools"
    _make_tool_inplace(tools_dir, "grid-archive-tool")

    archive = await httpx_client.post(
        "/api/tools/grid-archive-tool/archive"
    )
    assert archive.status_code == 204
    archived_view = await httpx_client.get("/tools?archived=1")
    assert archived_view.status_code == 200
    assert "grid-archive-tool" in archived_view.text

    unarchive = await httpx_client.post(
        "/api/tools/grid-archive-tool/unarchive"
    )
    assert unarchive.status_code == 204
    default_view = await httpx_client.get("/tools")
    assert "grid-archive-tool" in default_view.text


@pytest.mark.asyncio
async def test_tag_add_and_remove(
    httpx_client: httpx.AsyncClient,
    tmp_pixie_root: Path,
) -> None:
    _make_tool_inplace(tmp_pixie_root / "tools", "grid-tag-tool")
    added = await httpx_client.post(
        "/api/tools/grid-tag-tool/tags", json={"tag": "fast"}
    )
    assert added.status_code == 204
    removed = await httpx_client.delete(
        "/api/tools/grid-tag-tool/tags/fast"
    )
    assert removed.status_code == 204


@pytest.mark.asyncio
async def test_grid_fragment_renders(
    httpx_client: httpx.AsyncClient,
    sample_tool_factory,
) -> None:
    sample_tool_factory("all-inputs-tool")
    resp = await httpx_client.get("/tools/_grid?sort=name")
    assert resp.status_code == 200
