"""Unit tests for ``pixie.validator``.

Focuses on the pure helpers (sample-input generation, report
summarisation, output-shape checking) — the full 11-check pipeline
against a real tool lives in the integration suite where a real venv
is on hand.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixie.discovery import ToolSchema, load_tool_schema
from pixie.validator import (
    ValidationCheck,
    ValidationReport,
    _check_output_value,
    generate_sample_inputs,
    summary_report,
)

VALID_SCHEMA = {
    "id": "fixture",
    "name": "Fixture",
    "inputs": [
        {"key": "n", "type": "number", "label": "N", "default": 7},
        {"key": "name", "type": "text", "label": "Name", "default": "world"},
        {"key": "flag", "type": "toggle", "label": "Flag", "default": True},
    ],
    "outputs": [
        {"key": "n", "type": "number", "label": "N"},
        {"key": "msg", "type": "text", "label": "Msg"},
    ],
}


def test_generate_sample_inputs_uses_defaults_when_present() -> None:
    """Defaults declared in tool.json win over the type-based fallback."""

    schema = ToolSchema.model_validate(VALID_SCHEMA)
    sample = generate_sample_inputs(schema)
    assert sample["n"] == 7
    assert sample["name"] == "world"
    assert sample["flag"] is True


def test_generate_sample_inputs_falls_back_per_type() -> None:
    """Inputs without a default get a type-appropriate placeholder."""

    body = dict(VALID_SCHEMA)
    body["inputs"] = [{"key": "free", "type": "text", "label": "Free"}]
    schema = ToolSchema.model_validate(body)
    sample = generate_sample_inputs(schema)
    assert "free" in sample
    assert isinstance(sample["free"], str)


def test_check_output_value_passes_correct_shape() -> None:
    """A number output with an int value is accepted."""

    schema = ToolSchema.model_validate(VALID_SCHEMA)
    number_spec = schema.outputs[0]
    status, _ = _check_output_value(number_spec, 42)
    assert status == "pass"


def test_check_output_value_flags_wrong_shape() -> None:
    """A number output with a dict value is flagged."""

    schema = ToolSchema.model_validate(VALID_SCHEMA)
    number_spec = schema.outputs[0]
    status, message = _check_output_value(number_spec, {"not": "a number"})
    assert status in {"fail", "warn"}
    assert message  # carries a useful explanation


def test_summary_report_collapses_passes() -> None:
    """``summary_report`` keeps fail / warn rows and drops the noise."""

    report = ValidationReport(
        tool_id="fixture",
        tool_path="/tmp",
        timestamp="2026-01-01T00:00:00+00:00",  # type: ignore[arg-type]
        overall="warn",
        checks=[
            ValidationCheck(name="folder_structure", status="pass", message="ok"),
            ValidationCheck(name="venv", status="fail", message="missing"),
            ValidationCheck(name="streaming", status="warn", message="slow"),
        ],
        sample_inputs=None,
        sample_output=None,
        spawn_log=None,
    )
    summary = summary_report(report)
    # The summary keeps an aggregated count per status plus a list of
    # notable (fail/warn) checks. Passes are folded into the counts.
    assert summary["counts"]["pass"] == 1
    assert summary["counts"]["fail"] == 1
    assert summary["counts"]["warn"] == 1
    notable = {entry["name"]: entry["status"] for entry in summary["notable_checks"]}
    assert notable == {"venv": "fail", "streaming": "warn"}


def test_example_tool_schema_loads_cleanly() -> None:
    """The committed example tool must round-trip through ``ToolSchema``."""

    example_path = Path(__file__).resolve().parents[2] / "tools" / "example-compound-interest"
    schema = load_tool_schema(example_path)
    assert schema.id == "compound-interest"
    assert schema.outputs[0].type in {"number", "chart_line", "table"}
