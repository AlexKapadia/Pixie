"""Additional launcher coverage targeting non-spawn helpers."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
import pytest

from pixie.config import get_settings
from pixie.discovery import DiscoveredTool, ToolSchema
from pixie.launcher import (
    Launcher,
    LauncherError,
    RunningTool,
    StderrRing,
    _popen_kwargs,
    _send_graceful,
    _send_hard,
    _venv_python,
)


def _minimal_schema(tool_id: str = "fixture", concurrent: bool = True) -> ToolSchema:
    return ToolSchema.model_validate({
        "id": tool_id, "name": tool_id, "concurrent": concurrent,
        "inputs": [{"key": "x", "type": "number", "label": "X"}],
        "outputs": [{"key": "y", "type": "number", "label": "Y"}],
    })


class _StubProcess:
    def __init__(self, returncode=None, pid=-1) -> None:
        self.returncode = returncode
        self.pid = pid


# --- venv path -----------------------------------------------------------


def test_venv_python_returns_platform_path(tmp_pixie_root: Path) -> None:
    p = _venv_python(tmp_pixie_root)
    assert "python" in p.name.lower()


# --- popen kwargs --------------------------------------------------------


def test_popen_kwargs_returns_dict() -> None:
    out = _popen_kwargs(_minimal_schema())
    assert isinstance(out, dict)


# --- send signals (stub process) ----------------------------------------


def test_send_graceful_with_no_returncode() -> None:
    proc = type("P", (), {"returncode": None, "send_signal": lambda self, sig: None,
                            "pid": -1, "terminate": lambda self: None})()
    _send_graceful(proc)  # should not raise


def test_send_hard_with_dead_process() -> None:
    proc = type("P", (), {"returncode": 0, "kill": lambda self: None, "pid": -1})()
    _send_hard(proc)  # already dead — no-op path


def test_send_hard_with_alive_process() -> None:
    killed = []
    proc = type("P", (), {
        "returncode": None,
        "kill": lambda self: killed.append("k"),
        "pid": -1,
    })()
    _send_hard(proc)
    assert killed == ["k"]


# --- stderr ring ---------------------------------------------------------


def test_stderr_ring_snapshot_empty() -> None:
    ring = StderrRing(max_bytes=100)
    assert ring.snapshot() == ""


def test_stderr_ring_feed_within_capacity() -> None:
    ring = StderrRing(max_bytes=100)
    ring.feed(b"hello\n")
    assert "hello" in ring.snapshot()


# --- Launcher bookkeeping ----------------------------------------------


@pytest.mark.asyncio
async def test_set_pinned_warm_idempotent() -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        launcher.set_pinned_warm("a", True)
        launcher.set_pinned_warm("a", True)
        assert launcher.pinned_warm == {"a"}
        launcher.set_pinned_warm("a", False)
        assert launcher.pinned_warm == set()


@pytest.mark.asyncio
async def test_touch_noop_for_unknown_tool() -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        launcher.touch("no-such-tool")  # should not raise


@pytest.mark.asyncio
async def test_is_running_false_when_no_process() -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        assert launcher.is_running("a") is False


@pytest.mark.asyncio
async def test_list_running_filters_dead() -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        alive = _StubProcess(returncode=None)
        dead = _StubProcess(returncode=0)
        launcher.processes["alive"] = RunningTool(
            tool_id="alive", process=alive, port=1, started_at=0.0, last_used=0.0,
        )
        launcher.processes["dead"] = RunningTool(
            tool_id="dead", process=dead, port=2, started_at=0.0, last_used=0.0,
        )
        out = launcher.list_running()
        assert len(out) == 1
        assert out[0].tool_id == "alive"


@pytest.mark.asyncio
async def test_get_concurrent_lock_returns_same_lock() -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        l1 = launcher.get_concurrent_lock("a")
        l2 = launcher.get_concurrent_lock("a")
        assert l1 is l2


@pytest.mark.asyncio
async def test_ensure_running_rejects_schemaless_tool() -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        tool = DiscoveredTool(tool_id="x", path=Path("/no"), schema=None, parse_error=None, has_venv=False)
        with pytest.raises(LauncherError):
            await launcher.ensure_running(tool)


@pytest.mark.asyncio
async def test_stop_unknown_tool_is_noop() -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        await launcher.stop("never-spawned")  # should not raise


@pytest.mark.asyncio
async def test_stop_all_with_no_processes() -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        await launcher.stop_all()


@pytest.mark.asyncio
async def test_prewarm_bails_for_schemaless_tool() -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        tool = DiscoveredTool(tool_id="x", path=Path("/no"), schema=None, parse_error=None, has_venv=False)
        launcher.prewarm(tool)  # silent no-op
        assert not launcher._prewarm_tasks


@pytest.mark.asyncio
async def test_prewarm_skips_when_already_running() -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        proc = _StubProcess(returncode=None)
        running = RunningTool(
            tool_id="x", process=proc, port=1, started_at=0.0, last_used=0.0,
        )
        launcher.processes["x"] = running
        schema = _minimal_schema("x")
        tool = DiscoveredTool(tool_id="x", path=Path("/no"), schema=schema, parse_error=None, has_venv=False)
        launcher.prewarm(tool)
        # touch was called; no new task created
        assert not launcher._prewarm_tasks
