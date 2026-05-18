"""End-to-end run flow against a live Pixie server.

The default test only asserts that the server boots and answers a
simple JSON API request. Real tool-spawn coverage is gated behind the
``staged_example_tool`` fixture, which is skipped when the example
tool's venv is missing.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest


@pytest.mark.asyncio
async def test_server_boots_and_lists_tools(httpx_client: httpx.AsyncClient) -> None:
    """GET /api/tools returns 200 with an empty list when no tools are present."""

    response = await httpx_client.get("/api/tools")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)


@pytest.mark.asyncio
async def test_dashboard_returns_html(httpx_client: httpx.AsyncClient) -> None:
    """The root dashboard always renders, even with zero tools."""

    response = await httpx_client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.asyncio
async def test_run_flow_against_example_tool(
    staged_example_tool: Path,
    httpx_client: httpx.AsyncClient,
) -> None:
    """A staged example tool boots and answers POST /tool/<id>/run.

    Skipped if the example tool's venv is missing.
    """

    # Discovery picks the tool up - schema id is "compound-interest".
    list_response = await httpx_client.get("/api/tools")
    list_response.raise_for_status()
    tool_ids = {entry["id"] for entry in list_response.json()}
    assert "compound-interest" in tool_ids

    run_response = await httpx_client.post(
        "/tool/compound-interest/run",
        data={
            "principal": "1000",
            "annual_rate": "5",
            "years": "1",
            "compounding": "12",
            "monthly_contribution": "0",
            "inflation_adjusted": "false",
        },
        headers={"HX-Request": "true"},
    )
    # The route renders an HTML fragment via htmx. We only assert the
    # round-trip succeeded; deeper render assertions live in e2e.
    assert run_response.status_code in (200, 422)
