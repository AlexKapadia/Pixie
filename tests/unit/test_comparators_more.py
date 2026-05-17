"""More comparator gap fillers: table edges, chart scatter points,
file mime branches, media decode edge cases."""

from __future__ import annotations

import base64
import io

import pytest

from pixie.comparators._base import Diff
from pixie.comparators.chart import _compare_one_series, compare_chart
from pixie.comparators.file import compare_file, _file_bytes
from pixie.comparators.map import compare_map, _round_point
from pixie.comparators.media import (
    _decode_image_bytes,
    _ensure_audio_deps,
    _ensure_image_deps,
    compare_audio,
    compare_image,
    compare_image_compare,
    compare_image_grid,
    compare_video,
)
from pixie.comparators.table import (
    _cells_equal,
    _normalise_columns,
    _row_to_dict,
    _sort_key,
    compare_table,
)


# --- table -------------------------------------------------------------


def test_compare_table_non_dict_returns_diff() -> None:
    diff = compare_table("t", "table", [1, 2], {"rows": []}, {})
    assert diff is not None


def test_compare_table_column_names_differ() -> None:
    diff = compare_table(
        "t", "table",
        {"columns": ["a"], "rows": []},
        {"columns": ["b"], "rows": []},
        {},
    )
    assert diff is not None
    assert "column" in (diff.metric or "")


def test_compare_table_row_count_differs() -> None:
    diff = compare_table(
        "t", "table",
        {"columns": ["a"], "rows": [{"a": 1}]},
        {"columns": ["a"], "rows": []},
        {},
    )
    assert diff is not None


def test_compare_table_rows_ordered() -> None:
    a = {"columns": ["a"], "rows": [{"a": 1}, {"a": 2}]}
    b = {"columns": ["a"], "rows": [{"a": 2}, {"a": 1}]}
    diff = compare_table("t", "table", a, b, {"compare": "rows_ordered"})
    assert diff is not None


def test_compare_table_with_list_rows() -> None:
    a = {"columns": ["a", "b"], "rows": [[1, 2]]}
    b = {"columns": ["a", "b"], "rows": [[1, 2]]}
    assert compare_table("t", "table", a, b, {}) is None


def test_compare_table_numeric_mismatch_reports_rtol() -> None:
    diff = compare_table(
        "t", "table",
        {"columns": ["a"], "rows": [{"a": 1.0}]},
        {"columns": ["a"], "rows": [{"a": 2.0}]},
        {"float_rtol": 1e-6, "float_atol": 1e-9},
    )
    assert diff is not None and "rtol_exceeded" in (diff.metric or "")


def test_cells_equal_handles_nan() -> None:
    assert _cells_equal(float("nan"), float("nan"), 1e-6, 1e-9) is True
    assert _cells_equal(float("nan"), 1.0, 1e-6, 1e-9) is False


def test_row_to_dict_from_list() -> None:
    out = _row_to_dict([1, 2], ["a", "b"])
    assert out == {"a": 1, "b": 2}


def test_row_to_dict_from_scalar() -> None:
    out = _row_to_dict(42, ["x"])
    assert out == {"_value": 42}


def test_sort_key_handles_mixed_types() -> None:
    k = _sort_key({"a": None, "b": 1, "c": "x"}, ["a", "b", "c"])
    assert isinstance(k, tuple)


def test_normalise_columns_from_strings() -> None:
    assert _normalise_columns(["a", "b"]) == ["a", "b"]


def test_normalise_columns_from_dicts() -> None:
    assert _normalise_columns([{"key": "a"}, {"label": "B"}]) == ["a", "B"]


def test_normalise_columns_non_list() -> None:
    assert _normalise_columns(None) == []


# --- chart series -----------------------------------------------------


def test_compare_one_series_y_match() -> None:
    assert _compare_one_series({"y": [1.0]}, {"y": [1.0]}, 1e-6, 1e-9) is None


def test_compare_one_series_point_count_diff() -> None:
    out = _compare_one_series({"points": [1, 2]}, {"points": [1]}, 1e-6, 1e-9)
    assert out is not None


def test_compare_one_series_scatter_points_match() -> None:
    a_pts = [{"x": 1.0, "y": 2.0}]
    b_pts = [{"x": 1.0, "y": 2.0}]
    assert _compare_one_series({"points": a_pts}, {"points": b_pts}, 1e-6, 1e-9) is None


def test_compare_chart_data_only_scatter_point_diff() -> None:
    a = {"series": [{"name": "s", "points": [{"x": 1, "y": 1}]}]}
    b = {"series": [{"name": "s", "points": [{"x": 1, "y": 99}]}]}
    diff = compare_chart("c", "chart_scatter", a, b, {"compare": "data_only"})
    assert diff is not None


# --- file mime branches ---------------------------------------------------


def test_file_bytes_dict_no_data_returns_empty() -> None:
    raw, mime = _file_bytes({"mime": "x"})
    assert raw == b""
    assert mime == "x"


def test_file_bytes_repr_for_non_dict() -> None:
    raw, mime = _file_bytes(12345)
    assert raw == b"12345"


def test_file_bytes_string_data_url_invalid_base64() -> None:
    raw, mime = _file_bytes("data:text/plain;base64,not-valid-base64@@@")
    assert isinstance(raw, bytes)


def test_file_csv_mime_dispatch_match() -> None:
    body = b"a,b\n1,2\n"
    payload = {"mime": "text/csv", "data": base64.b64encode(body).decode()}
    assert compare_file("f", "file", payload, payload, {"compare": "mime_dispatch"}) is None


def test_file_unknown_mime_falls_back_to_sha256() -> None:
    a = {"mime": "application/x-weird", "data": base64.b64encode(b"abc").decode()}
    b = {"mime": "application/x-weird", "data": base64.b64encode(b"abc").decode()}
    assert compare_file("f", "file", a, b, {"compare": "mime_dispatch"}) is None


# --- media decode edge cases ---------------------------------------------


def test_decode_image_bytes_from_url_dict_key() -> None:
    out = _decode_image_bytes({"url": "https://example.com/x.png"})
    assert out == b"https://example.com/x.png"


def test_decode_image_bytes_from_value_dict_key() -> None:
    body = base64.b64encode(b"\x89PNG").decode()
    out = _decode_image_bytes({"value": body})
    assert out.startswith(b"\x89")


def test_decode_image_bytes_non_str_returns_repr() -> None:
    out = _decode_image_bytes(12345)
    assert out == b"12345"


def test_compare_image_grid_list_form() -> None:
    body = base64.b64encode(b"\x89PNG").decode()
    payload = [f"data:image/png;base64,{body}"]
    assert compare_image_grid(
        "i", "image_grid", payload, payload, {"compare": "size_sha256"},
    ) is None


def test_compare_image_grid_count_diff() -> None:
    body = base64.b64encode(b"\x89PNG").decode()
    a = [f"data:image/png;base64,{body}"]
    b = []
    diff = compare_image_grid("i", "image_grid", a, b, {"compare": "size_sha256"})
    assert diff is not None


def test_compare_image_grid_not_a_list() -> None:
    diff = compare_image_grid("i", "image_grid", {"images": "x"},
                                {"images": "y"}, {})
    assert diff is not None


def test_compare_image_compare_with_missing_before() -> None:
    body = base64.b64encode(b"\x89PNG").decode()
    payload = {"after": f"data:image/png;base64,{body}"}
    # before missing on one side -> compares the after only
    assert compare_image_compare(
        "i", "image_compare", payload, payload, {"compare": "size_sha256"},
    ) is None


def test_compare_video_per_frame_falls_back_to_sha() -> None:
    body = base64.b64encode(b"video-bytes").decode()
    payload = {"mime": "video/mp4", "data": body}
    out = compare_video("v", "video", payload, payload, {"compare": "per_frame_ssim_mean"})
    assert out is None


def test_compare_audio_with_unknown_mode_uses_fallback() -> None:
    body = base64.b64encode(b"audio").decode()
    payload = {"mime": "audio/wav", "data": body}
    out = compare_audio("a", "audio", payload, payload, {"compare": "size_sha256"})
    assert out is None
