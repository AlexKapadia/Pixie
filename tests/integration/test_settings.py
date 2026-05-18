"""Settings route + persistence coverage."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_settings_page_renders(httpx_client: httpx.AsyncClient) -> None:
    """GET /settings returns a 200 HTML page."""

    response = await httpx_client.get("/settings")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
