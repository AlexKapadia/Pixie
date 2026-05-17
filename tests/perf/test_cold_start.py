"""Cold-spawn budget: first click on a dormant tool must spawn in
under 2500 ms on CI (1500 ms on user laptops). Spawns the example tool
via the launcher and asserts the benchmark median.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _has_example_venv() -> bool:
    import sys

    venv = REPO_ROOT / "tools" / "example-compound-interest" / ".venv"
    if sys.platform == "win32":
        return (venv / "Scripts" / "python.exe").exists()
    return (venv / "bin" / "python").exists()


def test_cold_spawn_budget(benchmark, assert_within_budget) -> None:
    """Spawn-then-stop a tool inside ``benchmark`` so the median is the
    cold-spawn cost (no warm-cache hit because we stop between rounds).
    """

    if not _has_example_venv():
        pytest.skip("example tool venv missing")

    from pixie.config import get_settings
    from pixie.discovery import discover_tools
    from pixie.launcher import Launcher

    settings = get_settings()
    tools = [t for t in discover_tools(settings.tools_dir) if t.tool_id == "compound-interest"]
    if not tools:
        pytest.skip("example tool not discovered in real tools/ dir")
    tool = tools[0]

    async def _once() -> None:
        async with httpx.AsyncClient() as client:
            launcher = Launcher(settings, client)
            try:
                await launcher.ensure_running(tool)
            finally:
                await launcher.stop_all()

    benchmark(lambda: asyncio.run(_once()))
    assert_within_budget(benchmark, "cold_spawn")
