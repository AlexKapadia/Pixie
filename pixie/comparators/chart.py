"""Chart-family comparators. Data-only — never renders pixels."""

from __future__ import annotations

import math
from typing import Any

from pixie.comparators._base import Diff


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _close(a: float, b: float, rtol: float, atol: float) -> bool:
    if math.isnan(a) and math.isnan(b):
        return True
    if math.isnan(a) or math.isnan(b):
        return False
    return math.isclose(float(a), float(b), rel_tol=rtol, abs_tol=atol)


def _values_close(e_list: list[Any], a_list: list[Any], rtol: float, atol: float) -> bool:
    if len(e_list) != len(a_list):
        return False
    for e, a in zip(e_list, a_list):
        if _is_number(e) and _is_number(a):
            if not _close(float(e), float(a), rtol, atol):
                return False
        elif e != a:
            return False
    return True


def compare_chart(
    output_key: str,
    output_type: str,
    expected: Any,
    actual: Any,
    tolerance: dict[str, Any],
) -> Diff | None:
    """Dispatch a chart compare based on tolerance.compare."""

    mode = tolerance.get("compare", "data_only")
    rtol = float(tolerance.get("float_rtol", 1.0e-6))
    atol = float(tolerance.get("float_atol", 1.0e-9))

    if mode == "skip":
        return None

    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator=f"chart_{mode}",
            expected=expected, actual=actual,
            metric=f"chart payload must be a dict ({type(expected).__name__}/{type(actual).__name__})",
        )

    if mode == "data_only":
        return _compare_data_only(output_key, output_type, expected, actual, tolerance, rtol, atol)
    if mode == "slices_unordered":
        return _compare_slices(output_key, output_type, expected, actual, rtol, atol)
    if mode == "values_unordered":
        return _compare_values_unordered(output_key, output_type, expected, actual, rtol, atol)
    if mode == "series_summary":
        return _compare_series_summary(output_key, output_type, expected, actual, rtol, atol)
    if mode == "matrix_elementwise":
        return _compare_matrix(output_key, output_type, expected, actual, rtol, atol)
    if mode == "rows_ordered":
        return _compare_candlestick(output_key, output_type, expected, actual, rtol, atol)
    if mode == "graph_set":
        return _compare_graph(output_key, output_type, expected, actual, rtol, atol)
    if mode == "tree_set":
        return _compare_treemap(output_key, output_type, expected, actual, rtol, atol)
    return Diff(
        output_key=output_key, output_type=output_type,
        comparator=f"chart_{mode}",
        expected=expected, actual=actual,
        metric=f"unknown chart compare mode {mode!r}",
    )


def _compare_data_only(
    output_key: str, output_type: str,
    expected: dict[str, Any], actual: dict[str, Any],
    tolerance: dict[str, Any], rtol: float, atol: float,
) -> Diff | None:
    series_match = tolerance.get("series_match", "by_name")
    if "x" in expected or "x" in actual:
        e_x = expected.get("x") or []
        a_x = actual.get("x") or []
        if not _values_close(e_x, a_x, rtol, atol):
            return Diff(
                output_key=output_key, output_type=output_type, comparator="chart_data_only",
                expected=e_x, actual=a_x, metric="x-axis values differ",
            )
    if "axes" in expected or "axes" in actual:
        if expected.get("axes") != actual.get("axes"):
            return Diff(
                output_key=output_key, output_type=output_type, comparator="chart_data_only",
                expected=expected.get("axes"), actual=actual.get("axes"),
                metric="radar axes differ",
            )
    e_series = expected.get("series") or []
    a_series = actual.get("series") or []
    if len(e_series) != len(a_series):
        return Diff(
            output_key=output_key, output_type=output_type, comparator="chart_data_only",
            expected=len(e_series), actual=len(a_series),
            metric=f"series count differs: {len(e_series)} vs {len(a_series)}",
        )

    if series_match == "by_name":
        e_by_name = {(s.get("name") or i): s for i, s in enumerate(e_series)}
        a_by_name = {(s.get("name") or i): s for i, s in enumerate(a_series)}
        for name, e_ser in e_by_name.items():
            if name not in a_by_name:
                return Diff(
                    output_key=output_key, output_type=output_type, comparator="chart_data_only",
                    expected=name, actual=list(a_by_name.keys()),
                    metric=f"series {name!r} missing in actual",
                )
            sub = _compare_one_series(e_ser, a_by_name[name], rtol, atol)
            if sub:
                return Diff(
                    output_key=output_key, output_type=output_type, comparator="chart_data_only",
                    expected=e_ser, actual=a_by_name[name],
                    metric=f"series {name!r}: {sub}",
                )
        return None

    for i, (e_ser, a_ser) in enumerate(zip(e_series, a_series)):
        sub = _compare_one_series(e_ser, a_ser, rtol, atol)
        if sub:
            return Diff(
                output_key=output_key, output_type=output_type, comparator="chart_data_only",
                expected=e_ser, actual=a_ser,
                metric=f"series #{i}: {sub}",
            )
    return None


def _compare_one_series(e_ser: dict, a_ser: dict, rtol: float, atol: float) -> str | None:
    for key in ("y", "x", "values"):
        if key in e_ser or key in a_ser:
            if not _values_close(e_ser.get(key) or [], a_ser.get(key) or [], rtol, atol):
                return f"{key} values differ"
    # scatter-style points
    if "points" in e_ser or "points" in a_ser:
        e_pts = e_ser.get("points") or []
        a_pts = a_ser.get("points") or []
        if len(e_pts) != len(a_pts):
            return f"point count differs: {len(e_pts)} vs {len(a_pts)}"
        for ep, ap in zip(sorted(e_pts, key=str), sorted(a_pts, key=str)):
            if isinstance(ep, dict):
                for k in ep:
                    e_v, a_v = ep.get(k), ap.get(k) if isinstance(ap, dict) else None
                    if _is_number(e_v) and _is_number(a_v):
                        if not _close(float(e_v), float(a_v), rtol, atol):
                            return f"point {k!r} mismatch"
                    elif e_v != a_v:
                        return f"point {k!r} mismatch"
    return None


def _compare_slices(
    output_key: str, output_type: str,
    expected: dict[str, Any], actual: dict[str, Any],
    rtol: float, atol: float,
) -> Diff | None:
    e_slices = expected.get("slices") or []
    a_slices = actual.get("slices") or []
    if len(e_slices) != len(a_slices):
        return Diff(
            output_key=output_key, output_type=output_type, comparator="slices_unordered",
            expected=len(e_slices), actual=len(a_slices),
            metric=f"slice count differs: {len(e_slices)} vs {len(a_slices)}",
        )
    a_by_label = {s.get("label"): s for s in a_slices}
    for e_slice in e_slices:
        label = e_slice.get("label")
        if label not in a_by_label:
            return Diff(
                output_key=output_key, output_type=output_type, comparator="slices_unordered",
                expected=label, actual=list(a_by_label.keys()),
                metric=f"slice {label!r} missing",
            )
        a_slice = a_by_label[label]
        e_val = e_slice.get("value")
        a_val = a_slice.get("value")
        if _is_number(e_val) and _is_number(a_val):
            if not _close(float(e_val), float(a_val), rtol, atol):
                return Diff(
                    output_key=output_key, output_type=output_type, comparator="slices_unordered",
                    expected=e_val, actual=a_val,
                    metric=f"slice {label!r}: {e_val} vs {a_val}",
                )
        elif e_val != a_val:
            return Diff(
                output_key=output_key, output_type=output_type, comparator="slices_unordered",
                expected=e_val, actual=a_val,
                metric=f"slice {label!r}: {e_val!r} vs {a_val!r}",
            )
    return None


def _compare_values_unordered(
    output_key: str, output_type: str,
    expected: dict[str, Any], actual: dict[str, Any],
    rtol: float, atol: float,
) -> Diff | None:
    e_vals = sorted(expected.get("values") or [])
    a_vals = sorted(actual.get("values") or [])
    if len(e_vals) != len(a_vals):
        return Diff(
            output_key=output_key, output_type=output_type, comparator="values_unordered",
            expected=len(e_vals), actual=len(a_vals),
            metric=f"value count differs: {len(e_vals)} vs {len(a_vals)}",
        )
    for ev, av in zip(e_vals, a_vals):
        if _is_number(ev) and _is_number(av):
            if not _close(float(ev), float(av), rtol, atol):
                return Diff(
                    output_key=output_key, output_type=output_type, comparator="values_unordered",
                    expected=ev, actual=av,
                    metric=f"histogram value {ev} vs {av} exceeds tolerance",
                )
        elif ev != av:
            return Diff(
                output_key=output_key, output_type=output_type, comparator="values_unordered",
                expected=ev, actual=av,
                metric=f"histogram value mismatch {ev!r} vs {av!r}",
            )
    return None


def _compare_series_summary(
    output_key: str, output_type: str,
    expected: dict[str, Any], actual: dict[str, Any],
    rtol: float, atol: float,
) -> Diff | None:
    e_series = expected.get("series") or []
    a_series = actual.get("series") or []
    if len(e_series) != len(a_series):
        return Diff(
            output_key=output_key, output_type=output_type, comparator="series_summary",
            expected=len(e_series), actual=len(a_series),
            metric=f"series count differs: {len(e_series)} vs {len(a_series)}",
        )
    for e_ser, a_ser in zip(e_series, a_series):
        for key in ("q1", "q2", "q3", "min", "max", "median"):
            e_v = e_ser.get(key)
            a_v = a_ser.get(key)
            if e_v is None and a_v is None:
                continue
            if _is_number(e_v) and _is_number(a_v):
                if not _close(float(e_v), float(a_v), rtol, atol):
                    return Diff(
                        output_key=output_key, output_type=output_type, comparator="series_summary",
                        expected=e_v, actual=a_v,
                        metric=f"series {e_ser.get('name')!r}.{key}: {e_v} vs {a_v}",
                    )
            elif e_v != a_v:
                return Diff(
                    output_key=output_key, output_type=output_type, comparator="series_summary",
                    expected=e_v, actual=a_v,
                    metric=f"series {e_ser.get('name')!r}.{key}: {e_v!r} vs {a_v!r}",
                )
    return None


def _compare_matrix(
    output_key: str, output_type: str,
    expected: dict[str, Any], actual: dict[str, Any],
    rtol: float, atol: float,
) -> Diff | None:
    e_z = expected.get("z") or []
    a_z = actual.get("z") or []
    if len(e_z) != len(a_z):
        return Diff(
            output_key=output_key, output_type=output_type, comparator="matrix_elementwise",
            expected=(len(e_z),), actual=(len(a_z),),
            metric=f"row count differs: {len(e_z)} vs {len(a_z)}",
        )
    for r, (e_row, a_row) in enumerate(zip(e_z, a_z)):
        if len(e_row) != len(a_row):
            return Diff(
                output_key=output_key, output_type=output_type, comparator="matrix_elementwise",
                expected=len(e_row), actual=len(a_row),
                metric=f"row {r} length differs",
            )
        for c, (e_v, a_v) in enumerate(zip(e_row, a_row)):
            if _is_number(e_v) and _is_number(a_v):
                if not _close(float(e_v), float(a_v), rtol, atol):
                    return Diff(
                        output_key=output_key, output_type=output_type,
                        comparator="matrix_elementwise",
                        expected=e_v, actual=a_v, path=f"[{r},{c}]",
                        metric=f"cell [{r},{c}]: {e_v} vs {a_v}",
                    )
            elif e_v != a_v:
                return Diff(
                    output_key=output_key, output_type=output_type,
                    comparator="matrix_elementwise",
                    expected=e_v, actual=a_v, path=f"[{r},{c}]",
                    metric=f"cell [{r},{c}]: {e_v!r} vs {a_v!r}",
                )
    return None


def _compare_candlestick(
    output_key: str, output_type: str,
    expected: dict[str, Any], actual: dict[str, Any],
    rtol: float, atol: float,
) -> Diff | None:
    e_pts = expected.get("points") or []
    a_pts = actual.get("points") or []
    if len(e_pts) != len(a_pts):
        return Diff(
            output_key=output_key, output_type=output_type, comparator="rows_ordered",
            expected=len(e_pts), actual=len(a_pts),
            metric=f"candle count differs: {len(e_pts)} vs {len(a_pts)}",
        )
    for i, (e, a) in enumerate(zip(e_pts, a_pts)):
        for key in ("o", "h", "l", "c", "t", "open", "high", "low", "close"):
            e_v = e.get(key) if isinstance(e, dict) else None
            a_v = a.get(key) if isinstance(a, dict) else None
            if e_v is None and a_v is None:
                continue
            if _is_number(e_v) and _is_number(a_v):
                if not _close(float(e_v), float(a_v), rtol, atol):
                    return Diff(
                        output_key=output_key, output_type=output_type, comparator="rows_ordered",
                        expected=e_v, actual=a_v,
                        metric=f"candle {i} {key!r}: {e_v} vs {a_v}",
                    )
            elif e_v != a_v:
                return Diff(
                    output_key=output_key, output_type=output_type, comparator="rows_ordered",
                    expected=e_v, actual=a_v,
                    metric=f"candle {i} {key!r}: {e_v!r} vs {a_v!r}",
                )
    return None


def _compare_graph(
    output_key: str, output_type: str,
    expected: dict[str, Any], actual: dict[str, Any],
    rtol: float, atol: float,
) -> Diff | None:
    e_nodes = {_node_key(n) for n in (expected.get("nodes") or [])}
    a_nodes = {_node_key(n) for n in (actual.get("nodes") or [])}
    if e_nodes != a_nodes:
        return Diff(
            output_key=output_key, output_type=output_type, comparator="graph_set",
            expected=sorted(e_nodes), actual=sorted(a_nodes),
            metric=f"node set differs: missing {sorted(e_nodes - a_nodes)}, extra {sorted(a_nodes - e_nodes)}",
        )
    edges_field = "links" if "links" in expected else "edges"
    e_edges = [_edge_key(e) for e in (expected.get(edges_field) or [])]
    a_edges = [_edge_key(e) for e in (actual.get(edges_field) or [])]
    e_edges.sort()
    a_edges.sort()
    if len(e_edges) != len(a_edges):
        return Diff(
            output_key=output_key, output_type=output_type, comparator="graph_set",
            expected=len(e_edges), actual=len(a_edges),
            metric=f"edge count differs: {len(e_edges)} vs {len(a_edges)}",
        )
    for e_edge, a_edge in zip(e_edges, a_edges):
        if e_edge[:2] != a_edge[:2]:
            return Diff(
                output_key=output_key, output_type=output_type, comparator="graph_set",
                expected=e_edge, actual=a_edge,
                metric=f"edge mismatch: {e_edge} vs {a_edge}",
            )
        e_w, a_w = e_edge[2], a_edge[2]
        if e_w is None and a_w is None:
            continue
        if _is_number(e_w) and _is_number(a_w):
            if not _close(float(e_w), float(a_w), rtol, atol):
                return Diff(
                    output_key=output_key, output_type=output_type, comparator="graph_set",
                    expected=e_w, actual=a_w,
                    metric=f"edge {e_edge[:2]} weight: {e_w} vs {a_w}",
                )
        elif e_w != a_w:
            return Diff(
                output_key=output_key, output_type=output_type, comparator="graph_set",
                expected=e_w, actual=a_w,
                metric=f"edge {e_edge[:2]} weight mismatch",
            )
    return None


def _node_key(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("id") or node.get("name") or "")
    return str(node)


def _edge_key(edge: Any) -> tuple:
    if isinstance(edge, dict):
        return (
            str(edge.get("source") or edge.get("src") or edge.get("from") or ""),
            str(edge.get("target") or edge.get("tgt") or edge.get("to") or ""),
            edge.get("value") or edge.get("weight"),
        )
    return (str(edge), "", None)


def _compare_treemap(
    output_key: str, output_type: str,
    expected: dict[str, Any], actual: dict[str, Any],
    rtol: float, atol: float,
) -> Diff | None:
    e_nodes = expected.get("nodes") or []
    a_nodes = actual.get("nodes") or []
    e_set = {(n.get("name"), n.get("parent")) for n in e_nodes if isinstance(n, dict)}
    a_set = {(n.get("name"), n.get("parent")) for n in a_nodes if isinstance(n, dict)}
    if e_set != a_set:
        return Diff(
            output_key=output_key, output_type=output_type, comparator="tree_set",
            expected=sorted(e_set), actual=sorted(a_set),
            metric=f"treemap node set differs ({len(e_set ^ a_set)} mismatches)",
        )
    e_by_name = {n.get("name"): n for n in e_nodes if isinstance(n, dict)}
    a_by_name = {n.get("name"): n for n in a_nodes if isinstance(n, dict)}
    for name, e_node in e_by_name.items():
        e_val = e_node.get("value")
        a_val = a_by_name[name].get("value")
        if _is_number(e_val) and _is_number(a_val):
            if not _close(float(e_val), float(a_val), rtol, atol):
                return Diff(
                    output_key=output_key, output_type=output_type, comparator="tree_set",
                    expected=e_val, actual=a_val,
                    metric=f"treemap node {name!r} value: {e_val} vs {a_val}",
                )
    return None
