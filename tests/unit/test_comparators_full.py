"""Additional comparator coverage targeting chart/map/file/media/timeline."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from typing import Any

import pytest

from pixie.comparators import compare, compare_chart  # type: ignore[attr-defined]
from pixie.comparators.chart import (
    _compare_candlestick,
    _compare_graph,
    _compare_matrix,
    _compare_series_summary,
    _compare_slices,
    _compare_treemap,
    _compare_values_unordered,
    compare_chart,
)
from pixie.comparators.file import compare_file, _file_bytes
from pixie.comparators.map import compare_map, _round_point
from pixie.comparators.media import (
    compare_image,
    compare_image_compare,
    compare_image_grid,
    compare_audio,
    compare_video,
    _decode_image_bytes,
    _image_fallback,
)
from pixie.comparators.structural import compare_kv, compare_tree
from pixie.comparators.timeline import compare_timeline, _compare_log_line


# --- chart family ------------------------------------------------------------


def _line_spec(values):
    return {"x": [1, 2, 3], "series": [{"name": "a", "y": values}]}


def test_chart_data_only_match() -> None:
    a = _line_spec([1.0, 2.0, 3.0])
    b = _line_spec([1.0, 2.0, 3.0])
    assert compare_chart("c", "chart_line", a, b,
                          {"compare": "data_only", "float_rtol": 1e-6, "float_atol": 1e-9}) is None


def test_chart_data_only_value_mismatch() -> None:
    a = _line_spec([1.0, 2.0])
    b = _line_spec([1.0, 9.0])
    diff = compare_chart("c", "chart_line", a, b, {"compare": "data_only"})
    assert diff is not None


def test_chart_data_only_x_axis_mismatch() -> None:
    a = {"x": [1, 2], "series": []}
    b = {"x": [1, 3], "series": []}
    diff = compare_chart("c", "chart_line", a, b, {"compare": "data_only"})
    assert diff is not None
    assert "x-axis" in (diff.metric or "")


def test_chart_data_only_series_count_mismatch() -> None:
    a = {"series": [{"name": "a", "y": [1]}]}
    b = {"series": []}
    diff = compare_chart("c", "chart_line", a, b, {"compare": "data_only"})
    assert diff is not None
    assert "series count" in (diff.metric or "")


def test_chart_data_only_missing_series_name() -> None:
    a = {"series": [{"name": "a", "y": [1]}]}
    b = {"series": [{"name": "b", "y": [1]}]}
    diff = compare_chart("c", "chart_line", a, b, {"compare": "data_only"})
    assert diff is not None


def test_chart_data_only_series_by_index() -> None:
    a = {"series": [{"y": [1.0]}]}
    b = {"series": [{"y": [1.0]}]}
    assert compare_chart("c", "chart_line", a, b,
                          {"compare": "data_only", "series_match": "by_index"}) is None


def test_chart_slices_match() -> None:
    a = {"slices": [{"label": "x", "value": 1.0}, {"label": "y", "value": 2.0}]}
    b = {"slices": [{"label": "y", "value": 2.0}, {"label": "x", "value": 1.0}]}
    assert compare_chart("c", "chart_pie", a, b, {"compare": "slices_unordered"}) is None


def test_chart_slices_mismatch_count() -> None:
    a = {"slices": [{"label": "x", "value": 1}]}
    b = {"slices": []}
    diff = compare_chart("c", "chart_pie", a, b, {"compare": "slices_unordered"})
    assert diff is not None


def test_chart_slices_missing_label() -> None:
    a = {"slices": [{"label": "x", "value": 1}, {"label": "y", "value": 2}]}
    b = {"slices": [{"label": "x", "value": 1}, {"label": "z", "value": 2}]}
    diff = compare_chart("c", "chart_pie", a, b, {"compare": "slices_unordered"})
    assert diff is not None


def test_chart_slices_value_mismatch() -> None:
    a = {"slices": [{"label": "x", "value": 1.0}]}
    b = {"slices": [{"label": "x", "value": 2.0}]}
    diff = compare_chart("c", "chart_pie", a, b, {"compare": "slices_unordered"})
    assert diff is not None


def test_chart_values_unordered_match() -> None:
    a = {"values": [1, 2, 3]}
    b = {"values": [3, 1, 2]}
    assert compare_chart("c", "chart_histogram", a, b, {"compare": "values_unordered"}) is None


def test_chart_values_unordered_count_diff() -> None:
    diff = compare_chart("c", "chart_histogram",
                          {"values": [1, 2]}, {"values": [1]},
                          {"compare": "values_unordered"})
    assert diff is not None


def test_chart_values_unordered_value_diff() -> None:
    diff = compare_chart("c", "chart_histogram",
                          {"values": [1.0]}, {"values": [9.0]},
                          {"compare": "values_unordered"})
    assert diff is not None


def test_chart_series_summary_match() -> None:
    a = {"series": [{"name": "a", "q1": 1, "q2": 2, "q3": 3, "min": 0, "max": 5, "median": 2}]}
    b = {"series": [{"name": "a", "q1": 1, "q2": 2, "q3": 3, "min": 0, "max": 5, "median": 2}]}
    assert compare_chart("c", "chart_boxplot", a, b, {"compare": "series_summary"}) is None


def test_chart_series_summary_mismatch() -> None:
    a = {"series": [{"name": "a", "q1": 1}]}
    b = {"series": [{"name": "a", "q1": 99}]}
    diff = compare_chart("c", "chart_boxplot", a, b, {"compare": "series_summary"})
    assert diff is not None


def test_chart_matrix_match() -> None:
    a = {"z": [[1, 2], [3, 4]]}
    b = {"z": [[1, 2], [3, 4]]}
    assert compare_chart("c", "chart_heatmap", a, b, {"compare": "matrix_elementwise"}) is None


def test_chart_matrix_row_count_diff() -> None:
    diff = compare_chart("c", "chart_heatmap",
                          {"z": [[1]]}, {"z": [[1], [2]]},
                          {"compare": "matrix_elementwise"})
    assert diff is not None


def test_chart_matrix_cell_diff() -> None:
    diff = compare_chart("c", "chart_heatmap",
                          {"z": [[1, 2]]}, {"z": [[1, 99]]},
                          {"compare": "matrix_elementwise"})
    assert diff is not None


def test_chart_candlestick_match() -> None:
    pt = {"t": 1, "o": 1, "h": 2, "l": 0, "c": 1}
    a = {"points": [pt, pt]}
    b = {"points": [pt, pt]}
    assert compare_chart("c", "chart_candlestick", a, b, {"compare": "rows_ordered"}) is None


def test_chart_candlestick_value_diff() -> None:
    a = {"points": [{"o": 1, "h": 2, "l": 0, "c": 1}]}
    b = {"points": [{"o": 1, "h": 99, "l": 0, "c": 1}]}
    diff = compare_chart("c", "chart_candlestick", a, b, {"compare": "rows_ordered"})
    assert diff is not None


def test_chart_graph_match() -> None:
    a = {"nodes": [{"id": "a"}, {"id": "b"}], "links": [{"source": "a", "target": "b", "value": 1}]}
    b = {"nodes": [{"id": "b"}, {"id": "a"}], "links": [{"source": "a", "target": "b", "value": 1}]}
    assert compare_chart("c", "chart_sankey", a, b, {"compare": "graph_set"}) is None


def test_chart_graph_node_set_diff() -> None:
    a = {"nodes": [{"id": "a"}], "links": []}
    b = {"nodes": [{"id": "b"}], "links": []}
    diff = compare_chart("c", "chart_sankey", a, b, {"compare": "graph_set"})
    assert diff is not None


def test_chart_graph_edge_count_diff() -> None:
    a = {"nodes": [{"id": "a"}, {"id": "b"}],
          "links": [{"source": "a", "target": "b"}]}
    b = {"nodes": [{"id": "a"}, {"id": "b"}], "links": []}
    diff = compare_chart("c", "chart_sankey", a, b, {"compare": "graph_set"})
    assert diff is not None


def test_chart_treemap_match() -> None:
    a = {"nodes": [{"name": "root", "parent": None, "value": 100}]}
    b = {"nodes": [{"name": "root", "parent": None, "value": 100}]}
    assert compare_chart("c", "chart_treemap", a, b, {"compare": "tree_set"}) is None


def test_chart_treemap_set_diff() -> None:
    a = {"nodes": [{"name": "x", "parent": None}]}
    b = {"nodes": [{"name": "y", "parent": None}]}
    diff = compare_chart("c", "chart_treemap", a, b, {"compare": "tree_set"})
    assert diff is not None


def test_chart_unknown_mode_returns_diff() -> None:
    diff = compare_chart("c", "chart_line", {}, {}, {"compare": "bogus"})
    assert diff is not None and "unknown" in (diff.metric or "")


def test_chart_skip_returns_none() -> None:
    assert compare_chart("c", "chart_line", {}, {}, {"compare": "skip"}) is None


def test_chart_non_dict_returns_diff() -> None:
    diff = compare_chart("c", "chart_line", [1, 2], {}, {"compare": "data_only"})
    assert diff is not None


# --- map family --------------------------------------------------------------


def test_map_points_match() -> None:
    a = {"points": [{"lat": 1.0001, "lng": 2.0001}]}
    b = {"points": [{"lat": 1.0001, "lng": 2.0001}]}
    assert compare_map("m", "map_points", a, b,
                        {"compare": "set_equal_after_round_coords_4dp"}) is None


def test_map_points_round_diff_within_tolerance() -> None:
    a = {"points": [{"lat": 1.00001, "lng": 2.00001}]}
    b = {"points": [{"lat": 1.00002, "lng": 2.00002}]}
    # 5 decimal differences round to 4dp -> same
    assert compare_map("m", "map_points", a, b,
                        {"compare": "set_equal_after_round_coords_4dp",
                         "round_digits": 4}) is None


def test_map_points_count_diff() -> None:
    diff = compare_map("m", "map_points",
                        {"points": [{"lat": 1.0, "lng": 2.0}]},
                        {"points": []},
                        {"compare": "set_equal_after_round_coords_4dp"})
    assert diff is not None


def test_map_points_set_diff() -> None:
    diff = compare_map("m", "map_points",
                        {"points": [{"lat": 1.0, "lng": 2.0}]},
                        {"points": [{"lat": 9.0, "lng": 8.0}]},
                        {"compare": "set_equal_after_round_coords_4dp"})
    assert diff is not None


def test_map_heatmap_intensity_diff() -> None:
    diff = compare_map("m", "map_heatmap",
                        {"points": [{"lat": 1, "lng": 2, "intensity": 0.5}]},
                        {"points": [{"lat": 1, "lng": 2, "intensity": 0.99}]},
                        {"compare": "set_equal_after_round_coords_4dp"})
    assert diff is not None


def test_map_route_match() -> None:
    pts = [{"lat": 1, "lng": 2}, {"lat": 3, "lng": 4}]
    assert compare_map("m", "map_route", {"points": pts}, {"points": pts},
                        {"compare": "ordered_after_round_coords_4dp"}) is None


def test_map_route_order_diff() -> None:
    a = {"points": [{"lat": 1, "lng": 2}, {"lat": 3, "lng": 4}]}
    b = {"points": [{"lat": 3, "lng": 4}, {"lat": 1, "lng": 2}]}
    diff = compare_map("m", "map_route", a, b,
                        {"compare": "ordered_after_round_coords_4dp"})
    assert diff is not None


def test_map_choropleth_match() -> None:
    a = {"values": {"X": 1.0, "Y": 2.0}}
    b = {"values": {"Y": 2.0, "X": 1.0}}
    assert compare_map("m", "map_choropleth", a, b, {"compare": "keyed_values"}) is None


def test_map_choropleth_key_diff() -> None:
    diff = compare_map("m", "map_choropleth",
                        {"values": {"X": 1}}, {"values": {"Y": 1}},
                        {"compare": "keyed_values"})
    assert diff is not None


def test_map_choropleth_value_diff() -> None:
    diff = compare_map("m", "map_choropleth",
                        {"values": {"X": 1.0}}, {"values": {"X": 99.0}},
                        {"compare": "keyed_values"})
    assert diff is not None


def test_map_choropleth_non_dict() -> None:
    # values=[1,2] is truthy, so it's preserved; comparator sees list != dict
    diff = compare_map("m", "map_choropleth",
                        {"values": [1, 2]}, {"values": {"X": 1}},
                        {"compare": "keyed_values"})
    assert diff is not None


def test_map_polygons_match() -> None:
    poly = {"coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    assert compare_map("m", "map_polygons",
                        {"polygons": [poly]}, {"polygons": [poly]},
                        {"compare": "set_equal_after_round_coords_4dp"}) is None


def test_map_skip() -> None:
    assert compare_map("m", "map_points", {}, {}, {"compare": "skip"}) is None


def test_map_round_point_tuple() -> None:
    assert _round_point([1.0001, 2.0001], 3) == (1.0, 2.0)


def test_map_round_point_with_latitude_alias() -> None:
    assert _round_point({"latitude": 1.0, "longitude": 2.0}, 4) == (1.0, 2.0)


def test_map_unknown_type() -> None:
    diff = compare_map("m", "map_alien", {}, {}, {"compare": "set_equal_after_round_coords_4dp"})
    assert diff is not None and "unsupported" in (diff.metric or "")


def test_map_non_dict_returns_diff() -> None:
    diff = compare_map("m", "map_points", [], {}, {"compare": "set_equal_after_round_coords_4dp"})
    assert diff is not None


# --- file --------------------------------------------------------------------


def _data_url(mime: str, body: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(body).decode()}"


def test_file_sha256_match() -> None:
    payload = {"mime": "application/octet-stream", "data": base64.b64encode(b"abc").decode()}
    assert compare_file("f", "file", payload, payload, {"compare": "sha256"}) is None


def test_file_sha256_diff() -> None:
    a = {"mime": "application/octet-stream", "data": base64.b64encode(b"abc").decode()}
    b = {"mime": "application/octet-stream", "data": base64.b64encode(b"xyz").decode()}
    diff = compare_file("f", "file", a, b, {"compare": "sha256"})
    assert diff is not None


def test_file_json_match() -> None:
    a = _data_url("application/json", b'{"a":1,"b":2}')
    b = _data_url("application/json", b'{"b":2,"a":1}')
    assert compare_file("f", "file", a, b, {"compare": "mime_dispatch"}) is None


def test_file_json_diff() -> None:
    a = _data_url("application/json", b'{"a":1}')
    b = _data_url("application/json", b'{"a":2}')
    diff = compare_file("f", "file", a, b, {"compare": "mime_dispatch"})
    assert diff is not None


def test_file_json_parse_error() -> None:
    a = _data_url("application/json", b"not-json")
    b = _data_url("application/json", b"not-json")
    diff = compare_file("f", "file", a, b, {"compare": "mime_dispatch"})
    assert diff is not None and "json parse" in (diff.metric or "")


def test_file_csv_match() -> None:
    body = b"a,b\n1,2\n3,4\n"
    a = _data_url("text/csv", body)
    b = _data_url("text/csv", body)
    assert compare_file("f", "file", a, b, {"compare": "mime_dispatch"}) is None


def test_file_csv_diff() -> None:
    a = _data_url("text/csv", b"a\n1\n")
    b = _data_url("text/csv", b"a\n9\n")
    diff = compare_file("f", "file", a, b, {"compare": "mime_dispatch"})
    assert diff is not None


def test_file_pdf_degrades_without_pdfplumber() -> None:
    a = _data_url("application/pdf", b"%PDF-1.4\n%fake1")
    b = _data_url("application/pdf", b"%PDF-1.4\n%fake2")
    diff = compare_file("f", "file", a, b, {"compare": "mime_dispatch"})
    # degradation tags the metric (or pdfplumber is installed and yields a clean diff)
    assert diff is not None


def test_file_skip() -> None:
    assert compare_file("f", "file", {}, {}, {"compare": "skip"}) is None


def test_file_bytes_accepts_plain_string() -> None:
    raw, mime = _file_bytes("plain")
    assert raw == b"plain"
    assert mime == "text/plain"


def test_file_bytes_data_url() -> None:
    raw, mime = _file_bytes(_data_url("image/png", b"\x89PNGtest"))
    assert raw.startswith(b"\x89")
    assert mime == "image/png"


def test_file_bytes_dict_with_raw_bytes() -> None:
    raw, mime = _file_bytes({"mime": "x", "data": b"raw"})
    assert raw == b"raw"


# --- media -------------------------------------------------------------------


def _png_bytes() -> bytes:
    """Return a 2x2 red PNG."""

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def test_compare_image_match_via_size_sha256() -> None:
    payload = _data_url("image/png", _png_bytes())
    assert compare_image("i", "image", payload, payload, {"compare": "size_sha256"}) is None


def test_compare_image_diff_via_size_sha256() -> None:
    a = _data_url("image/png", _png_bytes())
    b = _data_url("image/png", b"\x89PNGdifferent")
    diff = compare_image("i", "image", a, b, {"compare": "size_sha256"})
    assert diff is not None


def test_compare_image_skip() -> None:
    assert compare_image("i", "image", "x", "x", {"compare": "skip"}) is None


def test_compare_image_ssim_match() -> None:
    # Real SSIM should pass on identical inputs (assuming scikit-image installed).
    payload = _data_url("image/png", _png_bytes())
    result = compare_image("i", "image", payload, payload, {"compare": "ssim", "min_ssim": 0.95})
    # If scikit-image is not present, it degrades to sha256 (which also matches).
    assert result is None


def test_compare_image_grid_match() -> None:
    payload = {"images": [_data_url("image/png", _png_bytes())]}
    assert compare_image_grid("i", "image_grid", payload, payload,
                                {"compare": "size_sha256"}) is None


def test_compare_image_compare_match() -> None:
    img = _data_url("image/png", _png_bytes())
    payload = {"before": img, "after": img}
    assert compare_image_compare("i", "image_compare", payload, payload,
                                  {"compare": "size_sha256"}) is None


def test_compare_audio_skip() -> None:
    assert compare_audio("a", "audio", "x", "x", {"compare": "skip"}) is None


def test_compare_audio_size_sha256_match() -> None:
    data = base64.b64encode(b"raw audio bytes").decode()
    payload = {"mime": "audio/wav", "data": data}
    assert compare_audio("a", "audio", payload, payload, {"compare": "size_sha256"}) is None


def test_compare_audio_size_sha256_diff() -> None:
    a = {"mime": "audio/wav", "data": base64.b64encode(b"a").decode()}
    b = {"mime": "audio/wav", "data": base64.b64encode(b"b").decode()}
    diff = compare_audio("a", "audio", a, b, {"compare": "size_sha256"})
    assert diff is not None


def test_compare_video_skip_default() -> None:
    assert compare_video("v", "video", "x", "x", {"compare": "skip"}) is None


def test_decode_image_bytes_data_url() -> None:
    out = _decode_image_bytes(_data_url("image/png", b"\x89PNGtest"))
    assert out.startswith(b"\x89")


def test_decode_image_bytes_http_url_returns_url_bytes() -> None:
    out = _decode_image_bytes("https://example.com/x.png")
    assert out == b"https://example.com/x.png"


def test_decode_image_bytes_dict_with_data_key() -> None:
    out = _decode_image_bytes({"data": _data_url("image/png", b"\x89P")})
    assert out.startswith(b"\x89")


def test_image_fallback_match_returns_none() -> None:
    raw = _data_url("image/png", b"abc")
    assert _image_fallback("i", "image", raw, raw, None) is None


# --- timeline / log ----------------------------------------------------------


def test_compare_timeline_events_match() -> None:
    a = {"events": [{"t": "2026-01-01", "label": "x"}]}
    b = {"events": [{"t": "2026-01-01", "label": "x"}]}
    assert compare_timeline("t", "timeline", a, b, {}) is None


def test_compare_timeline_count_diff() -> None:
    diff = compare_timeline("t", "timeline",
                              {"events": [{"t": 1}]}, {"events": []}, {})
    assert diff is not None


def test_compare_timeline_value_diff() -> None:
    diff = compare_timeline("t", "timeline",
                              {"events": [{"t": 1, "label": "x"}]},
                              {"events": [{"t": 1, "label": "y"}]}, {})
    assert diff is not None


def test_compare_timeline_non_list_raises_diff() -> None:
    diff = compare_timeline("t", "timeline", {"events": "x"}, {"events": "y"}, {})
    assert diff is not None


def test_compare_timeline_gantt_uses_tasks_field() -> None:
    a = {"tasks": [{"task": "A"}]}
    assert compare_timeline("t", "gantt", a, a, {}) is None


def test_compare_log_match() -> None:
    a = {"lines": ["info x", "info y"]}
    assert compare_timeline("t", "log", a, a, {}) is None


def test_compare_log_regex_match() -> None:
    a = {"lines": ["re:info \\d+"]}
    b = {"lines": ["info 123"]}
    assert compare_timeline("t", "log", a, b, {"allow_regex": True}) is None


def test_compare_log_regex_mismatch() -> None:
    a = {"lines": ["re:debug \\d+"]}
    b = {"lines": ["info 123"]}
    diff = compare_timeline("t", "log", a, b, {"allow_regex": True})
    assert diff is not None


def test_compare_log_line_exact_match() -> None:
    assert _compare_log_line("a", "a", False) is None


def test_compare_log_line_invalid_regex() -> None:
    msg = _compare_log_line("re:(unclosed", "x", True)
    assert msg and "invalid regex" in msg


# --- dispatcher --------------------------------------------------------------


def test_compare_skip_via_tolerance_returns_skip_diff() -> None:
    diff = compare(1, 1, "number", "n", {"compare": "skip"})
    assert diff is not None
    assert diff.comparator == "skip"


def test_compare_progress_is_dropped() -> None:
    assert compare(1, 1, "progress", "p", {}) is None


def test_compare_unknown_type_returns_none() -> None:
    assert compare(None, None, "alien-type", "k", {}) is None


# --- structural extra cases --------------------------------------------------


def test_compare_kv_extra_key_no_allow() -> None:
    diff = compare_kv("k", "kv", {"a": 1}, {"a": 1, "b": 2}, {})
    assert diff is not None


def test_compare_kv_allow_extra() -> None:
    assert compare_kv("k", "kv", {"a": 1}, {"a": 1, "b": 2}, {"allow_extra": True}) is None


def test_compare_kv_float_tolerance() -> None:
    assert compare_kv("k", "kv", {"a": 1.0}, {"a": 1.0 + 1e-12},
                       {"float_rtol": 1e-6, "float_atol": 1e-9}) is None


def test_compare_tree_id_diff() -> None:
    a = {"id": "root", "children": []}
    b = {"id": "other", "children": []}
    diff = compare_tree("t", "tree", a, b, {})
    assert diff is not None


def test_compare_tree_ordered_children() -> None:
    a = {"id": "r", "children": [{"id": "x", "children": []},
                                  {"id": "y", "children": []}]}
    b = {"id": "r", "children": [{"id": "y", "children": []},
                                  {"id": "x", "children": []}]}
    diff = compare_tree("t", "tree", a, b, {"children_order": "ordered"})
    assert diff is not None
