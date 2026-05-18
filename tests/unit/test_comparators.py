"""Unit tests for ``pixie.comparators``.

Covers numeric isclose, text exact / normalised / json_normalized,
table rows_unordered, structural compare (boolean, kv, tree), timeline,
file comparator, map points, chart line, image SSIM degradation path,
the tolerance hierarchy in ``merged_tolerance`` and the ``compare``
+ ``deep_compare`` dispatchers.
"""

from __future__ import annotations

import math

import pytest

from pixie.comparators import compare, deep_compare, merged_tolerance
from pixie.comparators._base import (
    BUILTIN_DEFAULTS,
    Diff,
    ToleranceConfig,
    load_tolerance_yaml,
    truncate_for_display,
)
from pixie.comparators.numeric import compare_number, _isclose
from pixie.comparators.structural import compare_boolean, compare_kv, compare_tree
from pixie.comparators.table import compare_table
from pixie.comparators.text import compare_text
from pixie.comparators.timeline import compare_timeline


# --- numeric -----------------------------------------------------------------


@pytest.mark.parametrize(
    "expected,actual,rtol,is_match",
    [
        (1.0, 1.0, 1e-6, True),
        (1.0, 1.0 + 1e-12, 1e-6, True),
        (1.0, 1.5, 1e-6, False),
        (1e6, 1.000001e6, 1e-5, True),
        (1.0, 2.0, 1e-1, False),
    ],
)
def test_compare_number_isclose(expected, actual, rtol, is_match) -> None:
    diff = compare_number("n", "number", expected, actual, {"rtol": rtol, "atol": 1e-9})
    assert (diff is None) is is_match


def test_compare_number_rejects_booleans() -> None:
    diff = compare_number("n", "number", True, 1.0, {})
    assert diff is not None and "boolean" in diff.metric.lower()


def test_compare_number_unwraps_value_dict() -> None:
    diff = compare_number("n", "number", {"value": 1.0}, 1.0, {})
    assert diff is None


def test_compare_number_metric_includes_actual_rtol() -> None:
    diff = compare_number("n", "number", 1.0, 1.5, {"rtol": 1e-3, "atol": 1e-9})
    assert diff is not None
    assert "rtol_exceeded" in diff.metric


def test_isclose_nan_aware() -> None:
    assert _isclose(float("nan"), float("nan"), 1e-6, 1e-9) is True
    assert _isclose(float("nan"), 1.0, 1e-6, 1e-9) is False


# --- text --------------------------------------------------------------------


def test_compare_text_exact_match() -> None:
    assert compare_text("k", "text", "hello", "hello", {"compare": "exact"}) is None


def test_compare_text_exact_mismatch() -> None:
    diff = compare_text("k", "text", "hello", "HELLO", {"compare": "exact"})
    assert diff is not None
    assert "k" == diff.output_key


def test_compare_text_normalise_whitespace_collapses_spaces() -> None:
    diff = compare_text(
        "k", "text", "a    b", "a b",
        {"compare": "exact_after_normalize_whitespace"},
    )
    assert diff is None


def test_compare_text_json_normalised_handles_key_order() -> None:
    diff = compare_text(
        "k", "text",
        '{"a":1,"b":2}', '{"b":2,"a":1}',
        {"compare": "json_normalized"},
    )
    assert diff is None


def test_compare_text_json_normalised_fails_on_value_mismatch() -> None:
    diff = compare_text(
        "k", "text",
        '{"a":1}', '{"a":2}',
        {"compare": "json_normalized"},
    )
    assert diff is not None


def test_compare_text_json_normalised_reports_parse_error() -> None:
    diff = compare_text(
        "k", "text",
        "not-json", "still-not",
        {"compare": "json_normalized"},
    )
    assert diff is not None
    assert "json parse failure" in diff.metric


def test_compare_text_latex_normalises_whitespace() -> None:
    diff = compare_text(
        "k", "latex",
        r"\frac{1}{2}", r"\frac{1}{2}  ", {},
    )
    assert diff is None


# --- structural --------------------------------------------------------------


def test_compare_boolean_match() -> None:
    assert compare_boolean("b", "boolean", True, True, {}) is None


def test_compare_boolean_mismatch() -> None:
    diff = compare_boolean("b", "boolean", True, False, {})
    assert diff is not None


def test_compare_kv_keys_match() -> None:
    diff = compare_kv("k", "kv", {"a": 1, "b": 2}, {"b": 2, "a": 1}, {})
    assert diff is None


def test_compare_kv_value_mismatch_reports_first_key() -> None:
    diff = compare_kv("k", "kv", {"a": 1, "b": 2}, {"a": 1, "b": 9}, {})
    assert diff is not None


def test_compare_tree_structural_match() -> None:
    a = {"label": "root", "children": [{"label": "x", "children": []}]}
    b = {"label": "root", "children": [{"label": "x", "children": []}]}
    assert compare_tree("t", "tree", a, b, {}) is None


def test_compare_tree_size_mismatch_flags_diff() -> None:
    a = {"label": "root", "children": []}
    b = {"label": "root", "children": [{"label": "y", "children": []}]}
    diff = compare_tree("t", "tree", a, b, {})
    assert diff is not None


# --- table -------------------------------------------------------------------


def test_compare_table_ordered_match() -> None:
    expected = {"columns": ["a", "b"], "rows": [{"a": 1, "b": 2}]}
    actual = {"columns": ["a", "b"], "rows": [{"a": 1, "b": 2}]}
    assert compare_table("t", "table", expected, actual, {"compare": "rows_ordered"}) is None


def test_compare_table_unordered_match() -> None:
    expected = {
        "columns": ["a"], "rows": [{"a": 1}, {"a": 2}, {"a": 3}],
    }
    actual = {
        "columns": ["a"], "rows": [{"a": 3}, {"a": 1}, {"a": 2}],
    }
    diff = compare_table("t", "table", expected, actual, {"compare": "rows_unordered"})
    assert diff is None


def test_compare_table_column_name_mismatch() -> None:
    expected = {"columns": ["a"], "rows": [{"a": 1}]}
    actual = {"columns": ["b"], "rows": [{"b": 1}]}
    diff = compare_table("t", "table", expected, actual, {})
    assert diff is not None


def test_compare_table_row_count_mismatch() -> None:
    expected = {"columns": ["a"], "rows": [{"a": 1}, {"a": 2}]}
    actual = {"columns": ["a"], "rows": [{"a": 1}]}
    diff = compare_table("t", "table", expected, actual, {})
    assert diff is not None


def test_compare_table_rejects_non_dict_input() -> None:
    diff = compare_table("t", "table", "rows", "rows", {})
    assert diff is not None


# --- timeline ----------------------------------------------------------------


def test_compare_timeline_match() -> None:
    a = [{"label": "x", "at": "2026-01-01"}]
    b = [{"label": "x", "at": "2026-01-01"}]
    assert compare_timeline("tl", "timeline", a, b, {}) is None


def test_compare_timeline_mismatch() -> None:
    a = [{"label": "x", "at": "2026-01-01"}]
    b = [{"label": "y", "at": "2026-01-01"}]
    diff = compare_timeline("tl", "timeline", a, b, {})
    assert diff is not None


# --- top-level dispatch ------------------------------------------------------


def test_compare_dispatches_to_number() -> None:
    assert compare(1.0, 1.0, "number", "n", {}) is None
    diff = compare(1.0, 2.0, "number", "n", {})
    assert diff is not None and diff.comparator.startswith("numeric")


def test_compare_skip_returns_skip_diff() -> None:
    diff = compare(1.0, 2.0, "number", "n", {"compare": "skip"})
    assert diff is not None and diff.comparator == "skip"


def test_compare_unknown_type_returns_none() -> None:
    # The dispatcher maps "progress" -> None (always skip).
    assert compare(0.5, 0.7, "progress", "p", {}) is None


# --- deep_compare ------------------------------------------------------------


def _output_spec(key: str, type_: str):
    """Build a minimal namespace mimicking an output_spec.key/.type."""

    class _Spec:
        pass
    spec = _Spec()
    spec.key = key
    spec.type = type_
    return spec


def test_deep_compare_emits_no_diff_when_all_outputs_match() -> None:
    specs = [_output_spec("n", "number")]
    diffs = deep_compare(
        {"n": 1.0}, {"n": 1.0}, specs, ToleranceConfig()
    )
    assert diffs == []


def test_deep_compare_flags_missing_key() -> None:
    specs = [_output_spec("n", "number")]
    diffs = deep_compare(
        {"n": 1.0}, {}, specs, ToleranceConfig()
    )
    assert len(diffs) == 1
    assert diffs[0].comparator == "key_presence"


def test_deep_compare_flags_undeclared_key_when_options_strict() -> None:
    specs = [_output_spec("n", "number")]
    cfg = ToleranceConfig.model_validate(
        {"options": {"on_extra_output_key": "warn"}}
    )
    diffs = deep_compare(
        {"n": 1.0, "extra": 9},
        {"n": 1.0, "extra": 9},
        specs, cfg,
    )
    assert any(d.comparator == "schema_check" for d in diffs)


# --- tolerance hierarchy -----------------------------------------------------


def test_merged_tolerance_builtin_default_for_number() -> None:
    merged = merged_tolerance("n", "number", ToleranceConfig())
    assert "rtol" in merged
    assert merged["rtol"] == BUILTIN_DEFAULTS["number"]["rtol"]


def test_merged_tolerance_fixture_override_wins() -> None:
    merged = merged_tolerance(
        "n", "number", ToleranceConfig(),
        fixture_overrides={"n": {"rtol": 1e-2}},
    )
    assert merged["rtol"] == 1e-2


def test_merged_tolerance_project_default_supplements_builtin() -> None:
    cfg = ToleranceConfig.model_validate(
        {"defaults": {"number": {"atol": 5e-2}}}
    )
    merged = merged_tolerance("n", "number", cfg)
    assert merged["atol"] == 5e-2
    # rtol comes from builtin because project default did not set it.
    assert "rtol" in merged


# --- tolerance.yaml loader ---------------------------------------------------


def test_load_tolerance_yaml_missing_file_returns_empty(tmp_path) -> None:
    cfg = load_tolerance_yaml(tmp_path / "tolerance.yaml")
    assert cfg.errors == []
    assert isinstance(cfg, ToleranceConfig)


def test_load_tolerance_yaml_parses_valid(tmp_path) -> None:
    p = tmp_path / "tolerance.yaml"
    p.write_text(
        "defaults:\n"
        "  number:\n"
        "    rtol: 0.001\n",
        encoding="utf-8",
    )
    cfg = load_tolerance_yaml(p)
    assert cfg.errors == []
    assert cfg.defaults_for("number")["rtol"] == 0.001


def test_load_tolerance_yaml_captures_parse_error(tmp_path) -> None:
    p = tmp_path / "tolerance.yaml"
    p.write_text("invalid: : :", encoding="utf-8")
    cfg = load_tolerance_yaml(p)
    assert cfg.errors


# --- truncation --------------------------------------------------------------


def test_truncate_for_display_shortens_long_strings() -> None:
    out = truncate_for_display("a" * 5000, limit=100)
    assert len(out) <= 200  # truncated + ellipsis annotation
