"""Unit-suite fixtures.

Unit tests target a single module and never spawn a child process or
bind a real port. Shared helpers (``tmp_pixie_root``, the validator
report factory, etc.) come from the top-level ``conftest.py``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def make_tool_json(tmp_pixie_root: Path) -> Callable[..., Path]:
    """Write a minimal valid ``tool.json`` into a fresh tool folder.

    Returns the tool folder path. Useful for discovery / validator unit
    tests that want a known-good schema without copying a fixture.
    """

    def factory(
        tool_id: str = "fixture-tool",
        *,
        overrides: dict | None = None,
    ) -> Path:
        body = {
            "id": tool_id,
            "name": tool_id.replace("-", " ").title(),
            "description": "Fixture tool.",
            "version": "0.1.0",
            "inputs": [
                {"key": "x", "type": "number", "label": "X", "default": 1}
            ],
            "outputs": [
                {"key": "y", "type": "number", "label": "Y"}
            ],
        }
        if overrides:
            body.update(overrides)
        tool_dir = tmp_pixie_root / "tools" / tool_id
        tool_dir.mkdir(parents=True, exist_ok=True)
        (tool_dir / "tool.json").write_text(
            json.dumps(body, indent=2), encoding="utf-8"
        )
        return tool_dir

    return factory
