"""Scale-feature performance budgets.

Two budgets so far:
* discover_tools_parallel completes a 50-tool tree in under 2 seconds.
* discover_tools_parallel completes a 100-tool tree in under 3 seconds.

We generate synthetic tool folders (tool.json + main.py stub) in a
temp directory. The stubs deliberately don't ``uv sync`` — discovery
just parses the schema and stats the disk, so missing venvs are fine.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Iterator

import pytest

from pixie.discovery import discover_tools_parallel


def _make_synthetic_tool(folder: Path, tool_id: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "tool.json").write_text(
        json.dumps({
            "id": tool_id,
            "name": tool_id.replace("-", " ").title(),
            "description": "Synthetic perf-test tool.",
            "category": "perf/scale",
            "inputs": [
                {
                    "key": "x",
                    "type": "number",
                    "label": "X",
                    "default": 1,
                }
            ],
            "outputs": [
                {
                    "key": "y",
                    "type": "number",
                    "label": "Y",
                }
            ],
        }),
        encoding="utf-8",
    )
    (folder / "main.py").write_text(
        "# Synthetic tool — perf test only.\n", encoding="utf-8"
    )
    (folder / "pyproject.toml").write_text(
        "[project]\nname='synth'\nversion='0.0.1'\n", encoding="utf-8"
    )


@pytest.fixture
def synth_tools_50(tmp_path: Path) -> Iterator[Path]:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    for i in range(50):
        _make_synthetic_tool(tools_dir / f"_synth_{i:03d}", f"synth-{i:03d}")
    yield tools_dir


@pytest.fixture
def synth_tools_100(tmp_path: Path) -> Iterator[Path]:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    for i in range(100):
        _make_synthetic_tool(tools_dir / f"_synth_{i:03d}", f"synth-{i:03d}")
    yield tools_dir


def test_discover_tools_parallel_50_under_2s(synth_tools_50: Path) -> None:
    """N=50 parallel discovery completes within budget."""

    async def run() -> tuple[float, int]:
        start = time.perf_counter()
        result = await discover_tools_parallel(synth_tools_50, concurrency=8)
        return time.perf_counter() - start, len(result)

    elapsed, count = asyncio.run(run())
    assert count == 50, f"expected 50 tools, got {count}"
    assert elapsed < 2.0, (
        f"discover_tools_parallel(50) took {elapsed:.3f}s, budget 2.0s"
    )


def test_discover_tools_parallel_100_under_3s(synth_tools_100: Path) -> None:
    """N=100 parallel discovery completes within budget."""

    async def run() -> tuple[float, int]:
        start = time.perf_counter()
        result = await discover_tools_parallel(synth_tools_100, concurrency=8)
        return time.perf_counter() - start, len(result)

    elapsed, count = asyncio.run(run())
    assert count == 100, f"expected 100 tools, got {count}"
    assert elapsed < 3.0, (
        f"discover_tools_parallel(100) took {elapsed:.3f}s, budget 3.0s"
    )
