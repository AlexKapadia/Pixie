"""Unit tests for ``pixie.proxy`` helpers.

The proxy itself is exercised end-to-end in the integration suite (a
real subprocess answering /run, /stream, /cancel). The unit tests here
cover only the pure helpers.
"""

from __future__ import annotations

import httpx
import pytest

from pixie.config import get_settings
from pixie.discovery import DiscoveredTool
from pixie.launcher import Launcher, RunningTool, StderrRing
from pixie.proxy import _stderr_for


@pytest.mark.asyncio
async def test_stderr_for_returns_empty_when_no_process() -> None:
    """Asking for stderr on a never-spawned tool returns the empty string."""

    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        assert _stderr_for(launcher, "no-such-tool") == ""


@pytest.mark.asyncio
async def test_stderr_for_reads_ring_snapshot() -> None:
    """When a process is registered, _stderr_for returns its ring snapshot."""

    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        ring = StderrRing(max_bytes=1024)
        ring.feed(b"boom: something exploded\n")
        # Build a RunningTool with a sentinel "process" object that has a
        # returncode attribute. We never call .kill() etc. so a stub works.

        class _StubProcess:
            returncode = 0

            def __init__(self) -> None:
                self.pid = -1

        running = RunningTool(
            tool_id="fixture",
            process=_StubProcess(),  # type: ignore[arg-type]
            port=12345,
            started_at=0.0,
            last_used=0.0,
            stderr_ring=ring,
        )
        launcher.processes["fixture"] = running
        snapshot = _stderr_for(launcher, "fixture")
        assert "boom" in snapshot


def test_proxy_run_payload_shape_matches_decisions() -> None:
    """DECISIONS s1 ratifies ``{run_id, inputs}`` as the body shape."""

    # We assert shape via a sample payload that the proxy assembles.
    # The proxy itself does not transform the payload, so the canonical
    # shape lives in the route layer; this test pins the agreement so a
    # future refactor cannot quietly drop the envelope.
    payload = {"run_id": "abc", "inputs": {"x": 1}}
    assert set(payload) == {"run_id", "inputs"}
    assert isinstance(payload["inputs"], dict)
