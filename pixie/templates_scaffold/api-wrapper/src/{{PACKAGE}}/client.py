"""HTTP client for {{TOOL_NAME}} with retry-with-exponential-backoff.

Uses ``httpx.AsyncClient`` so the FastAPI app can stay async.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("{{PACKAGE}}.client")

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=2.0)
MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 0.5


class UpstreamError(RuntimeError):
    """Raised when every retry fails."""


@dataclass(frozen=True)
class UpstreamReply:
    status_code: int
    body: dict[str, Any]
    attempts: int


async def call_upstream(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str | None,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
) -> UpstreamReply:
    """POST to ``url`` with retry-with-backoff. Raises on terminal failure."""

    headers = {"User-Agent": "{{TOOL_ID}}/0.1.0", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code >= 500 and attempt < MAX_ATTEMPTS:
                    raise UpstreamError(f"server returned {response.status_code}")
                try:
                    body = response.json()
                except ValueError:
                    body = {"raw": response.text[:2000]}
                return UpstreamReply(
                    status_code=response.status_code,
                    body=body,
                    attempts=attempt,
                )
            except (UpstreamError, httpx.HTTPError) as exc:
                last_exc = exc
                if attempt >= MAX_ATTEMPTS:
                    break
                delay = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "upstream attempt %d/%d failed: %s; retrying in %.2fs",
                    attempt, MAX_ATTEMPTS, exc, delay,
                )
                await asyncio.sleep(delay)

    raise UpstreamError(f"all {MAX_ATTEMPTS} attempts failed: {last_exc}")
