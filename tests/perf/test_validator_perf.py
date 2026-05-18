"""Validator full-pass budget against the example tool (13s CI, 8s local).

The validator spawns the tool, runs 11 checks, and gracefully shuts it
down. We measure the synchronous wrapper since that's what the CLI
uses (``pixie validate <id>``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_TOOL = REPO_ROOT / "tools" / "example-compound-interest"


def _has_example_venv() -> bool:
    venv = EXAMPLE_TOOL / ".venv"
    if sys.platform == "win32":
        return (venv / "Scripts" / "python.exe").exists()
    return (venv / "bin" / "python").exists()


def test_validator_full_pass_budget(benchmark, assert_within_budget) -> None:
    """``validate_tool_sync`` against example tool must fit the budget."""

    if not _has_example_venv():
        pytest.skip("example tool venv missing")

    from pixie.validator import validate_tool_sync

    def _run() -> object:
        return validate_tool_sync(EXAMPLE_TOOL, save_to_db=False)

    # Single rep is enough — spawn dominates and is ~7s.
    benchmark.pedantic(_run, iterations=1, rounds=2, warmup_rounds=0)
    assert_within_budget(benchmark, "validator_full_pass")
