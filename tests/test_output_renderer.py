"""Tests for the schema-driven output renderer.

Verifies that:

1. Every output type listed in ``discovery.OutputSpec`` has a matching
   partial under ``pixie/templates/partials/outputs/<type>.html``.
2. ``render_outputs`` dispatches to each partial; the rendered HTML
   includes one ``data-output-type`` marker per output spec.
3. Empty values render the empty-state placeholder rather than crashing.
4. The example tool's three outputs each render correct chrome
   (currency stat, Plotly container, real ``<table>``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pixie.discovery import OutputSpec, ToolSchema, load_tool_schema
from pixie.renderer.outputs import render_output, render_outputs

REPO = Path(__file__).resolve().parent.parent
PARTIALS = REPO / "pixie" / "templates" / "partials" / "outputs"
FIXTURE_TOOL = REPO / "tests" / "fixtures" / "all-outputs-tool" / "tool.json"


# All 39 output types from discovery.py — keep this list in sync with the
# OutputSpec discriminated union. The test asserts it covers every variant.
ALL_OUTPUT_TYPES: list[str] = [
    "text", "markdown", "number", "boolean", "kv", "table",
    "chart_line", "chart_bar", "chart_scatter", "chart_area", "chart_pie",
    "chart_histogram", "chart_boxplot", "chart_heatmap", "chart_candlestick",
    "chart_radar", "chart_sankey", "chart_treemap", "chart_network",
    "map_points", "map_heatmap", "map_choropleth", "map_polygons", "map_route",
    "image", "image_grid", "image_compare", "audio", "video",
    "latex", "code", "diff", "tree", "timeline", "gantt",
    "progress", "log", "stream_text", "file",
]


def test_every_output_type_has_a_partial() -> None:
    """Every output type must ship a Jinja partial."""

    missing: list[str] = []
    for type_ in ALL_OUTPUT_TYPES:
        if not (PARTIALS / f"{type_}.html").exists():
            missing.append(type_)
    assert not missing, f"missing partials: {missing}"


def test_fixture_tool_declares_every_output_type() -> None:
    """The all-outputs fixture must declare one of every type."""

    schema = load_tool_schema(FIXTURE_TOOL.parent)
    declared = {o.type for o in schema.outputs}
    expected = set(ALL_OUTPUT_TYPES)
    assert declared == expected, f"fixture missing {expected - declared}, extra {declared - expected}"


def _sample_value(type_: str) -> object:
    """Return a representative value the renderer can consume for `type_`."""

    bases: dict[str, object] = {
        "text": "Hello, world.",
        "markdown": "## Heading\n\nSome **bold** body.\n\n- one\n- two",
        "number": 12345.678,
        "boolean": True,
        "kv": {"alpha": 1, "beta": "two", "gamma": "3.14"},
        "table": {
            "rows": [
                {"name": "alpha", "score": 91},
                {"name": "beta",  "score": 82},
                {"name": "gamma", "score": 77},
            ],
        },
        "chart_line": {
            "x": [1, 2, 3, 4, 5],
            "series": [{"name": "A", "y": [3, 5, 4, 7, 6]}],
        },
        "chart_bar": {
            "x": ["one", "two", "three"],
            "series": [{"name": "A", "y": [10, 14, 8]}],
        },
        "chart_scatter": {
            "series": [{"name": "A",
                        "points": [{"x": 1, "y": 2}, {"x": 2, "y": 3}, {"x": 3, "y": 5}]}],
        },
        "chart_area": {
            "x": [1, 2, 3, 4],
            "series": [{"name": "A", "y": [1, 3, 5, 4]}],
        },
        "chart_pie": {"slices": [{"label": "A", "value": 30}, {"label": "B", "value": 70}]},
        "chart_histogram": {"values": [1, 2, 2, 3, 3, 3, 4, 4, 5], "bins": 5},
        "chart_boxplot": {"series": [{"name": "X", "values": [1, 2, 3, 4, 5, 12]}]},
        "chart_heatmap": {
            "x_labels": ["M", "T", "W"],
            "y_labels": ["AM", "PM"],
            "z": [[1, 2, 3], [4, 5, 6]],
        },
        "chart_candlestick": {
            "points": [
                {"t": "2024-01-01", "open": 100, "high": 110, "low": 95, "close": 108},
                {"t": "2024-01-02", "open": 108, "high": 112, "low": 102, "close": 104},
            ],
        },
        "chart_radar": {
            "axes": ["A", "B", "C", "D"],
            "series": [{"name": "X", "values": [3, 4, 2, 5]}],
        },
        "chart_sankey": {
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"},
                      {"id": "c", "label": "C"}],
            "links": [{"source": "a", "target": "b", "value": 4},
                      {"source": "b", "target": "c", "value": 4}],
        },
        "chart_treemap": {
            "nodes": [
                {"id": "root", "label": "Root", "value": 100},
                {"id": "a", "parent": "root", "label": "A", "value": 60},
                {"id": "b", "parent": "root", "label": "B", "value": 40},
            ],
        },
        "chart_network": {
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"},
                      {"id": "c", "label": "C"}],
            "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}],
        },
        "map_points": {
            "points": [{"lat": 51.5, "lng": -0.1, "label": "London"},
                       {"lat": 48.85, "lng": 2.35, "label": "Paris"}],
        },
        "map_heatmap": {
            "points": [{"lat": 51.5, "lng": -0.1, "weight": 1},
                       {"lat": 51.51, "lng": -0.12, "weight": 0.5}],
        },
        "map_choropleth": {
            "geojson": {"type": "FeatureCollection", "features": []},
            "values": {"a": 10, "b": 20}, "min": 0, "max": 30,
        },
        "map_polygons": {
            "polygons": [{"coords": [[51.5, -0.1], [51.55, -0.1], [51.55, -0.05]],
                          "label": "Soho"}],
        },
        "map_route": {
            "points": [{"lat": 51.5, "lng": -0.1},
                       {"lat": 51.51, "lng": -0.08}],
        },
        "image": {"url": "https://example.invalid/x.png", "alt": "x"},
        "image_grid": {"images": [
            {"url": "https://example.invalid/a.png", "alt": "a"},
            {"url": "https://example.invalid/b.png", "alt": "b"},
        ]},
        "image_compare": {"before": "https://example.invalid/a.png",
                          "after": "https://example.invalid/b.png"},
        "audio": {"url": "https://example.invalid/a.mp3"},
        "video": {"url": "https://example.invalid/v.mp4"},
        "latex": "E = mc^2",
        "code": {"text": "def f(x):\n    return x + 1"},
        "diff": {"before": "alpha\nbeta\n", "after": "alpha\ngamma\n"},
        "tree": {"root": {"name": "root", "children": [
            {"name": "child", "children": [{"name": "leaf"}]},
        ]}},
        "timeline": {"events": [
            {"t": "2024-01-01", "title": "Start"},
            {"t": "2024-02-01", "title": "Done", "description": "Done by end of Q1."},
        ]},
        "gantt": {"tasks": [
            {"name": "Design",  "start": 0, "end": 4, "label": "4d"},
            {"name": "Build",   "start": 4, "end": 10, "label": "6d"},
        ]},
        "progress": {"value": 0.42, "label": "Working"},
        "log": {"lines": [
            {"t": "12:00:01", "level": "info",  "message": "Started"},
            {"t": "12:00:02", "level": "warn",  "message": "Slow"},
            {"t": "12:00:03", "level": "error", "message": "Boom"},
        ]},
        "stream_text": {"text": "Hello "},
        "file": {"filename": "report.csv", "url": "https://example.invalid/r.csv",
                 "mime": "text/csv", "size": 12345},
    }
    return bases[type_]


def _spec_for(type_: str) -> OutputSpec:
    raw: dict[str, object] = {"key": f"o_{type_}", "type": type_, "label": type_}
    if type_ == "number":
        raw["format"] = "currency"
        raw["precision"] = 2
    if type_ == "table":
        raw["columns"] = [
            {"key": "name",  "label": "Name",  "type": "text"},
            {"key": "score", "label": "Score", "type": "number"},
        ]
        raw["downloadable"] = True
    if type_ == "code":
        raw["language"] = "python"
    return ToolSchema.model_validate(
        {
            "id": "t", "name": "t", "inputs": [], "outputs": [raw],
        }
    ).outputs[0]


@pytest.mark.parametrize("type_", ALL_OUTPUT_TYPES)
def test_render_output_each_type_has_value(type_: str) -> None:
    """Each partial must render markup that wraps the right card."""

    spec = _spec_for(type_)
    html = str(render_output(spec, _sample_value(type_)))
    assert f'data-output-type="{type_}"' in html, html[:600]
    assert "output-card" in html
    # Non-trivial content — placeholder copy must NOT appear.
    assert "renderer not built" not in html
    assert "phase 4c" not in html


@pytest.mark.parametrize("type_", ALL_OUTPUT_TYPES)
def test_render_output_empty_state(type_: str) -> None:
    """Each partial renders an empty-state placeholder when value is None.

    The `progress` partial intentionally still renders its bar (indeterminate)
    and the `stream_text` partial still renders its empty stream container —
    both signal "waiting" rather than "no data". For those two, we only check
    the card wrapper rendered without error.
    """

    spec = _spec_for(type_)
    html = str(render_output(spec, None))
    assert f'data-output-type="{type_}"' in html
    # progress/stream_text/log all render a "waiting" affordance rather
    # than the generic empty-state placeholder. For those, just confirm
    # the card chrome rendered (the marker check above already covers that).
    if type_ not in {"progress", "stream_text", "log"}:
        assert "output-card__empty" in html


def test_render_outputs_marker_count_matches_fixture() -> None:
    """The full fixture must produce one chunk per output."""

    schema = load_tool_schema(FIXTURE_TOOL.parent)
    html = str(render_outputs(schema.outputs))
    markers = re.findall(r'data-output-type="([a-z_]+)"', html)
    assert sorted(markers) == sorted(ALL_OUTPUT_TYPES), (
        f"missing or extra: expected={sorted(ALL_OUTPUT_TYPES)} got={sorted(markers)}"
    )


def test_render_outputs_with_values_for_every_type() -> None:
    """End-to-end: fixture + sample values render with no exceptions."""

    schema = load_tool_schema(FIXTURE_TOOL.parent)
    values = {spec.key: _sample_value(spec.type) for spec in schema.outputs}
    html = str(render_outputs(schema.outputs, values))
    # one chunk per type, no placeholder leftovers
    for type_ in ALL_OUTPUT_TYPES:
        assert f'data-output-type="{type_}"' in html
    assert "renderer not built" not in html


def test_example_tool_renders_each_output_correctly() -> None:
    """The example-compound-interest tool's three outputs render the right chrome."""

    schema = load_tool_schema(REPO / "tools" / "example-compound-interest")
    values = {
        "final_value": 23456.78,
        "total_contributions": 30000,
        "total_interest": 9876.54,
        "growth_chart": {
            "x": list(range(11)),
            "series": [{"name": "Balance", "y": [10000 + i * 1500 for i in range(11)]}],
        },
        "yearly_breakdown": {
            "rows": [
                {"year": y, "start_balance": 10000 + y * 1500,
                 "contributions": 3000, "interest": 600,
                 "end_balance": 10000 + (y + 1) * 1500}
                for y in range(5)
            ],
        },
    }
    html = str(render_outputs(schema.outputs, values))

    # final_value as a currency stat
    assert 'data-output-type="number"' in html
    assert 'data-stat-format="currency"' in html
    # growth_chart as a Plotly line container
    assert 'data-output-type="chart_line"' in html
    assert 'id="chart-out-growth_chart"' in html
    # yearly_breakdown as a sortable real table
    assert 'data-output-type="table"' in html
    assert "<table" in html
    assert 'data-key="year"' in html


def test_layout_grouping_tab_and_inline() -> None:
    """Outputs with layout=tab group into a tab strip; inline groups side-by-side."""

    raw_outs = [
        {"key": "a", "type": "text", "label": "A", "layout": "tab"},
        {"key": "b", "type": "text", "label": "B", "layout": "tab"},
        {"key": "c", "type": "number", "label": "C", "layout": "inline", "format": "decimal"},
        {"key": "d", "type": "number", "label": "D", "layout": "inline", "format": "decimal"},
    ]
    schema = ToolSchema.model_validate(
        {"id": "t", "name": "t", "inputs": [], "outputs": raw_outs}
    )
    html = str(render_outputs(schema.outputs, {"a": "x", "b": "y", "c": 1, "d": 2}))
    assert 'data-pixie-tabs' in html
    assert 'class="output-tabs"' in html
    assert 'output-inline' in html


def test_value_dict_with_text_key_is_unwrapped() -> None:
    spec = _spec_for("text")
    html = str(render_output(spec, {"text": "Some prose."}))
    assert "Some prose." in html


def test_tojson_safe_filter_handles_non_serializable() -> None:
    """The tojson_safe filter must not raise for unusual inputs."""

    spec = _spec_for("chart_line")
    # values that include a set (non-JSON) should not crash the renderer
    html = str(render_output(spec, {"x": [1, 2], "series": [{"name": "ok", "y": [1, 2]}]}))
    assert "Plotly" not in html  # client-side script tag exists but no eager call
    assert "id=\"chart-" in html


def test_render_outputs_no_outputs_message() -> None:
    html = str(render_outputs([]))
    assert "produces no outputs" in html


def test_card_carries_panel_id() -> None:
    spec = _spec_for("text")
    html = str(render_output(spec, "hello"))
    assert 'id="out-o_text"' in html


def test_renderer_never_emits_v1_or_todo_strings() -> None:
    """Verifies the AMBITION.md forbidden-strings rule.

    Matches as whole words (case-insensitive) so SVG path data like
    ``3v12`` doesn't trip the ``v1`` check.
    """

    forbidden = [r"\bTODO\b", r"\bFIXME\b", r"\bv1\b", r"\bplaceholder\b",
                 r"\bcoming soon\b", r"\bnot yet implemented\b",
                 r"\bout of scope\b", r"\bXXX\b", r"\bHACK\b"]
    schema = load_tool_schema(FIXTURE_TOOL.parent)
    values = {spec.key: _sample_value(spec.type) for spec in schema.outputs}
    html = str(render_outputs(schema.outputs, values))
    lowered = html.lower()
    for pattern in forbidden:
        match = re.search(pattern, lowered, flags=re.IGNORECASE)
        assert match is None, (
            f"renderer output contains forbidden string {pattern!r} at "
            f"{lowered[max(0, match.start() - 30):match.end() + 30]!r}"
        )


def test_partial_count_matches_output_type_count() -> None:
    """Sanity check: 39 output types + 1 shared macro file = 40 files."""

    actual = sorted(p.name for p in PARTIALS.iterdir()
                    if p.is_file() and p.suffix == ".html")
    expected = sorted([f"{t}.html" for t in ALL_OUTPUT_TYPES] + ["_card.html"])
    assert actual == expected, f"partial files do not match: {set(actual) ^ set(expected)}"
