"""Unit tests for check #12 (``reference_fixtures_match``).

Covers the pure parts of the comparator pipeline (dispatcher, tolerance
hierarchy, per-type comparators, fixture loader, tolerance.yaml loader).
The live-process scenarios — pass-case, fail-case, skip-case — live in
``tests/integration/test_reference_check.py`` where a real venv is
available.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixie.comparators import (
    BUILTIN_DEFAULTS,
    Diff,
    ToleranceConfig,
    compare,
    deep_compare,
    load_fixtures,
    load_tolerance_yaml,
    merged_tolerance,
)
from pixie.comparators.chart import compare_chart
from pixie.comparators.file import compare_file
from pixie.comparators.map import compare_map
from pixie.comparators.media import compare_image
from pixie.comparators.numeric import compare_number
from pixie.comparators.structural import compare_boolean, compare_kv, compare_tree
from pixie.comparators.table import compare_table
from pixie.comparators.text import compare_text
from pixie.comparators.timeline import compare_timeline


# --- numeric -----------------------------------------------------------------


def test_numeric_passes_within_rtol() -> None:
    assert compare_number("v", "number", 1.0, 1.000001, {"rtol": 1e-4, "atol": 1e-9}) is None


def test_numeric_fails_outside_rtol() -> None:
    diff = compare_number("v", "number", 1.0, 1.5, {"rtol": 1e-4, "atol": 1e-9})
    assert diff is not None and "rtol_exceeded" in (diff.metric or "")


def test_numeric_rejects_boolean() -> None:
    diff = compare_number("v", "number", True, 1.0, {"rtol": 1e-6, "atol": 1e-9})
    assert diff is not None and "boolean" in (diff.metric or "").lower()


# --- text --------------------------------------------------------------------


def test_text_exact() -> None:
    assert compare_text("k", "text", "hello", "hello", {"compare": "exact"}) is None
    diff = compare_text("k", "text", "hello", "world", {"compare": "exact"})
    assert diff is not None


def test_text_normalised_whitespace() -> None:
    # Trailing whitespace stripped, runs of whitespace within a line collapsed.
    e = "hello   world   "
    a = "hello world"
    tol = {"compare": "exact_after_normalize_whitespace"}
    assert compare_text("k", "markdown", e, a, tol) is None


# --- boolean / kv / tree -----------------------------------------------------


def test_boolean() -> None:
    assert compare_boolean("k", "boolean", True, True, {}) is None
    assert compare_boolean("k", "boolean", True, False, {}) is not None


def test_kv_per_value_dispatch() -> None:
    tol = {"compare": "dict_per_value", "allow_extra": False,
           "float_rtol": 1e-6, "float_atol": 1e-9}
    assert compare_kv("k", "kv", {"a": 1, "b": "x"}, {"a": 1.0000001, "b": "x"}, tol) is None
    diff = compare_kv("k", "kv", {"a": 1}, {"a": 2}, tol)
    assert diff is not None and "1" in (diff.metric or "")


def test_tree_structural_unordered() -> None:
    e = {"id": "root", "children": [
        {"id": "a"}, {"id": "b", "children": [{"id": "ba"}]},
    ]}
    a = {"id": "root", "children": [
        {"id": "b", "children": [{"id": "ba"}]}, {"id": "a"},
    ]}
    assert compare_tree("k", "tree", e, a, {"children_order": "unordered"}) is None


# --- table -------------------------------------------------------------------


def test_table_rows_unordered_passes() -> None:
    e = {"columns": ["name", "score"], "rows": [["a", 1], ["b", 2]]}
    a = {"columns": ["name", "score"], "rows": [["b", 2], ["a", 1]]}
    tol = {"compare": "rows_unordered", "float_rtol": 1e-6, "float_atol": 1e-9}
    assert compare_table("k", "table", e, a, tol) is None


def test_table_row_count_mismatch() -> None:
    e = {"columns": ["x"], "rows": [[1], [2]]}
    a = {"columns": ["x"], "rows": [[1]]}
    diff = compare_table("k", "table", e, a, {"compare": "rows_unordered",
                                              "float_rtol": 1e-6, "float_atol": 1e-9})
    assert diff is not None and "row counts" in (diff.metric or "")


# --- chart -------------------------------------------------------------------


def test_chart_data_only_by_name() -> None:
    e = {"x": [1, 2, 3], "series": [{"name": "rev", "y": [10, 20, 30]}]}
    a = {"x": [1, 2, 3], "series": [{"name": "rev", "y": [10, 20.0000001, 30]}]}
    tol = {"compare": "data_only", "series_match": "by_name",
           "float_rtol": 1e-6, "float_atol": 1e-9}
    assert compare_chart("c", "chart_line", e, a, tol) is None


def test_chart_pie_slices_unordered() -> None:
    e = {"slices": [{"label": "EU", "value": 30}, {"label": "AS", "value": 70}]}
    a = {"slices": [{"label": "AS", "value": 70}, {"label": "EU", "value": 30}]}
    tol = {"compare": "slices_unordered", "float_rtol": 1e-6, "float_atol": 1e-9}
    assert compare_chart("c", "chart_pie", e, a, tol) is None


# --- map ---------------------------------------------------------------------


def test_map_points_round_set() -> None:
    e = {"points": [[51.50745, -0.12780], [40.7128, -74.0060]]}
    a = {"points": [[40.71281, -74.00601], [51.5074, -0.1278]]}
    tol = {"compare": "set_equal_after_round_coords_4dp", "round_digits": 4,
           "float_rtol": 1e-6, "float_atol": 1e-9}
    assert compare_map("m", "map_points", e, a, tol) is None


def test_map_choropleth_keyed_values() -> None:
    tol = {"compare": "keyed_values", "float_rtol": 1e-6, "float_atol": 1e-9}
    e = {"values": {"FR": 67.2, "DE": 83.1}}
    a = {"values": {"DE": 83.10001, "FR": 67.20001}}
    assert compare_map("m", "map_choropleth", e, a, tol) is None


# --- media (degrade-when-missing) --------------------------------------------


def test_image_degrades_to_sha256_when_skimage_missing() -> None:
    # Two raw-data strings; even if skimage isn't installed, identical
    # values must compare equal via sha256+size fallback.
    same_url = "data:image/png;base64,AAAA"
    assert compare_image("img", "image", same_url, same_url, {"compare": "ssim", "min_ssim": 0.95}) is None


def test_image_size_sha256_mode_explicit() -> None:
    diff = compare_image("img", "image", "data:image/png;base64,AAAA",
                         "data:image/png;base64,BBBB",
                         {"compare": "size_sha256"})
    assert diff is not None and "sha256 differs" in (diff.metric or "")


# --- timeline ----------------------------------------------------------------


def test_timeline_rows_ordered() -> None:
    e = {"events": [{"at": "T0", "msg": "a"}, {"at": "T1", "msg": "b"}]}
    a = {"events": [{"at": "T0", "msg": "a"}, {"at": "T1", "msg": "b"}]}
    assert compare_timeline("k", "timeline", e, a, {}) is None
    a2 = {"events": [{"at": "T0", "msg": "a"}, {"at": "T1", "msg": "x"}]}
    diff = compare_timeline("k", "timeline", e, a2, {})
    assert diff is not None


# --- file --------------------------------------------------------------------


def test_file_sha256_match() -> None:
    e = {"filename": "a.bin", "data": "data:application/octet-stream;base64,QUE="}
    a = {"filename": "a.bin", "data": "data:application/octet-stream;base64,QUE="}
    assert compare_file("f", "file", e, a, {"compare": "sha256"}) is None


def test_file_json_dispatch() -> None:
    payload = {"mime": "application/json", "data": json.dumps({"k": 1})}
    payload_b = {"mime": "application/json", "data": json.dumps({"k": 1})}
    assert compare_file("f", "file", payload, payload_b, {"compare": "mime_dispatch"}) is None


# --- tolerance hierarchy -----------------------------------------------------


def test_merged_tolerance_layers() -> None:
    cfg = ToleranceConfig()
    # built-in default has rtol=1e-6 for number
    merged = merged_tolerance("v", "number", cfg, fixture_overrides=None)
    assert merged["rtol"] == 1e-6
    # fixture override wins
    merged = merged_tolerance("v", "number", cfg, fixture_overrides={"v": {"rtol": 1e-2}})
    assert merged["rtol"] == 1e-2


def test_builtin_defaults_covers_all_known_types() -> None:
    """Every output type that has a dispatcher must have a built-in default."""

    expected = {
        "text", "markdown", "code", "latex", "diff", "stream_text",
        "number", "boolean", "kv", "table", "tree",
        "chart_line", "chart_bar", "chart_area", "chart_scatter", "chart_pie",
        "chart_histogram", "chart_boxplot", "chart_heatmap", "chart_candlestick",
        "chart_radar", "chart_sankey", "chart_treemap", "chart_network",
        "map_points", "map_heatmap", "map_choropleth", "map_polygons", "map_route",
        "image", "image_grid", "image_compare", "audio", "video",
        "timeline", "gantt", "log", "progress", "file",
    }
    missing = expected - set(BUILTIN_DEFAULTS)
    assert not missing, f"missing built-in defaults for: {missing}"


# --- loaders -----------------------------------------------------------------


def test_load_tolerance_yaml_missing_returns_defaults(tmp_path: Path) -> None:
    config = load_tolerance_yaml(tmp_path / "nope.yaml")
    assert config.errors == []
    assert config.defaults.number.rtol == 1e-6


def test_load_tolerance_yaml_invalid_compare_collects_errors(tmp_path: Path) -> None:
    (tmp_path / "tolerance.yaml").write_text(
        "defaults:\n  table: { compare: invalid_mode }\n",
        encoding="utf-8",
    )
    config = load_tolerance_yaml(tmp_path / "tolerance.yaml")
    assert config.errors


def test_load_fixtures_rejects_undeclared_output_key(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture_x.json"
    fixture_path.write_text(json.dumps({
        "name": "X", "inputs": {"a": 1},
        "expected_outputs": {"undeclared": 1},
    }), encoding="utf-8")
    _, errors = load_fixtures([fixture_path], declared_output_keys={"declared"})
    assert errors and "undeclared" in errors[0]


def test_load_fixtures_parses_valid(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture_basic.json"
    fixture_path.write_text(json.dumps({
        "name": "Basic", "inputs": {"x": 4},
        "expected_outputs": {"result": 2.0},
    }), encoding="utf-8")
    fixtures, errors = load_fixtures([fixture_path], declared_output_keys={"result"})
    assert errors == []
    assert len(fixtures) == 1
    assert fixtures[0].inputs == {"x": 4}


# --- dispatcher --------------------------------------------------------------


def test_compare_dispatches_by_output_type() -> None:
    diff = compare(1.0, 1.5, "number", "v", {"rtol": 1e-4, "atol": 1e-9})
    assert isinstance(diff, Diff) and diff.comparator == "numeric_isclose"


def test_compare_skip_short_circuits() -> None:
    diff = compare(1.0, 2.0, "number", "v", {"compare": "skip"})
    assert diff is not None and diff.comparator == "skip"


def test_deep_compare_missing_key_reports() -> None:
    """A missing actual output key must be reported (default option=fail)."""

    from pixie.discovery import ToolSchema

    schema = ToolSchema.model_validate({
        "id": "x", "name": "x",
        "inputs": [{"key": "a", "type": "number", "label": "a"}],
        "outputs": [{"key": "result", "type": "number", "label": "Result"}],
    })
    cfg = ToleranceConfig()
    diffs = deep_compare({"result": 1.0}, {}, schema.outputs, cfg, None)
    assert len(diffs) == 1
    assert "missing" in (diffs[0].metric or "")
