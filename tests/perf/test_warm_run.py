"""Warm-path /run round-trip budget (100 ms on CI, 50 ms on user laptops).

After a one-time spawn we hit ``/run`` on the example-compound-interest
tool 50 times back to back. The median is the warm-path budget; the
launcher's idle sweeper is left alone (60 s warm_keep_seconds in the
tool.json comfortably covers the test window).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _has_example_venv() -> bool:
    venv = REPO_ROOT / "tools" / "example-compound-interest" / ".venv"
    if sys.platform == "win32":
        return (venv / "Scripts" / "python.exe").exists()
    return (venv / "bin" / "python").exists()


def test_warm_run_budget(benchmark, assert_within_budget) -> None:
    """Time a single warm-path /run round-trip; pytest-benchmark medians it."""

    if not _has_example_venv():
        pytest.skip("example tool venv missing")

    from pixie.config import get_settings
    from pixie.discovery import discover_tools
    from pixie.launcher import Launcher

    settings = get_settings()
    tools = [
        t for t in discover_tools(settings.tools_dir)
        if t.tool_id == "compound-interest"
    ]
    if not tools:
        pytest.skip("compound-interest tool not discovered")
    tool = tools[0]

    # Build a single launcher + client and keep them alive across rounds.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = httpx.AsyncClient(timeout=10.0)
    launcher = Launcher(settings, client)

    try:
        port = loop.run_until_complete(launcher.ensure_running(tool))
        # Synthesise the smallest sample payload from the schema defaults.
        payload = {
            inp.key: inp.default
            for inp in tool.schema.inputs
            if inp.default is not None
        }

        def _one_run() -> None:
            async def _go() -> None:
                resp = await client.post(
                    f"http://127.0.0.1:{port}/run", json=payload
                )
                resp.raise_for_status()

            loop.run_until_complete(_go())

        # Warm the route once outside the benchmark so the first-hit
        # cost (route binding, asyncio task setup) does not pollute.
        _one_run()
        benchmark.pedantic(_one_run, iterations=1, rounds=50, warmup_rounds=2)
        assert_within_budget(benchmark, "warm_run_roundtrip")
    finally:
        try:
            loop.run_until_complete(launcher.stop_all())
        finally:
            loop.run_until_complete(client.aclose())
            loop.close()
