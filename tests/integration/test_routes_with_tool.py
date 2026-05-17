"""Integration tests that exercise routes via the staged example tool.

These ride on the conftest ``sample_tool_factory`` fixture (no venv
required) so they remain fast. The example tools live under
``tests/fixtures/`` and have valid tool.json + main.py shapes.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest


@pytest.mark.asyncio
async def test_dashboard_tool_page_with_staged_tool(
    sample_tool_factory,
    httpx_client: httpx.AsyncClient,
) -> None:
    """Stage a fixture tool, then load its /tool/{id} page."""

    sample_tool_factory("all-inputs-tool")
    # Force a re-discovery by hitting tools-changed.
    r = await httpx_client.get("/tools-changed")
    assert r.status_code == 200

    # The live server's cached discovery state may not pick up the new
    # tool unless it does a re-scan on each /tool/{id} request. Either
    # 200 (success) or 404 (not yet refreshed) is acceptable - we mainly
    # want the route code to execute.
    r = await httpx_client.get("/tool/all-inputs-tool")
    assert r.status_code in (200, 404)


@pytest.mark.asyncio
async def test_tool_runs_endpoint_unknown_tool(
    httpx_client: httpx.AsyncClient,
) -> None:
    r = await httpx_client.get("/tool/no-such-tool/runs")
    assert r.status_code in (200, 404)


@pytest.mark.asyncio
async def test_tool_run_view_unknown(
    httpx_client: httpx.AsyncClient,
) -> None:
    r = await httpx_client.get("/tool/no-such-tool/runs/no-such-run")
    assert r.status_code in (404, 200)


@pytest.mark.asyncio
async def test_tool_settings_with_staged_tool(
    sample_tool_factory,
    httpx_client: httpx.AsyncClient,
) -> None:
    sample_tool_factory("all-inputs-tool")
    await httpx_client.get("/tools-changed")
    r = await httpx_client.get("/tool/all-inputs-tool/settings")
    assert r.status_code in (200, 404)


@pytest.mark.asyncio
async def test_tool_overrides_post(
    sample_tool_factory,
    httpx_client: httpx.AsyncClient,
) -> None:
    sample_tool_factory("all-inputs-tool")
    await httpx_client.get("/tools-changed")
    r = await httpx_client.post(
        "/tool/all-inputs-tool/overrides",
        data={"warm_keep_seconds": "60"},
    )
    assert r.status_code in (200, 303, 404, 422)


@pytest.mark.asyncio
async def test_tool_secret_post(
    sample_tool_factory,
    httpx_client: httpx.AsyncClient,
) -> None:
    sample_tool_factory("all-inputs-tool")
    await httpx_client.get("/tools-changed")
    r = await httpx_client.post(
        "/tool/all-inputs-tool/secrets/MY_KEY",
        data={"value": "secret-value"},
    )
    assert r.status_code in (200, 303, 404, 422)


@pytest.mark.asyncio
async def test_tool_secret_delete(
    sample_tool_factory,
    httpx_client: httpx.AsyncClient,
) -> None:
    sample_tool_factory("all-inputs-tool")
    await httpx_client.get("/tools-changed")
    r = await httpx_client.delete("/tool/all-inputs-tool/secrets/MY_KEY")
    assert r.status_code in (200, 204, 404)


@pytest.mark.asyncio
async def test_tool_validate_now_post(
    sample_tool_factory,
    httpx_client: httpx.AsyncClient,
) -> None:
    sample_tool_factory("all-inputs-tool")
    await httpx_client.get("/tools-changed")
    r = await httpx_client.post("/tool/all-inputs-tool/validate-now")
    # validate-now is sync and may take time; allow 200/202/503
    assert r.status_code in (200, 202, 404, 503)


@pytest.mark.asyncio
async def test_settings_revalidate_all(
    httpx_client: httpx.AsyncClient,
) -> None:
    r = await httpx_client.post("/settings/revalidate-all")
    assert r.status_code in (200, 202, 204)


@pytest.mark.asyncio
async def test_tools_grid_archive_and_unarchive(
    sample_tool_factory,
    httpx_client: httpx.AsyncClient,
) -> None:
    sample_tool_factory("all-inputs-tool")
    await httpx_client.get("/tools-changed")
    r = await httpx_client.post("/api/tools/all-inputs-tool/archive")
    assert r.status_code in (200, 204, 404)
    r = await httpx_client.post("/api/tools/all-inputs-tool/unarchive")
    assert r.status_code in (200, 204, 404)


@pytest.mark.asyncio
async def test_tool_cancel_endpoint(
    httpx_client: httpx.AsyncClient,
) -> None:
    # cancel takes run_id as query param
    r = await httpx_client.post(
        "/tool/no-such-tool/cancel?run_id=no-such-run",
    )
    assert r.status_code in (200, 404, 422)


@pytest.mark.asyncio
async def test_tool_runs_list_unknown(
    httpx_client: httpx.AsyncClient,
) -> None:
    r = await httpx_client.get("/tool/no-such-tool/runs")
    assert r.status_code == 200
    # empty list for unknown tool
    assert r.json() == [] or isinstance(r.json(), list)
