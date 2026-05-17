"""Advanced comparator tests — chart / map / file / image / audio / video.

These hit the per-family modules directly to cover branches that the
top-level dispatcher tests in ``test_comparators.py`` don't reach.
"""

from __future__ import annotations

import base64
import hashlib
import io

import pytest

from pixie.comparators.chart import compare_chart
from pixie.comparators.file import compare_file
from pixie.comparators.map import compare_map
from pixie.comparators.media import (
    compare_audio,
    compare_image,
    compare_image_compare,
    compare_image_grid,
    compare_video,
)


# --- chart -------------------------------------------------------------------


def test_compare_chart_line_data_only_match() -> None:
    expected = {
        "x": [1, 2, 3],
        "series": [{"name": "a", "y": [10, 20, 30]}],
    }
    actual = {
        "x": [1, 2, 3],
        "series": [{"name": "a", "y": [10, 20, 30]}],
    }
    assert compare_chart("c", "chart_line", expected, actual, {}) is None


def test_compare_chart_line_xaxis_mismatch() -> None:
    expected = {"x": [1, 2, 3], "series": [{"name": "a", "y": [1, 2, 3]}]}
    actual = {"x": [1, 2, 4], "series": [{"name": "a", "y": [1, 2, 3]}]}
    diff = compare_chart("c", "chart_line", expected, actual, {})
    assert diff is not None
    assert "x-axis" in diff.metric


def test_compare_chart_line_handles_reordered_series() -> None:
    expected = {
        "x": [1, 2], "series": [
            {"name": "a", "y": [1, 2]},
            {"name": "b", "y": [3, 4]},
        ],
    }
    actual = {
        "x": [1, 2], "series": [
            {"name": "b", "y": [3, 4]},
            {"name": "a", "y": [1, 2]},
        ],
    }
    diff = compare_chart("c", "chart_line", expected, actual, {"series_match": "by_name"})
    assert diff is None


def test_compare_chart_series_count_mismatch() -> None:
    expected = {"x": [1], "series": [{"name": "a", "y": [1]}, {"name": "b", "y": [2]}]}
    actual = {"x": [1], "series": [{"name": "a", "y": [1]}]}
    diff = compare_chart("c", "chart_line", expected, actual, {})
    assert diff is not None
    assert "series count" in diff.metric


def test_compare_chart_skip_mode_returns_none() -> None:
    assert compare_chart("c", "chart_line", {"y": [1]}, {"y": [99]}, {"compare": "skip"}) is None


def test_compare_chart_rejects_non_dict() -> None:
    diff = compare_chart("c", "chart_line", [1, 2], [1, 2], {})
    assert diff is not None and "dict" in diff.metric


def test_compare_chart_pie_slices_unordered() -> None:
    expected = {"slices": [{"label": "a", "value": 30}, {"label": "b", "value": 70}]}
    actual = {"slices": [{"label": "b", "value": 70}, {"label": "a", "value": 30}]}
    diff = compare_chart(
        "c", "chart_pie", expected, actual, {"compare": "slices_unordered"},
    )
    assert diff is None


# --- map ---------------------------------------------------------------------


def test_compare_map_points_match_after_rounding() -> None:
    expected = {"points": [{"lat": 51.5074, "lon": -0.1278}]}
    actual = {"points": [{"lat": 51.5074001, "lon": -0.1278001}]}
    diff = compare_map("m", "map_points", expected, actual, {"round_digits": 4})
    assert diff is None


def test_compare_map_points_count_mismatch() -> None:
    expected = {"points": [{"lat": 1, "lon": 2}]}
    actual = {"points": [{"lat": 1, "lon": 2}, {"lat": 3, "lon": 4}]}
    diff = compare_map("m", "map_points", expected, actual, {})
    assert diff is not None
    assert "point count" in diff.metric


def test_compare_map_skip_returns_none() -> None:
    diff = compare_map(
        "m", "map_points", {"points": [{"lat": 1, "lon": 2}]},
        {"points": []}, {"compare": "skip"},
    )
    assert diff is None


def test_compare_map_rejects_non_dict() -> None:
    diff = compare_map("m", "map_points", "x", "y", {})
    assert diff is not None


def test_compare_map_unknown_type_flags_unsupported() -> None:
    diff = compare_map("m", "map_unknown_subtype", {}, {}, {})
    assert diff is not None
    assert "unsupported" in diff.metric


# --- file --------------------------------------------------------------------


def test_compare_file_sha256_match_bytes() -> None:
    e = {"mime": "application/octet-stream", "data": b"hello"}
    a = {"mime": "application/octet-stream", "data": b"hello"}
    assert compare_file("f", "file", e, a, {"compare": "sha256"}) is None


def test_compare_file_sha256_mismatch_bytes() -> None:
    e = {"mime": "application/octet-stream", "data": b"hello"}
    a = {"mime": "application/octet-stream", "data": b"world"}
    diff = compare_file("f", "file", e, a, {"compare": "sha256"})
    assert diff is not None
    assert "sha256 differs" in diff.metric


def test_compare_file_json_normalises_key_order() -> None:
    e = {"mime": "application/json", "data": b'{"a":1,"b":2}'}
    a = {"mime": "application/json", "data": b'{"b":2,"a":1}'}
    assert compare_file("f", "file", e, a, {}) is None


def test_compare_file_data_url_decoded() -> None:
    e = "data:text/plain;base64," + base64.b64encode(b"hi").decode()
    a = "data:text/plain;base64," + base64.b64encode(b"hi").decode()
    assert compare_file("f", "file", e, a, {"compare": "sha256"}) is None


def test_compare_file_skip_returns_none() -> None:
    e = {"mime": "any", "data": b"a"}
    a = {"mime": "any", "data": b"b"}
    assert compare_file("f", "file", e, a, {"compare": "skip"}) is None


# --- image (degraded path) ---------------------------------------------------


def test_compare_image_size_sha256_mode_uses_fallback() -> None:
    # Force the size_sha256 path; identical bytes match.
    payload = base64.b64encode(b"\x89PNG-tiny-fake").decode()
    e = {"mime": "image/png", "data": payload}
    a = {"mime": "image/png", "data": payload}
    assert compare_image("i", "image", e, a, {"compare": "size_sha256"}) is None


def test_compare_image_size_sha256_mode_flags_mismatch() -> None:
    e = {"mime": "image/png", "data": base64.b64encode(b"a").decode()}
    a = {"mime": "image/png", "data": base64.b64encode(b"b").decode()}
    diff = compare_image("i", "image", e, a, {"compare": "size_sha256"})
    assert diff is not None
    assert "sha256 differs" in diff.metric


def test_compare_image_grid_count_mismatch() -> None:
    e = {"images": [{"data": "x", "mime": "image/png"}]}
    a = {"images": []}
    diff = compare_image_grid("g", "image_grid", e, a, {})
    assert diff is not None


def test_compare_image_grid_non_list_rejected() -> None:
    diff = compare_image_grid("g", "image_grid", "x", "y", {})
    assert diff is not None


def test_compare_image_compare_calls_per_side() -> None:
    e = {
        "before": {"mime": "image/png", "data": base64.b64encode(b"a").decode()},
        "after": {"mime": "image/png", "data": base64.b64encode(b"b").decode()},
    }
    a = {
        "before": {"mime": "image/png", "data": base64.b64encode(b"a").decode()},
        "after": {"mime": "image/png", "data": base64.b64encode(b"b").decode()},
    }
    # Use the degraded path so we don't need skimage.
    diff = compare_image_compare("ic", "image_compare", e, a, {"compare": "size_sha256"})
    assert diff is None


# --- audio + video skip mode ------------------------------------------------


def test_compare_audio_skip_returns_none() -> None:
    assert compare_audio("a", "audio", {"data": "x"}, {"data": "y"}, {"compare": "skip"}) is None


def test_compare_video_skip_returns_none() -> None:
    assert compare_video("v", "video", {"data": "x"}, {"data": "y"}, {"compare": "skip"}) is None


def test_compare_audio_size_sha256_match() -> None:
    e = {"mime": "audio/wav", "data": base64.b64encode(b"WAV-FAKE").decode()}
    a = {"mime": "audio/wav", "data": base64.b64encode(b"WAV-FAKE").decode()}
    assert compare_audio("a", "audio", e, a, {"compare": "size_sha256"}) is None


def test_compare_video_size_sha256_mismatch() -> None:
    e = {"mime": "video/mp4", "data": base64.b64encode(b"MP4-X").decode()}
    a = {"mime": "video/mp4", "data": base64.b64encode(b"MP4-Y").decode()}
    diff = compare_video("v", "video", e, a, {"compare": "size_sha256"})
    assert diff is not None
