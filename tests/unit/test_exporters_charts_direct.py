"""Direct tests for chart figure building (kaleido-free).

The chart exporters use Plotly to construct a Figure server-side and
then call kaleido for PNG/SVG/PDF. Kaleido isn't a hard dep, so the
PNG paths degrade to HTML via ExporterDegraded. These tests exercise
the figure-building code directly so per-chart-type branches are
covered without needing kaleido.
"""

from __future__ import annotations

import pytest

from pixie.exporters.charts import (
    CHART_TYPES,
    _figure_for,
    _network_nodes_edges,
    _plot_network,
)


def _spec(chart_type: str) -> dict:
    if chart_type in {"chart_line", "chart_bar", "chart_scatter", "chart_area"}:
        return {"title": "T", "x": [1, 2, 3],
                 "series": [{"name": "a", "y": [1, 2, 3]}]}
    if chart_type == "chart_pie":
        return {"labels": ["a", "b"], "values": [3, 5]}
    if chart_type == "chart_histogram":
        return {"series": [{"name": "h", "values": [1, 1, 2]}]}
    if chart_type == "chart_boxplot":
        return {"series": [{"name": "b", "values": [1, 2, 3]}]}
    if chart_type == "chart_heatmap":
        return {"z": [[1, 2], [3, 4]], "x": ["a", "b"], "y": ["r1", "r2"]}
    if chart_type == "chart_candlestick":
        return {"t": ["a", "b"], "open": [1, 2], "high": [3, 4],
                 "low": [0, 1], "close": [2, 3]}
    if chart_type == "chart_radar":
        return {"axes": ["a", "b"], "series": [{"name": "r", "values": [1, 2]}]}
    if chart_type == "chart_sankey":
        return {"nodes": [{"id": 0, "label": "A"}, {"id": 1, "label": "B"}],
                 "links": [{"source": 0, "target": 1, "value": 5}]}
    if chart_type == "chart_treemap":
        return {"items": [{"id": "r", "label": "r", "value": 0}]}
    if chart_type == "chart_network":
        return {"nodes": [{"id": "a", "label": "A", "x": 0.0, "y": 0.0},
                           {"id": "b", "label": "B", "x": 1.0, "y": 1.0}],
                 "edges": [{"source": "a", "target": "b"}]}
    return {}


@pytest.mark.parametrize("chart_type", CHART_TYPES)
def test_figure_for_returns_figure(chart_type: str) -> None:
    import plotly.graph_objects as go
    fig = _figure_for(_spec(chart_type), chart_type)
    assert isinstance(fig, go.Figure)


def test_network_nodes_edges_with_coords() -> None:
    spec = {
        "nodes": [{"id": "a", "x": 0.0, "y": 0.0}, {"id": "b", "x": 1.0, "y": 1.0}],
        "edges": [{"source": "a", "target": "b"}],
    }
    nodes, edges = _network_nodes_edges(spec)
    assert len(nodes) == 2 and len(edges) == 1


def test_network_nodes_edges_without_coords_uses_networkx() -> None:
    spec = {
        "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        "edges": [{"source": "a", "target": "b"}],
    }
    nodes, _ = _network_nodes_edges(spec)
    # spring_layout populates x,y
    assert "x" in nodes[0] and "y" in nodes[0]


def test_plot_network_returns_figure() -> None:
    import plotly.graph_objects as go
    nodes = [{"id": "a", "label": "A", "x": 0.0, "y": 0.0},
              {"id": "b", "label": "B", "x": 1.0, "y": 1.0}]
    edges = [{"source": "a", "target": "b"}]
    fig = _plot_network(nodes, edges, go)
    assert isinstance(fig, go.Figure)


def test_figure_for_unknown_chart_raises() -> None:
    from pixie.exporters import ExporterError
    with pytest.raises(ExporterError):
        _figure_for({}, "chart_alien")
