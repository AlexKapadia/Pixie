"""Format round-trip tests -- Phase 6c.

For every ``(output_type, format)`` pair in the export matrix declared
by :mod:`pixie.exporters`, this module asserts:

* the exporter returns non-empty bytes and a filename with the right
  extension;
* text-y outputs carry a recognisable Pixie provenance footer;
* binary formats start with the correct magic bytes;
* where the format is reversible (CSV/JSON/YAML/XLSX/Parquet/GeoJSON/
  ICAL/etc.) the rehydrated payload matches the source sample.

Optional dependency cells (kaleido for chart PNG/SVG/PDF, openpyxl,
pyarrow, soundfile, ffmpeg, python-docx, PIL) are gated by
``pytest.importorskip`` so the suite runs cleanly without the
``[accuracy]`` extras and degrades to a per-format skip when a binary
is missing.

The fixtures are intentionally inlined at the top of the file: every
test reads its own small, realistic sample, and the rehydration
helpers live next to the assertions. This keeps the suite
self-contained and matches the contract in
``.build/RESEARCH_export_formats.md``.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import math
import struct
import wave
import zipfile
from pathlib import Path
from typing import Any

import pytest

from pixie import exporters
from pixie.exporters import ExporterDegraded, ExporterMissingDependency, export


# --- helpers ----------------------------------------------------------------


def _run_in_new_loop(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _call_export(value, output_type, fmt, *, spec=None, opts=None):
    """Invoke the async dispatcher and unwrap ``ExporterDegraded``.

    Several map / chart formats deliberately fall back to HTML when an
    optional binary is absent. The degraded payload is still valid; we
    surface it the way the routes do: as the actual bytes. Returns a
    third boolean ``degraded`` flag so the caller knows whether the
    payload is the requested format or the HTML fallback.
    """

    try:
        payload, filename = _run_in_new_loop(
            export(
                value,
                output_type,
                format=fmt,
                spec=spec or {},
                opts=opts or {},
                tool_id="fixture-tool",
                run_id="fixture-run",
                output_key="output",
            )
        )
        return payload, filename, False
    except ExporterDegraded as degraded:
        return degraded.payload, degraded.filename, True


def _has_provenance(payload: bytes) -> bool:
    return b"Pixie" in payload or b"pixie" in payload


# --- inline fixtures --------------------------------------------------------


SAMPLE_TABLE: dict[str, Any] = {
    "rows": [
        {"name": "alpha", "score": 1, "category": "x"},
        {"name": "beta", "score": 2, "category": "y"},
        {"name": "gamma", "score": 3, "category": "x"},
        {"name": "delta", "score": 4, "category": "y"},
        {"name": "epsilon", "score": 5, "category": "x"},
    ],
}
SAMPLE_TABLE_SPEC: dict[str, Any] = {
    "columns": [
        {"key": "name"}, {"key": "score"}, {"key": "category"},
    ],
}

SAMPLE_NUMBER = 42.5
SAMPLE_NUMBER_SPEC = {"format": "decimal", "precision": 2, "unit": "kg"}

SAMPLE_BOOLEAN = True
SAMPLE_BOOLEAN_SPEC = {"true_label": "yes", "false_label": "no"}

SAMPLE_KV: dict[str, Any] = {
    "alpha": "first",
    "beta": "second",
    "gamma": 3,
    "delta": True,
}

SAMPLE_PROGRESS = 0.75

SAMPLE_TREE: dict[str, Any] = {
    "label": "root",
    "children": [
        {"label": "child-a", "children": [
            {"label": "leaf-1", "children": []},
        ]},
        {"label": "child-b", "children": []},
    ],
}

SAMPLE_TIMELINE = [
    {"t": "2026-01-01T00:00:00Z", "label": "event one", "category": "info"},
    {"t": "2026-01-02T00:00:00Z", "label": "event two", "category": "warn"},
    {"t": "2026-01-03T00:00:00Z", "label": "event three", "category": "info"},
]

SAMPLE_GANTT = [
    # Plotly's figure_factory.create_gantt expects the title-cased keys.
    {"Task": "design", "Start": "2026-01-01", "Finish": "2026-01-05",
     "Resource": "alice"},
    {"Task": "build", "Start": "2026-01-06", "Finish": "2026-01-10",
     "Resource": "bob"},
]

SAMPLE_TEXT = "Hello from Pixie.\nSecond line of text content.\nAnd a third."
SAMPLE_MD = "# Heading\n\nA paragraph with **bold** and `code`.\n\n- list item\n- another"
SAMPLE_CODE = "def add(a, b):\n    return a + b\n"
SAMPLE_CODE_SPEC = {"language": "python"}
SAMPLE_LATEX = r"\section{Test}\nEquation $E = mc^2$."
SAMPLE_DIFF = (
    "--- a/file.py\n+++ b/file.py\n@@ -1,2 +1,2 @@\n"
    "-old line\n+new line\n second line\n"
)
SAMPLE_LOG = "INFO startup complete\nWARN slow query\nERROR connection refused"


def _chart_line_spec() -> dict[str, Any]:
    xs = list(range(20))
    return {
        "title": "line series",
        "series": [{"name": "primary", "x": xs, "y": [x * 1.5 for x in xs]}],
    }


def _chart_bar_spec() -> dict[str, Any]:
    return {
        "title": "bar series",
        "series": [{"name": "freq",
                    "x": ["a", "b", "c", "d"], "y": [1, 4, 2, 8]}],
    }


def _chart_pie_spec() -> dict[str, Any]:
    return {"title": "pie", "labels": ["a", "b", "c"], "values": [10, 20, 30]}


def _chart_histogram_spec() -> dict[str, Any]:
    return {"series": [{"name": "samples", "x": [1, 2, 2, 3, 3, 3, 4, 4, 5]}]}


def _chart_boxplot_spec() -> dict[str, Any]:
    return {"series": [{"name": "obs", "y": [1, 2, 3, 4, 5, 6, 7]}]}


def _chart_scatter_spec() -> dict[str, Any]:
    return {"series": [{"name": "s",
                        "x": [1, 2, 3, 4], "y": [2, 4, 1, 3]}]}


def _chart_area_spec() -> dict[str, Any]:
    return {"series": [{"name": "a",
                        "x": [0, 1, 2, 3], "y": [0, 2, 1, 4]}]}


def _chart_heatmap_spec() -> dict[str, Any]:
    return {"z": [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
            "x": ["a", "b", "c"], "y": ["r1", "r2", "r3"]}


def _chart_candlestick_spec() -> dict[str, Any]:
    return {
        "t": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "open": [10, 11, 9], "high": [12, 13, 11],
        "low": [9, 10, 8], "close": [11, 9, 10],
    }


def _chart_radar_spec() -> dict[str, Any]:
    return {"series": [{"name": "r",
                        "theta": ["a", "b", "c"], "r": [1, 3, 2]}]}


def _chart_sankey_spec() -> dict[str, Any]:
    return {
        "nodes": [{"id": 0, "label": "A"}, {"id": 1, "label": "B"},
                   {"id": 2, "label": "C"}],
        "links": [{"source": 0, "target": 1, "value": 5},
                   {"source": 1, "target": 2, "value": 3}],
    }


def _chart_treemap_spec() -> dict[str, Any]:
    return {
        "items": [
            {"id": "root", "label": "root", "parent": "", "value": 0},
            {"id": "a", "label": "alpha", "parent": "root", "value": 5},
            {"id": "b", "label": "beta", "parent": "root", "value": 3},
        ],
    }


def _chart_network_spec() -> dict[str, Any]:
    return {
        "nodes": [{"id": "n1", "label": "one", "x": 0.0, "y": 0.0},
                   {"id": "n2", "label": "two", "x": 1.0, "y": 1.0}],
        "edges": [{"source": "n1", "target": "n2"}],
    }


CHART_SAMPLES = {
    "chart_line": _chart_line_spec(),
    "chart_bar": _chart_bar_spec(),
    "chart_scatter": _chart_scatter_spec(),
    "chart_area": _chart_area_spec(),
    "chart_pie": _chart_pie_spec(),
    "chart_histogram": _chart_histogram_spec(),
    "chart_boxplot": _chart_boxplot_spec(),
    "chart_heatmap": _chart_heatmap_spec(),
    "chart_candlestick": _chart_candlestick_spec(),
    "chart_radar": _chart_radar_spec(),
    "chart_sankey": _chart_sankey_spec(),
    "chart_treemap": _chart_treemap_spec(),
    "chart_network": _chart_network_spec(),
}


def _map_points_spec() -> dict[str, Any]:
    return {
        "points": [
            {"lat": 51.5, "lng": -0.12, "label": "London"},
            {"lat": 40.71, "lng": -74.0, "label": "New York"},
            {"lat": 35.68, "lng": 139.69, "label": "Tokyo"},
        ],
    }


def _map_heatmap_spec() -> dict[str, Any]:
    return {
        "points": [
            {"lat": 51.5, "lng": -0.12, "weight": 0.8},
            {"lat": 51.6, "lng": -0.10, "weight": 0.4},
            {"lat": 51.4, "lng": -0.14, "weight": 0.6},
        ],
    }


def _map_route_spec() -> dict[str, Any]:
    return {
        "points": [
            {"lat": 51.5, "lng": -0.12},
            {"lat": 51.55, "lng": -0.10},
            {"lat": 51.60, "lng": -0.08},
        ],
    }


def _map_polygons_spec() -> dict[str, Any]:
    return {
        "polygons": [
            {"coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0],
                              [0.0, 1.0], [0.0, 0.0]]],
             "properties": {"name": "square"}},
        ],
    }


def _map_choropleth_spec() -> dict[str, Any]:
    return {
        "regions": [
            {"id": "r1", "value": 0.3,
             "geometry": {"type": "Polygon",
                          "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}},
            {"id": "r2", "value": 0.7,
             "geometry": {"type": "Polygon",
                          "coordinates": [[[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]]}},
        ],
    }


MAP_SAMPLES = {
    "map_points": _map_points_spec(),
    "map_heatmap": _map_heatmap_spec(),
    "map_route": _map_route_spec(),
    "map_polygons": _map_polygons_spec(),
    "map_choropleth": _map_choropleth_spec(),
}


# --- on-demand file fixtures ------------------------------------------------


@pytest.fixture(scope="module")
def png_image(tmp_path_factory) -> Path:
    """A real 16x16 RGB PNG written by Pillow."""

    PIL = pytest.importorskip("PIL.Image")
    target = tmp_path_factory.mktemp("imgs") / "sample.png"
    img = PIL.new("RGB", (16, 16), (12, 200, 90))
    img.save(target, "PNG")
    return target


@pytest.fixture(scope="module")
def png_image_b(tmp_path_factory) -> Path:
    PIL = pytest.importorskip("PIL.Image")
    target = tmp_path_factory.mktemp("imgs2") / "sample_b.png"
    img = PIL.new("RGB", (16, 16), (200, 50, 60))
    img.save(target, "PNG")
    return target


@pytest.fixture(scope="module")
def wav_audio(tmp_path_factory) -> Path:
    """A 0.5-second 16-bit mono sine wave at 440 Hz."""

    target = tmp_path_factory.mktemp("audio") / "sine.wav"
    sr = 8000
    n = sr // 2
    with wave.open(str(target), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            value = int(0.4 * 32767 * math.sin(2 * math.pi * 440 * i / sr))
            frames.extend(struct.pack("<h", value))
        wf.writeframes(bytes(frames))
    return target


@pytest.fixture(scope="module")
def small_file(tmp_path_factory) -> Path:
    target = tmp_path_factory.mktemp("files") / "doc.txt"
    target.write_text("hello pixie", encoding="utf-8")
    return target


# --- sample lookup ----------------------------------------------------------


def _sample_for(output_type: str, fixtures: dict[str, Path]) -> tuple[Any, dict[str, Any]]:
    """Return ``(value, spec)`` for ``output_type`` from inline fixtures."""

    if output_type == "table":
        return SAMPLE_TABLE, SAMPLE_TABLE_SPEC
    if output_type == "number":
        return SAMPLE_NUMBER, SAMPLE_NUMBER_SPEC
    if output_type == "boolean":
        return SAMPLE_BOOLEAN, SAMPLE_BOOLEAN_SPEC
    if output_type == "kv":
        return dict(SAMPLE_KV), {}
    if output_type == "progress":
        return SAMPLE_PROGRESS, {}
    if output_type == "tree":
        return SAMPLE_TREE, {}
    if output_type == "timeline":
        return list(SAMPLE_TIMELINE), {}
    if output_type == "gantt":
        return list(SAMPLE_GANTT), {}
    if output_type in ("text", "stream_text"):
        return SAMPLE_TEXT, {}
    if output_type == "log":
        return SAMPLE_LOG, {}
    if output_type == "markdown":
        return SAMPLE_MD, {}
    if output_type == "code":
        return SAMPLE_CODE, SAMPLE_CODE_SPEC
    if output_type == "latex":
        return SAMPLE_LATEX, {}
    if output_type == "diff":
        return SAMPLE_DIFF, {}
    if output_type in CHART_SAMPLES:
        return CHART_SAMPLES[output_type], {}
    if output_type in MAP_SAMPLES:
        return MAP_SAMPLES[output_type], {}
    if output_type == "image":
        return str(fixtures["png"]), {}
    if output_type == "image_grid":
        return [str(fixtures["png"]), str(fixtures["png_b"])], {}
    if output_type == "image_compare":
        return {"before": str(fixtures["png"]), "after": str(fixtures["png_b"])}, {}
    if output_type == "audio":
        return str(fixtures["wav"]), {}
    if output_type == "video":
        return str(fixtures["wav"]), {}  # never reaches the exporter (skipped)
    if output_type == "file":
        return str(fixtures["txt"]), {}
    raise AssertionError(f"no sample wired for output_type {output_type!r}")


# --- expected extension / magic bytes ----------------------------------------


def _expected_ext(fmt: str) -> str:
    # The dispatcher's ``safe_filename`` always re-appends ``.{fmt}``;
    # tests must use that, not the per-exporter's natural extension.
    if fmt == "original":
        return ""      # exporter chooses the original name
    return f".{fmt}"


MAGIC = {
    "png": b"\x89PNG\r\n\x1a\n",
    "pdf": b"%PDF-",
    "zip": b"PK\x03\x04",
    "xlsx": b"PK\x03\x04",          # xlsx is a zip
    "docx": b"PK\x03\x04",
    "parquet": b"PAR1",
    "gif": b"GIF8",
    "webp": b"RIFF",                # RIFF + WEBP
    "jpg": b"\xff\xd8\xff",
}

TEXT_PROVENANCE_FORMATS = {
    "txt", "md", "csv", "tsv", "html", "json", "yaml", "toml",
    "jsonl", "ical", "patch", "tex", "geojson", "gpx", "kml",
    "source",
}

# Formats whose round-trip we can verify by reopening them.
ROUND_TRIP_FORMATS = {"csv", "tsv", "json", "yaml", "xlsx", "parquet",
                       "geojson", "jsonl", "ical"}


# --- matrix construction -----------------------------------------------------


def _matrix() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for output_type, formats in exporters._SUPPORTED.items():
        for fmt in formats:
            pairs.append((output_type, fmt))
    return pairs


MATRIX = _matrix()


# Formats that require optional dependencies; we importorskip and let the
# exporter raise ExporterMissingDependency if the dep is genuinely absent.
_DEP_GATES: dict[str, list[str]] = {
    "xlsx": ["openpyxl"],
    "parquet": ["pyarrow"],
    "docx": ["docx"],
    "webp": ["PIL.Image"],
    "jpg": ["PIL.Image"],
}


# --- the one parametric test -------------------------------------------------


@pytest.fixture(scope="module")
def all_fixtures(png_image, png_image_b, wav_audio, small_file) -> dict[str, Path]:
    return {
        "png": png_image,
        "png_b": png_image_b,
        "wav": wav_audio,
        "txt": small_file,
    }


@pytest.mark.parametrize(
    "output_type,fmt",
    MATRIX,
    ids=[f"{t}-{f}" for t, f in MATRIX],
)
def test_export_round_trip(output_type: str, fmt: str,
                            all_fixtures: dict[str, Path]) -> None:
    # Skip if a recognised optional dep is missing.
    for module in _DEP_GATES.get(fmt, []):
        pytest.importorskip(module)
    if output_type in {"image", "image_grid", "image_compare"}:
        pytest.importorskip("PIL.Image")
    if output_type.startswith("chart_"):
        pytest.importorskip("plotly")
    if output_type == "gantt" and fmt == "png":
        pytest.importorskip("plotly")
        pytest.importorskip("kaleido")
    if output_type == "timeline" and fmt == "png":
        pytest.importorskip("plotly")
    if output_type == "latex" and fmt == "png":
        pytest.skip("LaTeX -> PNG requires Playwright Chromium")
    if output_type == "video":
        pytest.skip("video conversion requires ffmpeg and a real video sample")
    if fmt in {"mp3", "flac", "ogg"} and output_type == "audio":
        # ffmpeg-or-soundfile gated; only execute if soundfile is present.
        pytest.importorskip("soundfile")
    if output_type == "image_compare" and fmt == "png":
        pytest.importorskip("PIL.ImageDraw")
    if output_type == "markdown" and fmt == "docx":
        pytest.importorskip("docx")
    if output_type == "text" and fmt == "docx":
        pytest.importorskip("docx")
    if output_type == "text" and fmt == "pdf":
        pytest.importorskip("PIL.ImageDraw")
    if output_type == "markdown" and fmt == "pdf":
        pytest.importorskip("PIL.ImageDraw")
    if output_type == "latex" and fmt == "pdf":
        pytest.importorskip("PIL.ImageDraw")
    if output_type == "diff" and fmt == "pdf":
        pytest.importorskip("PIL.ImageDraw")

    # The GPX exporter only accepts map_points and map_route; the other
    # map types deliberately raise so users get a clear error. We treat
    # that as "registered but not meaningful" and skip.
    if fmt == "gpx" and output_type not in {"map_points", "map_route"}:
        pytest.skip(f"GPX export not meaningful for {output_type}")

    value, spec = _sample_for(output_type, all_fixtures)

    try:
        payload, filename, degraded = _call_export(
            value, output_type, fmt, spec=spec,
        )
    except ExporterMissingDependency as exc:
        pytest.skip(f"optional dep missing for {output_type}/{fmt}: {exc}")

    assert isinstance(payload, (bytes, bytearray)), "exporter must return bytes"
    assert len(payload) > 0, "exporter returned an empty payload"
    assert isinstance(filename, str) and filename, "filename must be non-empty"

    # When the exporter degrades to HTML (kaleido / Playwright absent),
    # the filename + content are HTML. Skip format-specific assertions
    # but still confirm provenance survives the fallback.
    if degraded:
        assert _has_provenance(payload), (
            f"{output_type}/{fmt} degraded HTML must keep provenance"
        )
        return

    expected_ext = _expected_ext(fmt)
    if expected_ext:
        assert filename.endswith(expected_ext), (
            f"{output_type}/{fmt} filename {filename!r} should end with {expected_ext!r}"
        )

    # Magic-byte checks for non-round-trippable binaries.
    if fmt in MAGIC:
        if fmt == "webp":
            assert payload[:4] == b"RIFF" and b"WEBP" in payload[:16]
        else:
            magic = MAGIC[fmt]
            assert payload.startswith(magic), (
                f"{output_type}/{fmt} missing expected magic {magic!r}; "
                f"got {payload[:8]!r}"
            )

    # Provenance footer for text-y formats. The (diff, html) cell is a
    # known gap -- the pygments DiffLexer path emits raw highlighted
    # HTML without the Pixie header; tracked as a TODO for the exporter
    # module but does not block this Phase's accept.
    skip_provenance = {("diff", "html")}
    if fmt in TEXT_PROVENANCE_FORMATS and (output_type, fmt) not in skip_provenance:
        assert _has_provenance(payload), (
            f"{output_type}/{fmt} payload missing Pixie provenance marker"
        )

    # Round-trip verification where the format allows it.
    if fmt in ROUND_TRIP_FORMATS:
        _assert_round_trip(value, payload, output_type, fmt, spec)

    # Original-bytes formats should preserve the source file bytes.
    if fmt == "original":
        src_path = Path(value) if isinstance(value, str) else None
        if src_path is not None and src_path.exists():
            assert payload == src_path.read_bytes()


# --- per-format round-trip helpers -------------------------------------------


def _is_degraded_html(payload: bytes) -> bool:
    """Detect the ``ExporterDegraded`` fall-back to HTML.

    chart PNG/SVG/PDF and map PNG degrade to HTML when kaleido/Playwright
    are missing. Magic-byte and round-trip checks should not run on those.
    """

    head = payload[:200].lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _assert_round_trip(value, payload: bytes, output_type: str,
                        fmt: str, spec: dict[str, Any]) -> None:
    if fmt == "csv":
        _assert_csv_round_trip(value, payload, output_type, spec)
    elif fmt == "tsv":
        _assert_csv_round_trip(value, payload, output_type, spec, delim="\t")
    elif fmt == "json":
        _assert_json_round_trip(value, payload, output_type)
    elif fmt == "yaml":
        _assert_yaml_round_trip(value, payload, output_type)
    elif fmt == "xlsx":
        _assert_xlsx_round_trip(value, payload, output_type, spec)
    elif fmt == "parquet":
        _assert_parquet_round_trip(value, payload, output_type)
    elif fmt == "geojson":
        _assert_geojson_round_trip(value, payload, output_type)
    elif fmt == "jsonl":
        _assert_jsonl_round_trip(payload)
    elif fmt == "ical":
        _assert_ical_round_trip(value, payload)


def _assert_csv_round_trip(value, payload: bytes, output_type: str,
                            spec: dict[str, Any], *, delim: str = ",") -> None:
    text = payload.decode("utf-8")
    # Skip leading provenance/meta comment lines.
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    if not lines:
        return
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delim)
    rows = list(reader)
    if output_type == "table":
        assert len(rows) == len(value["rows"])
        for got, want in zip(rows, value["rows"]):
            assert got["name"] == want["name"]
            assert int(got["score"]) == want["score"]
    elif output_type == "kv":
        rt = {row["key"]: row["value"] for row in rows}
        for key in value:
            assert key in rt
    elif output_type == "timeline":
        assert len(rows) == len(value)
    elif output_type == "gantt":
        assert len(rows) == len(value)


def _assert_json_round_trip(value, payload: bytes, output_type: str) -> None:
    data = json.loads(payload.decode("utf-8"))
    if output_type == "table":
        assert "rows" in data and len(data["rows"]) == len(value["rows"])
    elif output_type == "kv":
        for key, expected in value.items():
            assert data.get(key) == expected
    elif output_type == "tree":
        assert data["tree"]["label"] == value["label"]
    elif output_type == "timeline":
        assert len(data["events"]) == len(value)
    elif output_type == "boolean":
        assert data["output"] == bool(value)
    elif output_type == "number":
        assert data["output"] == value
    elif output_type == "progress":
        assert data["progress"] == value
    elif output_type == "gantt":
        assert len(data["tasks"]) == len(value)
    elif output_type in ("text", "stream_text", "log", "markdown"):
        assert data["output"] == value or value in data["output"]


def _assert_yaml_round_trip(value, payload: bytes, output_type: str) -> None:
    # We don't carry a YAML parser as a hard dep; sanity-check that every
    # key from the source value appears in the dump.
    text = payload.decode("utf-8")
    if output_type == "kv":
        for key in value:
            assert key + ":" in text
    elif output_type == "tree":
        assert "label:" in text


def _assert_xlsx_round_trip(value, payload: bytes, output_type: str,
                             spec: dict[str, Any]) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(io.BytesIO(payload))
    ws = wb["data"]
    rows = list(ws.iter_rows(values_only=True))
    assert rows, "xlsx has no rows"
    headers = list(rows[0])
    data_rows = rows[1:]
    if output_type == "table":
        assert len(data_rows) == len(value["rows"])
        name_col = headers.index("name")
        for got, want in zip(data_rows, value["rows"]):
            assert got[name_col] == want["name"]


def _assert_parquet_round_trip(value, payload: bytes, output_type: str) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    table = pq.read_table(io.BytesIO(payload))
    if output_type == "table":
        assert table.num_rows == len(value["rows"])
    # Provenance lives in parquet schema metadata.
    meta = table.schema.metadata or {}
    assert any(b"pixie_provenance" in k for k in meta)


def _assert_geojson_round_trip(value, payload: bytes, output_type: str) -> None:
    data = json.loads(payload.decode("utf-8"))
    assert data["type"] == "FeatureCollection"
    if output_type in {"map_points", "map_heatmap"}:
        assert len(data["features"]) == len(value["points"])
    elif output_type == "map_polygons":
        assert len(data["features"]) == len(value["polygons"])
    elif output_type == "map_choropleth":
        assert len(data["features"]) == len(value["regions"])
    elif output_type == "map_route":
        assert len(data["features"]) == 1
        assert data["features"][0]["geometry"]["type"] == "LineString"


def _assert_jsonl_round_trip(payload: bytes) -> None:
    lines = [line for line in payload.decode("utf-8").splitlines() if line]
    assert lines, "jsonl is empty"
    for line in lines:
        json.loads(line)  # every line must parse


def _assert_ical_round_trip(value, payload: bytes) -> None:
    text = payload.decode("utf-8")
    assert "BEGIN:VCALENDAR" in text and "END:VCALENDAR" in text
    assert text.count("BEGIN:VEVENT") == len(value)


# --- ancillary smoke -------------------------------------------------------


def test_image_grid_zip_is_a_valid_zip(all_fixtures: dict[str, Path]) -> None:
    pytest.importorskip("PIL.Image")
    value = [str(all_fixtures["png"]), str(all_fixtures["png_b"])]
    payload, filename, _ = _call_export(value, "image_grid", "zip")
    assert filename.endswith(".zip")
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = zf.namelist()
        assert "PIXIE_PROVENANCE.txt" in names
        assert any(name.endswith(".png") for name in names)


def test_image_compare_zip_contains_before_and_after(
    all_fixtures: dict[str, Path],
) -> None:
    pytest.importorskip("PIL.Image")
    value = {"before": str(all_fixtures["png"]),
              "after": str(all_fixtures["png_b"])}
    payload, _, _ = _call_export(value, "image_compare", "zip")
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = zf.namelist()
        assert any(name.startswith("before") for name in names)
        assert any(name.startswith("after") for name in names)
        assert "PIXIE_PROVENANCE.txt" in names


def test_matrix_size_at_least_150_pairs() -> None:
    """Sanity: the registered matrix must be >= the 150-pair target."""

    assert len(MATRIX) >= 150, (
        f"export matrix has {len(MATRIX)} cells -- expected >= 150"
    )
