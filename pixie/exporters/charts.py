"""Exporters for all 13 chart_* output types.

PNG / SVG / PDF via kaleido (lazy import). HTML via Plotly self-contained.
JSON dumps the spec verbatim. CSV uses per-type flatteners so the output
is analysis-ready.

If kaleido is missing we degrade to interactive HTML and surface a clear
message via :class:`ExporterDegraded`.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Iterable

from pixie.exporters import (
    ExporterError,
    ExporterMissingDependency,
    register_exporter,
)
from pixie.exporters._common import coerce_value, csv_scalar, json_default


CHART_TYPES = (
    "chart_line", "chart_bar", "chart_scatter", "chart_area", "chart_pie",
    "chart_histogram", "chart_boxplot", "chart_heatmap", "chart_candlestick",
    "chart_radar", "chart_sankey", "chart_treemap", "chart_network",
)


# --- spec -> Plotly figure ---------------------------------------------------


def _figure_for(spec_data: dict[str, Any], chart_type: str):
    """Build a Plotly Figure server-side. Mirrors RESEARCH_frontend §1.5."""

    try:
        import plotly.graph_objects as go  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ExporterMissingDependency(
            "plotly is required for chart static exports",
            hint="run `uv add plotly`",
        ) from exc
    series = spec_data.get("series") or []
    x_axis = spec_data.get("x") or spec_data.get("labels") or []
    fig = go.Figure()
    if chart_type in ("chart_line", "chart_area"):
        for s in series:
            fig.add_trace(go.Scatter(
                x=s.get("x") or x_axis,
                y=s.get("y") or [],
                name=s.get("name") or "",
                mode="lines+markers",
                fill="tozeroy" if chart_type == "chart_area" else None,
            ))
    elif chart_type == "chart_bar":
        for s in series:
            fig.add_trace(go.Bar(
                x=s.get("x") or x_axis,
                y=s.get("y") or [],
                name=s.get("name") or "",
            ))
    elif chart_type == "chart_scatter":
        for s in series:
            fig.add_trace(go.Scatter(
                x=s.get("x") or x_axis,
                y=s.get("y") or [],
                mode="markers",
                name=s.get("name") or "",
            ))
    elif chart_type == "chart_pie":
        labels = spec_data.get("labels") or []
        values = spec_data.get("values") or []
        fig.add_trace(go.Pie(labels=labels, values=values))
    elif chart_type == "chart_histogram":
        for s in series:
            fig.add_trace(go.Histogram(x=s.get("x") or s.get("values") or [], name=s.get("name") or ""))
    elif chart_type == "chart_boxplot":
        for s in series:
            fig.add_trace(go.Box(y=s.get("y") or s.get("values") or [], name=s.get("name") or ""))
    elif chart_type == "chart_heatmap":
        z = spec_data.get("z") or []
        fig.add_trace(go.Heatmap(z=z, x=spec_data.get("x"), y=spec_data.get("y")))
    elif chart_type == "chart_candlestick":
        fig.add_trace(go.Candlestick(
            x=spec_data.get("t") or x_axis,
            open=spec_data.get("open") or [],
            high=spec_data.get("high") or [],
            low=spec_data.get("low") or [],
            close=spec_data.get("close") or [],
        ))
    elif chart_type == "chart_radar":
        for s in series:
            fig.add_trace(go.Scatterpolar(
                r=s.get("r") or s.get("values") or [],
                theta=s.get("theta") or spec_data.get("axes") or [],
                name=s.get("name") or "", fill="toself",
            ))
    elif chart_type == "chart_sankey":
        nodes = spec_data.get("nodes") or []
        links = spec_data.get("links") or []
        fig.add_trace(go.Sankey(
            node=dict(label=[n.get("label", "") for n in nodes]),
            link=dict(
                source=[l.get("source", 0) for l in links],
                target=[l.get("target", 0) for l in links],
                value=[l.get("value", 0) for l in links],
            ),
        ))
    elif chart_type == "chart_treemap":
        items = spec_data.get("items") or []
        fig.add_trace(go.Treemap(
            ids=[i.get("id") for i in items],
            labels=[i.get("label") for i in items],
            parents=[i.get("parent", "") for i in items],
            values=[i.get("value", 0) for i in items],
        ))
    elif chart_type == "chart_network":
        nodes, edges = _network_nodes_edges(spec_data)
        fig = _plot_network(nodes, edges, go)
    else:  # pragma: no cover -- safety net
        raise ExporterError(f"unknown chart type {chart_type!r}")

    title = spec_data.get("title") or ""
    fig.update_layout(
        title=title,
        margin=dict(l=40, r=20, t=40 if title else 20, b=40),
        showlegend=len(series) > 1,
    )
    return fig


def _network_nodes_edges(spec_data):
    nodes = spec_data.get("nodes") or []
    edges = spec_data.get("edges") or spec_data.get("links") or []
    has_coords = nodes and all(("x" in n and "y" in n) for n in nodes)
    if not has_coords:
        try:
            import networkx as nx  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ExporterMissingDependency(
                "chart_network without x,y coordinates requires networkx",
                hint="run `uv add networkx`",
            ) from exc
        graph = nx.Graph()
        for node in nodes:
            graph.add_node(node.get("id"))
        for edge in edges:
            graph.add_edge(edge.get("source"), edge.get("target"))
        layout = nx.spring_layout(graph, seed=42)
        for node in nodes:
            x, y = layout.get(node.get("id"), (0.0, 0.0))
            node["x"] = float(x); node["y"] = float(y)
    return nodes, edges


def _plot_network(nodes, edges, go):
    by_id = {n.get("id"): n for n in nodes}
    edge_x, edge_y = [], []
    for edge in edges:
        s = by_id.get(edge.get("source")); t = by_id.get(edge.get("target"))
        if not s or not t: continue
        edge_x += [s.get("x"), t.get("x"), None]
        edge_y += [s.get("y"), t.get("y"), None]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=1, color="#9aa0a6"), hoverinfo="none",
    ))
    fig.add_trace(go.Scatter(
        x=[n.get("x") for n in nodes],
        y=[n.get("y") for n in nodes],
        mode="markers+text",
        text=[n.get("label", str(n.get("id"))) for n in nodes],
        textposition="top center",
        marker=dict(size=12, color="#3b82f6"),
    ))
    fig.update_layout(
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        showlegend=False,
    )
    return fig


# --- exporters ---------------------------------------------------------------


def _to_static(raw, *, prov, output_key, spec, chart_type, fmt) -> tuple[bytes, str]:
    spec_data = coerce_value(raw) or {}
    if not isinstance(spec_data, dict):
        spec_data = {"value": spec_data}
    try:
        fig = _figure_for(spec_data, chart_type)
    except ExporterMissingDependency:
        raise
    try:
        import plotly.io as pio  # type: ignore[import-not-found]
        payload = pio.to_image(
            fig, format=fmt, width=1280, height=720, scale=2, engine="kaleido",
        )
    except (ImportError, ValueError) as exc:
        # kaleido missing or chrome bootstrap failed -- fall back to HTML.
        html_bytes, html_name = _to_html(
            raw, prov=prov, output_key=output_key, spec=spec, chart_type=chart_type,
        )
        from pixie.exporters import ExporterDegraded
        raise ExporterDegraded(
            "static chart export needs kaleido; exported as interactive HTML instead",
            payload=html_bytes, filename=html_name, actual_format="html",
            hint="run `uv add kaleido==0.2.1` (and ensure Chromium is allowed)",
        ) from exc
    return payload, f"{output_key}.{fmt}"


def _to_html(raw, *, prov, output_key, spec, chart_type, **_) -> tuple[bytes, str]:
    spec_data = coerce_value(raw) or {}
    fig = _figure_for(spec_data if isinstance(spec_data, dict) else {}, chart_type)
    import plotly.io as pio  # type: ignore[import-not-found]
    html = pio.to_html(fig, full_html=True, include_plotlyjs="cdn",
                       config={"responsive": True, "displaylogo": False})
    inject = f'<meta name="pixie-provenance" content="{prov}">'
    html = html.replace("<head>", "<head>" + inject, 1)
    return html.encode("utf-8"), f"{output_key}.html"


def _to_json(raw, *, prov, output_key, spec, chart_type, **_) -> tuple[bytes, str]:
    payload = {
        "chart_type": chart_type,
        "spec": coerce_value(raw),
        "_pixie_provenance": prov,
    }
    return json.dumps(payload, indent=2, default=json_default).encode("utf-8"), f"{output_key}.json"


def _to_csv(raw, *, prov, output_key, spec, chart_type, **_) -> tuple[bytes, str]:
    spec_data = coerce_value(raw) or {}
    rows = list(_flatten_chart(spec_data, chart_type))
    columns = list(rows[0].keys()) if rows else ["value"]
    buf = io.StringIO()
    buf.write(f"# {prov}\n")
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: csv_scalar(row.get(c)) for c in columns})
    return buf.getvalue().encode("utf-8"), f"{output_key}.csv"


def _flatten_chart(spec_data: dict[str, Any], chart_type: str) -> Iterable[dict[str, Any]]:
    if chart_type in ("chart_line", "chart_area", "chart_scatter", "chart_bar"):
        x_axis = spec_data.get("x") or spec_data.get("labels") or []
        for s in spec_data.get("series") or []:
            name = s.get("name", "")
            xs = s.get("x") or x_axis
            ys = s.get("y") or []
            for x, y in zip(xs, ys):
                yield {"series": name, "x": x, "y": y}
    elif chart_type == "chart_pie":
        labels = spec_data.get("labels") or []
        values = spec_data.get("values") or []
        for l, v in zip(labels, values):
            yield {"label": l, "value": v}
    elif chart_type == "chart_histogram":
        for s in spec_data.get("series") or []:
            name = s.get("name", "")
            for value in s.get("x") or s.get("values") or []:
                yield {"series": name, "value": value}
    elif chart_type == "chart_boxplot":
        for s in spec_data.get("series") or []:
            name = s.get("name", "")
            for value in s.get("y") or s.get("values") or []:
                yield {"series": name, "value": value}
    elif chart_type == "chart_heatmap":
        z = spec_data.get("z") or []
        xs = spec_data.get("x") or list(range(len(z[0]) if z else 0))
        ys = spec_data.get("y") or list(range(len(z)))
        for i, row in enumerate(z):
            for j, cell in enumerate(row):
                yield {"x": xs[j] if j < len(xs) else j,
                       "y": ys[i] if i < len(ys) else i,
                       "z": cell}
    elif chart_type == "chart_candlestick":
        t = spec_data.get("t") or spec_data.get("x") or []
        opens = spec_data.get("open") or []
        highs = spec_data.get("high") or []
        lows = spec_data.get("low") or []
        closes = spec_data.get("close") or []
        for i, ts in enumerate(t):
            yield {
                "t": ts,
                "open": opens[i] if i < len(opens) else None,
                "high": highs[i] if i < len(highs) else None,
                "low": lows[i] if i < len(lows) else None,
                "close": closes[i] if i < len(closes) else None,
            }
    elif chart_type == "chart_radar":
        for s in spec_data.get("series") or []:
            name = s.get("name", "")
            theta = s.get("theta") or spec_data.get("axes") or []
            r = s.get("r") or s.get("values") or []
            for axis, value in zip(theta, r):
                yield {"series": name, "axis": axis, "value": value}
    elif chart_type == "chart_sankey":
        nodes = {n.get("id", i): n.get("label", str(i)) for i, n in enumerate(spec_data.get("nodes") or [])}
        for link in spec_data.get("links") or []:
            yield {
                "source_id": link.get("source"),
                "source_label": nodes.get(link.get("source"), ""),
                "target_id": link.get("target"),
                "target_label": nodes.get(link.get("target"), ""),
                "value": link.get("value", 0),
            }
    elif chart_type == "chart_treemap":
        for item in spec_data.get("items") or []:
            yield {
                "id": item.get("id"),
                "label": item.get("label"),
                "parent": item.get("parent", ""),
                "value": item.get("value", 0),
            }
    elif chart_type == "chart_network":
        for node in spec_data.get("nodes") or []:
            yield {"kind": "node", "id": node.get("id"), "label": node.get("label", "")}
        for edge in spec_data.get("edges") or spec_data.get("links") or []:
            yield {"kind": "edge", "id": "", "label": "",
                   "source": edge.get("source"), "target": edge.get("target")}
    else:
        yield {"value": json.dumps(spec_data, default=json_default)}


# --- registration ------------------------------------------------------------


def _bind(chart_type: str) -> None:
    def png(raw, **kw):
        return _to_static(raw, chart_type=chart_type, fmt="png", **kw)

    def svg(raw, **kw):
        return _to_static(raw, chart_type=chart_type, fmt="svg", **kw)

    def pdf(raw, **kw):
        return _to_static(raw, chart_type=chart_type, fmt="pdf", **kw)

    def html(raw, **kw):
        return _to_html(raw, chart_type=chart_type, **kw)

    def to_json(raw, **kw):
        return _to_json(raw, chart_type=chart_type, **kw)

    def to_csv(raw, **kw):
        return _to_csv(raw, chart_type=chart_type, **kw)

    register_exporter(chart_type, "png", png, default=True)
    register_exporter(chart_type, "svg", svg)
    register_exporter(chart_type, "pdf", pdf)
    register_exporter(chart_type, "html", html)
    register_exporter(chart_type, "json", to_json)
    register_exporter(chart_type, "csv", to_csv)


for _ct in CHART_TYPES:
    _bind(_ct)
