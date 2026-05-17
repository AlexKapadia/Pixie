"""Additional proxy tests using a mock launcher + httpx mocks."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from pixie import db
from pixie.artefacts import ArtefactRegistry
from pixie.config import get_settings
from pixie.discovery import DiscoveredTool, ToolSchema
from pixie.launcher import Launcher, LauncherError, RunningTool, StderrRing
from pixie.proxy import cancel_tool, cancel_tool_hard, run_tool, stream_tool


def _schema(tool_id: str = "fixture") -> ToolSchema:
    return ToolSchema.model_validate({
        "id": tool_id, "name": tool_id, "max_runtime_seconds": 10,
        "inputs": [{"key": "x", "type": "number", "label": "X"}],
        "outputs": [{"key": "y", "type": "number", "label": "Y"}],
    })


def _tool(tool_id: str = "fixture") -> DiscoveredTool:
    return DiscoveredTool(
        tool_id=tool_id, path=Path("/no"), schema=_schema(tool_id),
        parse_error=None, has_venv=False,
    )


class _StubProcess:
    def __init__(self, returncode=None, pid=-1) -> None:
        self.returncode = returncode
        self.pid = pid


@pytest.fixture
def init_db(tmp_pixie_root: Path, monkeypatch) -> Path:
    monkeypatch.setenv("PIXIE_ARTEFACTS_ROOT", str(tmp_pixie_root / "artefacts"))
    get_settings.cache_clear()
    settings = get_settings()
    db.init_db(settings.db_path)
    return settings.db_path


@pytest.mark.asyncio
async def test_run_tool_rejects_schemaless(init_db: Path) -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        tool = DiscoveredTool(
            tool_id="x", path=Path("/no"), schema=None,
            parse_error="bad", has_venv=False,
        )
        with pytest.raises(LauncherError):
            await run_tool(launcher, tool, {"x": 1}, "run-1")


@pytest.mark.asyncio
async def test_stream_tool_rejects_schemaless(init_db: Path) -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        tool = DiscoveredTool(
            tool_id="x", path=Path("/no"), schema=None,
            parse_error=None, has_venv=False,
        )
        with pytest.raises(LauncherError):
            gen = stream_tool(launcher, tool, {"x": 1}, "run-1")
            async for _ in gen:
                pass


@pytest.mark.asyncio
async def test_cancel_tool_unknown_is_noop(init_db: Path) -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        tool = _tool()
        await cancel_tool(launcher, tool, "run-1")  # no-op


@pytest.mark.asyncio
async def test_cancel_tool_handles_http_error(init_db: Path, monkeypatch) -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        tool = _tool()
        proc = _StubProcess(returncode=None)
        running = RunningTool(
            tool_id=tool.tool_id, process=proc, port=1, started_at=0.0, last_used=0.0,
        )
        launcher.processes[tool.tool_id] = running

        async def boom(*a, **kw):
            raise httpx.ConnectError("nope")

        monkeypatch.setattr(client, "post", boom)
        # Should log and swallow
        await cancel_tool(launcher, tool, "run-1")


@pytest.mark.asyncio
async def test_cancel_tool_hard_returns_false_when_not_in_flight(
    init_db: Path, monkeypatch,
) -> None:
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        launcher = Launcher(settings, client)
        tool = _tool()
        proc = _StubProcess(returncode=None)
        running = RunningTool(
            tool_id=tool.tool_id, process=proc, port=1, started_at=0.0, last_used=0.0,
        )
        launcher.processes[tool.tool_id] = running

        async def stub_post(*a, **kw):
            class R:
                def raise_for_status(self): return None
            return R()

        monkeypatch.setattr(client, "post", stub_post)
        # Not in flight, so soft cancel succeeds without hard kill
        out = await cancel_tool_hard(launcher, tool, "run-x", soft_grace=0.1)
        assert out is False
