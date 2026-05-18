"""Sidebar render budget (100 ms p95 on user laptops, 200 ms CI).

Measures ``discover_tools`` over the real ``tools/`` directory.
"""

from __future__ import annotations

from pathlib import Path

from pixie.discovery import discover_tools

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_sidebar_discovery_budget(benchmark, assert_within_budget) -> None:
    """The filesystem scan + JSON parse must fit the sidebar budget."""

    benchmark(lambda: discover_tools(REPO_ROOT / "tools"))
    assert_within_budget(benchmark, "sidebar_render")
