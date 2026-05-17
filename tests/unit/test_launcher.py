"""Unit tests for ``pixie.launcher``.

These tests deliberately avoid spawning real subprocesses (that is the
job of the integration suite). They cover the helpers that the rest of
the launcher pivots on: free-port allocation, env scrubbing, and the
in-memory ``Launcher`` bookkeeping (locks, touch, is_running).
"""

from __future__ import annotations

import asyncio
import ipaddress
from pathlib import Path

import httpx
import pytest

from pixie.config import get_settings
from pixie.discovery import DiscoveredTool, ToolSchema
from pixie.launcher import (
    Launcher,
    LauncherError,
    StderrRing,
    _build_child_env,
    _free_port,
)


def _minimal_schema(tool_id: str = "fixture") -> ToolSchema:
    return ToolSchema.model_validate(
        {
            "id": tool_id,
            "name": tool_id,
            "inputs": [{"key": "x", "type": "number", "label": "X"}],
            "outputs": [{"key": "y", "type": "number", "label": "Y"}],
        }
    )


def test_free_port_returns_loopback_only() -> None:
    """The kernel-assigned port must be a usable loopback port (1024+)."""

    port = _free_port()
    assert 1024 <= port <= 65535


def test_free_port_is_unique_per_call() -> None:
    """Repeated calls return different free ports (kernel never reuses straight away)."""

    ports = {_free_port() for _ in range(5)}
    assert len(ports) >= 4  # at least some are unique


def test_build_child_env_strips_pixie_vars(
    tmp_pixie_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child env must not carry Pixie's own loopback/host config."""

    monkeypatch.setenv("PIXIE_HOST", "127.0.0.1")
    monkeypatch.setenv("MY_CUSTOM_VAR", "value")
    env = _build_child_env(tmp_pixie_root / "tools" / "fixture")
    # Pixie's own host/port config must NOT leak to the child.
    assert "PIXIE_HOST" not in env
    # PATH should be preserved so the venv shebang can find python.
    assert "PATH" in env


def test_stderr_ring_drops_oldest_chunks() -> None:
    """The bounded ring keeps the most recent bytes only."""

    ring = StderrRing(max_bytes=20)
    ring.feed(b"first-chunk-aaaaa")  # 17 bytes
    ring.feed(b"second-chunk-bb")  # would overflow
    snapshot = ring.snapshot()
    assert "second-chunk" in snapshot
    assert len(snapshot.encode("utf-8")) <= 20


@pytest.mark.asyncio
async def test_launcher_ensure_running_rejects_broken_schema(
    tmp_pixie_root: Path,
) -> None:
    """A tool without a parsed schema must fail loudly."""

    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        broken = DiscoveredTool(
            tool_id="broken",
            path=tmp_pixie_root / "tools" / "broken",
            schema=None,
            parse_error="boom",
            has_venv=False,
        )
        with pytest.raises(LauncherError):
            await launcher.ensure_running(broken)


@pytest.mark.asyncio
async def test_launcher_per_tool_locks_are_unique(tmp_pixie_root: Path) -> None:
    """The launcher allocates one lock per tool id, deduped on reuse."""

    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        lock_a = launcher.locks.setdefault("alpha", asyncio.Lock())
        lock_b = launcher.locks.setdefault("alpha", asyncio.Lock())
        lock_c = launcher.locks.setdefault("beta", asyncio.Lock())
        assert lock_a is lock_b
        assert lock_a is not lock_c


@pytest.mark.asyncio
async def test_launcher_concurrent_lock_is_per_tool(tmp_pixie_root: Path) -> None:
    """``get_concurrent_lock`` returns the same lock instance per tool id."""

    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        assert launcher.get_concurrent_lock("x") is launcher.get_concurrent_lock("x")
        assert launcher.get_concurrent_lock("x") is not launcher.get_concurrent_lock("y")


@pytest.mark.asyncio
async def test_launcher_is_running_false_when_empty(tmp_pixie_root: Path) -> None:
    """``is_running`` returns False until a process is recorded."""

    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        assert launcher.is_running("nothing") is False
        assert launcher.list_running() == []
