"""Unit tests for ``pixie.discovery``.

Covers schema parse success, parse-error capture, the new optional
fields ratified in ``DECISIONS.md``, and a parametrised sweep over a
sample of the input/output discriminated unions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pixie.discovery import ToolSchema, discover_tools, load_tool_schema

VALID_MINIMAL = {
    "id": "minimal",
    "name": "Minimal",
    "inputs": [{"key": "x", "type": "number", "label": "X"}],
    "outputs": [{"key": "y", "type": "number", "label": "Y"}],
}


def _write_tool(tool_path: Path, body: dict) -> None:
    tool_path.mkdir(parents=True, exist_ok=True)
    (tool_path / "tool.json").write_text(json.dumps(body), encoding="utf-8")


def test_load_tool_schema_parses_minimal_valid_tool(tmp_pixie_root: Path) -> None:
    tool_dir = tmp_pixie_root / "tools" / "minimal"
    _write_tool(tool_dir, VALID_MINIMAL)
    schema = load_tool_schema(tool_dir)
    assert schema.id == "minimal"
    assert schema.layout == "form"  # default
    assert schema.warm_keep_seconds == 300  # default


def test_load_tool_schema_rejects_broken_json(tmp_pixie_root: Path) -> None:
    tool_dir = tmp_pixie_root / "tools" / "broken"
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool.json").write_text("not json{", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_tool_schema(tool_dir)


def test_load_tool_schema_rejects_invalid_shape(tmp_pixie_root: Path) -> None:
    tool_dir = tmp_pixie_root / "tools" / "bad-shape"
    body = dict(VALID_MINIMAL)
    body["inputs"] = [{"key": "x", "type": "no-such-type", "label": "X"}]
    _write_tool(tool_dir, body)
    with pytest.raises(ValidationError):
        load_tool_schema(tool_dir)


def test_discover_tools_captures_parse_errors(tmp_pixie_root: Path) -> None:
    """Broken tools must appear in the discovery list with parse_error set."""

    good = tmp_pixie_root / "tools" / "good"
    bad = tmp_pixie_root / "tools" / "bad"
    _write_tool(good, VALID_MINIMAL)  # JSON id is "minimal"
    bad.mkdir()
    (bad / "tool.json").write_text("{garbage", encoding="utf-8")

    discovered = discover_tools(tmp_pixie_root / "tools")
    # The good tool gets its tool_id from schema.id ("minimal"); the bad
    # one falls back to the folder name because the schema never parsed.
    by_id = {d.tool_id: d for d in discovered}
    assert by_id["minimal"].schema is not None
    assert by_id["minimal"].parse_error is None
    assert by_id["bad"].schema is None
    assert by_id["bad"].parse_error is not None


def test_tool_schema_accepts_new_optional_fields() -> None:
    """The fields ratified in DECISIONS s table-additions all parse."""

    body = dict(VALID_MINIMAL)
    body.update(
        {
            "schema_version": "1.0",
            "concurrent": False,
            "validator_timeout_override": 60,
            "requires_data_persistence": True,
            "input_transport": "multipart",
            "provides_file_endpoint": True,
            "provides_autocomplete": True,
        }
    )
    schema = ToolSchema.model_validate(body)
    assert schema.concurrent is False
    assert schema.input_transport == "multipart"
    assert schema.provides_file_endpoint is True


@pytest.mark.parametrize(
    "input_type,extra",
    [
        ("text", {}),
        ("textarea", {}),
        ("number", {}),
        ("select", {"options": [{"value": "a", "label": "A"}]}),
        ("toggle", {}),
        ("date", {}),
        ("file", {}),
        ("slider", {"min": 0, "max": 10}),
    ],
)
def test_input_union_dispatches_per_type(input_type: str, extra: dict) -> None:
    """The discriminated union routes to the right Pydantic variant per type."""

    body = dict(VALID_MINIMAL)
    body["inputs"] = [
        {"key": "x", "type": input_type, "label": "X", **extra}
    ]
    schema = ToolSchema.model_validate(body)
    assert schema.inputs[0].type == input_type


@pytest.mark.parametrize(
    "output_type",
    ["text", "number", "table", "chart_line", "map_points", "image", "log"],
)
def test_output_union_dispatches_per_type(output_type: str) -> None:
    body = dict(VALID_MINIMAL)
    body["outputs"] = [{"key": "y", "type": output_type, "label": "Y"}]
    schema = ToolSchema.model_validate(body)
    assert schema.outputs[0].type == output_type


def test_discover_tools_missing_dir_returns_empty(tmp_path: Path) -> None:
    """A non-existent tools dir must return an empty list, not raise."""

    assert discover_tools(tmp_path / "no-such-dir") == []
