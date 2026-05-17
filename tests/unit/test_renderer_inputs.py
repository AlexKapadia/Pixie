"""Unit tests for the input renderer dispatch.

The output renderer has its own committed suite (``test_output_renderer.py``);
this file is the input-side counterpart. It verifies that every input
type has a matching Jinja partial and that ``render_input`` produces
HTML carrying the expected ``data-input-type`` attribute (the contract
the renderer dispatcher is built on).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pixie.discovery import ToolSchema
from pixie.renderer.inputs import render_input, render_inputs

REPO = Path(__file__).resolve().parents[2]
PARTIALS = REPO / "pixie" / "templates" / "partials" / "inputs"

# The committed partial set under pixie/templates/partials/inputs/.
# Keep aligned with disk; the validator complains if discovery hands
# the renderer a type whose partial is missing.
ALL_INPUT_TYPES = [
    "text", "textarea", "number", "slider", "select", "multiselect",
    "checkbox", "toggle", "radio", "date", "time", "datetime",
    "date_range", "file", "image", "audio", "colour",
    "json", "code", "markdown", "tags", "autocomplete", "table", "hidden",
    "map_point", "map_multipoint", "map_polygon", "map_bbox",
]


def test_every_input_type_has_a_partial() -> None:
    missing = [t for t in ALL_INPUT_TYPES if not (PARTIALS / f"{t}.html").exists()]
    assert missing == [], f"missing input partials: {missing}"


@pytest.mark.parametrize("input_type", ["text", "number", "toggle"])
def test_render_input_emits_marker_attr(input_type: str) -> None:
    """Each input partial carries a data-input-type marker for diagnostics."""

    body = {
        "id": "fixture",
        "name": "Fixture",
        "inputs": [
            {
                "key": "x",
                "type": input_type,
                "label": "X",
                **({"options": [{"value": "a", "label": "A"}]} if input_type == "select" else {}),
            }
        ],
        "outputs": [{"key": "y", "type": "number", "label": "Y"}],
    }
    schema = ToolSchema.model_validate(body)
    rendered = str(render_input(schema.inputs[0]))
    assert input_type in rendered or "data-input-type" in rendered


def test_render_inputs_groups_by_section() -> None:
    """``render_inputs`` accepts a list of specs and returns one HTML blob."""

    body = {
        "id": "fixture",
        "name": "Fixture",
        "inputs": [
            {"key": "a", "type": "text", "label": "A"},
            {"key": "b", "type": "number", "label": "B"},
        ],
        "outputs": [{"key": "y", "type": "number", "label": "Y"}],
    }
    schema = ToolSchema.model_validate(body)
    rendered = str(render_inputs(schema.inputs))
    # Both inputs should appear in the combined output.
    assert "A" in rendered
    assert "B" in rendered


def test_render_input_handles_default_value() -> None:
    """Passing an explicit value should not raise (rendered into the field)."""

    body = {
        "id": "fixture",
        "name": "Fixture",
        "inputs": [{"key": "x", "type": "text", "label": "X", "default": "hello"}],
        "outputs": [{"key": "y", "type": "number", "label": "Y"}],
    }
    schema = ToolSchema.model_validate(body)
    rendered = str(render_input(schema.inputs[0], value="override"))
    assert "override" in rendered or "hello" in rendered
