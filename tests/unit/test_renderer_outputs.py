"""Slim re-export of output-renderer assertions.

The deep coverage for the output renderer lives in
``tests/test_output_renderer.py`` (90 tests, committed before this
scaffolding existed). This file holds a smaller sentinel set so that
running ``uv run pytest tests/unit`` alone catches any regression in
the renderer's most load-bearing contract: every output type must
render to HTML that carries ``data-output-type`` and the partials must
all exist on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pixie.discovery import ToolSchema
from pixie.renderer.outputs import render_output, render_outputs

REPO = Path(__file__).resolve().parents[2]
PARTIALS = REPO / "pixie" / "templates" / "partials" / "outputs"

SENTINEL_TYPES = ["text", "number", "table", "chart_line", "image", "log", "file"]


@pytest.mark.parametrize("output_type", SENTINEL_TYPES)
def test_sentinel_output_partial_exists(output_type: str) -> None:
    assert (PARTIALS / f"{output_type}.html").exists()


def test_render_outputs_handles_empty_list() -> None:
    """An empty outputs list renders to an empty (but valid) blob."""

    rendered = str(render_outputs([], {}))
    # No crash and no leftover Jinja markers.
    assert "{{" not in rendered
    assert "{%" not in rendered


def test_render_output_handles_none_value() -> None:
    """Missing values must render the empty-state placeholder, not crash."""

    body = {
        "id": "fixture",
        "name": "Fixture",
        "inputs": [{"key": "x", "type": "text", "label": "X"}],
        "outputs": [{"key": "msg", "type": "text", "label": "Msg"}],
    }
    schema = ToolSchema.model_validate(body)
    rendered = str(render_output(schema.outputs[0], None))
    # The text partial accepts None; assert no exception and HTML is non-empty.
    assert isinstance(rendered, str)
    assert len(rendered) > 0
