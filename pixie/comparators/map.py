"""Map-family comparators.

All coordinate-set comparators round lat/lon to 4 d.p. (~11m) before
comparison; choropleth compares by region key, not geometry.
"""

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


def _round_point(p: Any, digits: int) -> tuple:
    if isinstance(p, dict):
        lat = p.get("lat") or p.get("latitude")
        lon = p.get("lon") or p.get("lng") or p.get("longitude")
        return (round(float(lat), digits), round(float(lon), digits))
    if isinstance(p, (list, tuple)) and len(p) >= 2:
        return (round(float(p[0]), digits), round(float(p[1]), digits))
    return (p,)


def compare_map(
    output_key: str,
    output_type: str,
    expected: Any,
    actual: Any,
    tolerance: dict[str, Any],
) -> Diff | None:
    """Dispatch by output type — points / heatmap / choropleth / polygons / route."""

    mode = tolerance.get("compare")
    if mode == "skip":
        return None

    digits = int(tolerance.get("round_digits", 4))
    rtol = float(tolerance.get("float_rtol", 1.0e-6))
    atol = float(tolerance.get("float_atol", 1.0e-9))

    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator=f"map:{mode}",
            expected=expected, actual=actual,
            metric=f"map payload must be a dict ({type(expected).__name__}/{type(actual).__name__})",
        )

    if output_type in {"map_points", "map_heatmap"}:
        return _compare_point_set(output_key, output_type, expected, actual, digits, rtol, atol)
    if output_type == "map_route":
        return _compare_route(output_key, output_type, expected, actual, digits)
    if output_type == "map_choropleth":
        return _compare_choropleth(output_key, output_type, expected, actual, rtol, atol)
    if output_type == "map_polygons":
        return _compare_polygons(output_key, output_type, expected, actual, digits)
    return Diff(
        output_key=output_key, output_type=output_type,
        comparator="map_unknown",
        expected=expected, actual=actual,
        metric=f"unsupported map output type {output_type!r}",
    )


def _compare_point_set(
    output_key: str, output_type: str,
    expected: dict, actual: dict, digits: int,
    rtol: float, atol: float,
) -> Diff | None:
    e_points = expected.get("points") or []
    a_points = actual.get("points") or []
    if len(e_points) != len(a_points):
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator="points_round_set",
            expected=len(e_points), actual=len(a_points),
            metric=f"point count differs: {len(e_points)} vs {len(a_points)}",
        )
    e_set = {_round_point(p, digits) for p in e_points}
    a_set = {_round_point(p, digits) for p in a_points}
    missing = sorted(e_set - a_set)
    extra = sorted(a_set - e_set)
    if missing or extra:
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator="points_round_set",
            expected=sorted(e_set)[:5], actual=sorted(a_set)[:5],
            metric=(
                f"point set differs (rounded {digits}dp): "
                f"{len(missing)} missing, {len(extra)} extra"
            ),
        )
    # intensities for heatmap
    if output_type == "map_heatmap":
        e_by_key = {_round_point(p, digits): p for p in e_points if isinstance(p, dict)}
        a_by_key = {_round_point(p, digits): p for p in a_points if isinstance(p, dict)}
        for key, e_p in e_by_key.items():
            e_w = e_p.get("intensity") or e_p.get("weight")
            a_w = a_by_key.get(key, {}).get("intensity") or a_by_key.get(key, {}).get("weight")
            if e_w is None and a_w is None:
                continue
            if _is_number(e_w) and _is_number(a_w) and not _close(float(e_w), float(a_w), rtol, atol):
                return Diff(
                    output_key=output_key, output_type=output_type,
                    comparator="points_round_set",
                    expected=e_w, actual=a_w,
                    metric=f"intensity at {key} differs: {e_w} vs {a_w}",
                )
    return None


def _compare_route(
    output_key: str, output_type: str,
    expected: dict, actual: dict, digits: int,
) -> Diff | None:
    e_points = expected.get("points") or []
    a_points = actual.get("points") or []
    if len(e_points) != len(a_points):
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator="route_round_ordered",
            expected=len(e_points), actual=len(a_points),
            metric=f"vertex count differs: {len(e_points)} vs {len(a_points)}",
        )
    for i, (e_p, a_p) in enumerate(zip(e_points, a_points)):
        e_r = _round_point(e_p, digits)
        a_r = _round_point(a_p, digits)
        if e_r != a_r:
            return Diff(
                output_key=output_key, output_type=output_type,
                comparator="route_round_ordered",
                expected=e_r, actual=a_r,
                metric=f"route vertex {i} differs (rounded {digits}dp): {e_r} vs {a_r}",
            )
    return None


def _compare_choropleth(
    output_key: str, output_type: str,
    expected: dict, actual: dict, rtol: float, atol: float,
) -> Diff | None:
    e_values = expected.get("values") or {}
    a_values = actual.get("values") or {}
    if not isinstance(e_values, dict) or not isinstance(a_values, dict):
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator="keyed_values",
            expected=e_values, actual=a_values,
            metric="choropleth.values must be a dict of region->value",
        )
    if set(e_values) != set(a_values):
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator="keyed_values",
            expected=sorted(e_values), actual=sorted(a_values),
            metric=(
                f"region key set differs: "
                f"missing {sorted(set(e_values) - set(a_values))}, "
                f"extra {sorted(set(a_values) - set(e_values))}"
            ),
        )
    for key, e_v in e_values.items():
        a_v = a_values[key]
        if _is_number(e_v) and _is_number(a_v):
            if not _close(float(e_v), float(a_v), rtol, atol):
                return Diff(
                    output_key=output_key, output_type=output_type,
                    comparator="keyed_values",
                    expected=e_v, actual=a_v,
                    metric=f"region {key!r} value: {e_v} vs {a_v}",
                )
        elif e_v != a_v:
            return Diff(
                output_key=output_key, output_type=output_type,
                comparator="keyed_values",
                expected=e_v, actual=a_v,
                metric=f"region {key!r} value: {e_v!r} vs {a_v!r}",
            )
    return None


def _compare_polygons(
    output_key: str, output_type: str,
    expected: dict, actual: dict, digits: int,
) -> Diff | None:
    e_polys = expected.get("polygons") or []
    a_polys = actual.get("polygons") or []
    if len(e_polys) != len(a_polys):
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator="polygon_round_set",
            expected=len(e_polys), actual=len(a_polys),
            metric=f"polygon count differs: {len(e_polys)} vs {len(a_polys)}",
        )

    def _poly_key(poly: Any) -> frozenset:
        verts = poly.get("vertices") if isinstance(poly, dict) else poly
        return frozenset(_round_point(v, digits) for v in (verts or []))

    e_set = {_poly_key(p) for p in e_polys}
    a_set = {_poly_key(p) for p in a_polys}
    if e_set != a_set:
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator="polygon_round_set",
            expected=len(e_set), actual=len(a_set),
            metric=f"polygon vertex sets differ ({len(e_set ^ a_set)} mismatches)",
        )
    return None
