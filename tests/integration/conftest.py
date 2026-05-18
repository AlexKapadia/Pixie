"""Integration-suite fixtures.

Integration tests stand up a live Pixie server (``pixie_server`` from
the top-level conftest) and exercise the real route layer. They may
spawn real tool subprocesses via the example tool's venv but never via
``uv sync`` (per RULES.md s3).

Shared helpers below let the integration tests reuse the canonical
example tool without copying its venv every test.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_TOOL = REPO_ROOT / "tools" / "example-compound-interest"


def _example_tool_has_venv() -> bool:
    if sys.platform == "win32":
        return (EXAMPLE_TOOL / ".venv" / "Scripts" / "python.exe").exists()
    return (EXAMPLE_TOOL / ".venv" / "bin" / "python").exists()


@pytest.fixture
def staged_example_tool(tmp_pixie_root: Path) -> Path:
    """Stage the example tool into ``tmp_pixie_root/tools/``.

    Uses the real ``.venv`` because integration tests need a working
    Python interpreter. Skips the test if the venv is missing - run
    ``cd tools/example-compound-interest && uv sync`` first.
    """

    if not _example_tool_has_venv():
        pytest.skip(
            "example-compound-interest/.venv missing - "
            "run `cd tools/example-compound-interest && uv sync` first"
        )
    dest = tmp_pixie_root / "tools" / "example-compound-interest"
    shutil.copytree(
        EXAMPLE_TOOL,
        dest,
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return dest
