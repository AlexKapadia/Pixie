"""Public comparator API for check #12 ``reference_fixtures_match``.

The validator never imports the per-family modules directly. It calls
:func:`compare` and :func:`deep_compare` here; this module dispatches
to the right comparator by output type. See ``RESEARCH_reference_validator.md``
§§2-3 for the full design (39 output types, 4-level tolerance hierarchy).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pixie.comparators._base import (
    BUILTIN_DEFAULTS,
    Diff,
    FixtureResult,
    ReferenceFixture,
    ToleranceConfig,
    TruncationLimit,
    load_fixtures,
    load_tolerance_yaml,
    merged_tolerance,
    truncate_for_display,
)
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
from pixie.comparators.numeric import compare_number
from pixie.comparators.structural import compare_boolean, compare_kv, compare_tree
from pixie.comparators.table import compare_table
from pixie.comparators.text import compare_text
from pixie.comparators.timeline import compare_timeline


__all__ = [
    "Diff",
    "FixtureResult",
    "ReferenceFixture",
    "ToleranceConfig",
    "BUILTIN_DEFAULTS",
    "compare",
    "deep_compare",
    "merged_tolerance",
    "load_tolerance_yaml",
    "load_fixtures",
    "truncate_for_display",
]


# Map every declared output type in :class:`pixie.discovery.OutputSpec`
# (39 entries) to the function that knows how to compare it.

_CHART_TYPES = (
    "chart_line", "chart_bar", "chart_area", "chart_scatter", "chart_pie",
    "chart_histogram", "chart_boxplot", "chart_heatmap", "chart_candlestick",
    "chart_radar", "chart_sankey", "chart_treemap", "chart_network",
)
_MAP_TYPES = (
    "map_points", "map_heatmap", "map_choropleth", "map_polygons", "map_route",
)
_TIMELINE_TYPES = ("timeline", "gantt", "log")
_TEXT_FAMILY = ("text", "markdown", "code", "latex", "diff", "stream_text")


_DISPATCH = {
    "number": compare_number,
    "boolean": compare_boolean,
    "kv": compare_kv,
    "tree": compare_tree,
    "table": compare_table,
    "image": compare_image,
    "image_grid": compare_image_grid,
    "image_compare": compare_image_compare,
    "audio": compare_audio,
    "video": compare_video,
    "file": compare_file,
    "progress": None,  # always skipped
}
for _t in _CHART_TYPES:
    _DISPATCH[_t] = compare_chart
for _t in _MAP_TYPES:
    _DISPATCH[_t] = compare_map
for _t in _TIMELINE_TYPES:
    _DISPATCH[_t] = compare_timeline
for _t in _TEXT_FAMILY:
    _DISPATCH[_t] = compare_text


def compare(
    expected: Any,
    actual: Any,
    output_type: str,
    output_key: str,
    tolerance: dict[str, Any],
) -> Diff | None:
    """Top-level comparator dispatcher.

    Returns ``None`` on match, a :class:`Diff` on mismatch. ``output_key``
    is recorded on the returned ``Diff`` so the report can identify which
    output failed.
    """

    if tolerance.get("compare") == "skip":
        return Diff(
            output_key=output_key, output_type=output_type, comparator="skip",
            expected=None, actual=None,
            metric="comparison skipped by tolerance.compare: skip",
        )

    fn = _DISPATCH.get(output_type)
    if fn is None:
        # Unknown / progress / unsupported -> skip with explanation.
        return None
    return fn(output_key, output_type, expected, actual, tolerance)


def deep_compare(
    expected_outputs: dict[str, Any],
    actual_outputs: dict[str, Any],
    output_specs: list[Any],
    tolerance_config: ToleranceConfig,
    fixture_overrides: dict[str, dict[str, Any]] | None = None,
) -> list[Diff]:
    """Compare every declared output and return the list of diffs."""

    diffs: list[Diff] = []
    spec_by_key = {spec.key: spec for spec in output_specs}

    options = tolerance_config.options

    for key, expected in expected_outputs.items():
        spec = spec_by_key.get(key)
        if spec is None:
            # Should have been caught by load_fixtures, but be defensive.
            if options.on_extra_output_key != "ignore":
                diffs.append(Diff(
                    output_key=key, output_type="unknown",
                    comparator="schema_check",
                    expected=None, actual=None,
                    metric=f"output key {key!r} is not declared in tool.json",
                ))
            continue
        output_type = spec.type

        if not isinstance(actual_outputs, dict) or key not in actual_outputs:
            if options.on_missing_expected_key == "ignore":
                continue
            diffs.append(Diff(
                output_key=key, output_type=output_type, comparator="key_presence",
                expected=expected, actual=None,
                metric=f"output key {key!r} missing in /run response",
            ))
            continue

        tolerance = merged_tolerance(
            key, output_type, tolerance_config, fixture_overrides
        )
        diff = compare(
            expected=expected,
            actual=actual_outputs[key],
            output_type=output_type,
            output_key=key,
            tolerance=tolerance,
        )
        if diff is not None:
            # Surface a "skip" diff only if tolerance explicitly says skip.
            if diff.comparator == "skip" and tolerance.get("compare") != "skip":
                continue
            diffs.append(diff)

    if options.on_extra_output_key in {"warn", "fail"} and isinstance(actual_outputs, dict):
        declared = set(spec_by_key)
        unknown_actual = sorted(set(actual_outputs) - declared)
        # Only worth reporting when the fixture also asserts on those keys.
        # Otherwise this is just noise (the validator's check #9 handles it).
        for key in unknown_actual:
            if key not in expected_outputs:
                continue
            diffs.append(Diff(
                output_key=key, output_type="unknown",
                comparator="schema_check",
                expected=expected_outputs.get(key), actual=actual_outputs[key],
                metric=f"actual /run returned undeclared key {key!r}",
            ))

    return diffs


# Bound the public truncation constant.
TRUNCATE_LIMIT = TruncationLimit


def format_diff_report(fixture_results: list[FixtureResult]) -> str:
    """Markdown report for a list of failing fixture results."""

    sections: list[str] = []
    for result in fixture_results:
        if result.status == "skip":
            sections.append(
                f"### {result.name} — skipped\n\n> {result.message}\n"
            )
            continue
        if result.status == "pass":
            continue

        header = f"### {result.name} — {result.message}"
        if not result.diffs:
            sections.append(f"{header}\n")
            continue

        rows = ["| output | type | comparator | metric |", "|---|---|---|---|"]
        for diff in result.diffs:
            metric = (diff.metric or "").replace("|", "\\|").replace("\n", " ")
            path = f".{diff.path}" if diff.path else ""
            rows.append(
                f"| {diff.output_key}{path} | {diff.output_type} | "
                f"{diff.comparator} | {metric} |"
            )
        source_line = f"\n> Source: {result.source}\n" if result.source else ""
        sections.append("\n".join([header, "", *rows, source_line]))
    return "\n\n".join(sections).rstrip() + "\n"


def format_skip_report(fixture_results: list[FixtureResult]) -> str:
    lines = ["| fixture | reason |", "|---|---|"]
    for r in fixture_results:
        lines.append(f"| {r.name} | {r.message} |")
    return "\n".join(lines) + "\n"


def list_reference_fixtures(reference_dir: Path) -> list[dict[str, Any]]:
    """Lightweight directory scan for the HTTP picker endpoint."""

    if not reference_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(reference_dir.glob("fixture_*.json")):
        try:
            import json as _json
            data = _json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        out.append({
            "filename": path.name,
            "name": data.get("name", path.stem),
            "tags": data.get("tags", []),
            "source": data.get("source"),
            "skip_reason": data.get("skip_reason"),
        })
    return out
