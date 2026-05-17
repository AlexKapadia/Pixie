"""Timeline / gantt / log comparators (all rows_ordered)."""

from __future__ import annotations

import re
from typing import Any

from pixie.comparators._base import Diff


def compare_timeline(
    output_key: str,
    output_type: str,
    expected: Any,
    actual: Any,
    tolerance: dict[str, Any],
) -> Diff | None:
    """Compare timeline/gantt/log outputs in declared order."""

    field = _payload_field(output_type)
    e_list = expected.get(field) if isinstance(expected, dict) else expected
    a_list = actual.get(field) if isinstance(actual, dict) else actual
    if not isinstance(e_list, list) or not isinstance(a_list, list):
        return Diff(
            output_key=output_key, output_type=output_type, comparator="rows_ordered",
            expected=e_list, actual=a_list,
            metric=f"{output_type} expects a list under .{field}",
        )
    if len(e_list) != len(a_list):
        return Diff(
            output_key=output_key, output_type=output_type, comparator="rows_ordered",
            expected=len(e_list), actual=len(a_list),
            metric=f"{field} count differs: {len(e_list)} vs {len(a_list)}",
        )

    allow_regex = bool(tolerance.get("allow_regex", False))

    for i, (e_row, a_row) in enumerate(zip(e_list, a_list)):
        if output_type == "log":
            sub = _compare_log_line(e_row, a_row, allow_regex)
            if sub is not None:
                return Diff(
                    output_key=output_key, output_type=output_type, comparator="rows_ordered",
                    expected=e_row, actual=a_row,
                    metric=f"line {i}: {sub}",
                )
            continue
        if isinstance(e_row, dict) and isinstance(a_row, dict):
            for key in sorted(set(e_row) | set(a_row)):
                e_v = e_row.get(key)
                a_v = a_row.get(key)
                if e_v != a_v:
                    return Diff(
                        output_key=output_key, output_type=output_type, comparator="rows_ordered",
                        expected=e_v, actual=a_v,
                        metric=f"row {i} key {key!r}: {e_v!r} vs {a_v!r}",
                    )
        elif e_row != a_row:
            return Diff(
                output_key=output_key, output_type=output_type, comparator="rows_ordered",
                expected=e_row, actual=a_row,
                metric=f"row {i}: {e_row!r} vs {a_row!r}",
            )
    return None


def _payload_field(output_type: str) -> str:
    if output_type == "timeline":
        return "events"
    if output_type == "gantt":
        return "tasks"
    if output_type == "log":
        return "lines"
    return "rows"


def _compare_log_line(expected: Any, actual: Any, allow_regex: bool) -> str | None:
    if allow_regex and isinstance(expected, str) and expected.startswith("re:"):
        pattern = expected[3:]
        try:
            if re.fullmatch(pattern, str(actual)):
                return None
        except re.error as exc:
            return f"invalid regex {pattern!r}: {exc}"
        return f"actual {actual!r} did not match regex {pattern!r}"
    if expected == actual:
        return None
    return f"{expected!r} vs {actual!r}"
