"""Text-family comparators: text, markdown, code, latex, diff, stream_text."""

from __future__ import annotations

import json
import re
from typing import Any

from pixie.comparators._base import Diff


_WHITESPACE_RE = re.compile(r"\s+")
_LATEX_SPACE_RE = re.compile(r"\\[,;:!]")  # \, \; \: \!  (latex spacing)


def _unwrap(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _coerce_to_str(value: Any) -> tuple[str | None, str | None]:
    """Return ``(string, None)`` on success or ``(None, error)`` on failure."""

    unwrapped = _unwrap(value)
    if isinstance(unwrapped, str):
        return unwrapped, None
    return None, f"value is not a string (got {type(unwrapped).__name__})"


def _normalise_whitespace(s: str) -> str:
    """Collapse runs of whitespace, strip per-line trailing whitespace."""

    lines = [_WHITESPACE_RE.sub(" ", line).rstrip() for line in s.splitlines()]
    return "\n".join(lines).strip()


def _normalise_latex(s: str) -> str:
    return _normalise_whitespace(_LATEX_SPACE_RE.sub(" ", s))


def _first_diff_offset(a: str, b: str) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def _diff_window(a: str, b: str, *, width: int = 40) -> str:
    offset = _first_diff_offset(a, b)
    lo = max(0, offset - width // 2)
    hi_a = min(len(a), offset + width // 2)
    hi_b = min(len(b), offset + width // 2)
    return (
        f"strings differ at offset {offset}: "
        f"...{a[lo:hi_a]!r}... vs ...{b[lo:hi_b]!r}..."
    )


def compare_text(
    output_key: str,
    output_type: str,
    expected: Any,
    actual: Any,
    tolerance: dict[str, Any],
) -> Diff | None:
    """Compare two text-family values."""

    mode = tolerance.get("compare", "exact")
    comparator_name = f"{output_type}:{mode}"

    expected_s, expected_err = _coerce_to_str(expected)
    actual_s, actual_err = _coerce_to_str(actual)
    if expected_err or actual_err:
        msg = expected_err or actual_err
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator=comparator_name,
            expected=expected, actual=actual, metric=msg,
        )

    assert expected_s is not None and actual_s is not None  # for type narrowing

    if output_type == "latex" or mode == "exact_after_normalize_whitespace":
        normaliser = _normalise_latex if output_type == "latex" else _normalise_whitespace
        e_norm = normaliser(expected_s)
        a_norm = normaliser(actual_s)
        if e_norm == a_norm:
            return None
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator=comparator_name,
            expected=expected_s, actual=actual_s,
            metric=_diff_window(e_norm, a_norm),
        )

    if mode == "json_normalized":
        try:
            e_obj = json.loads(expected_s)
            a_obj = json.loads(actual_s)
        except json.JSONDecodeError as exc:
            return Diff(
                output_key=output_key, output_type=output_type,
                comparator=comparator_name,
                expected=expected_s, actual=actual_s,
                metric=f"json parse failure: {exc}",
            )
        if e_obj == a_obj:
            return None
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator=comparator_name,
            expected=e_obj, actual=a_obj,
            metric="json values differ structurally",
        )

    # default: exact byte-equal compare
    if expected_s == actual_s:
        return None
    return Diff(
        output_key=output_key, output_type=output_type,
        comparator=comparator_name,
        expected=expected_s, actual=actual_s,
        metric=_diff_window(expected_s, actual_s),
    )
