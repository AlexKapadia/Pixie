"""Numeric comparator: :func:`math.isclose` with rtol/atol from tolerance."""

from __future__ import annotations

import math
from typing import Any

from pixie.comparators._base import Diff


def compare_number(
    output_key: str,
    output_type: str,
    expected: Any,
    actual: Any,
    tolerance: dict[str, Any],
) -> Diff | None:
    """Compare two numeric values via ``math.isclose``.

    Booleans are rejected on purpose: ``isclose(True, 1.0)`` would silently
    pass, masking a real type mismatch.
    """

    if isinstance(expected, bool) or isinstance(actual, bool):
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator="numeric_isclose",
            expected=expected, actual=actual,
            metric="boolean refused by numeric comparator",
        )

    # Tolerant unwrap: tools may return {value: N} for scalar outputs.
    expected_num = _unwrap(expected)
    actual_num = _unwrap(actual)

    if not isinstance(expected_num, (int, float)):
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator="numeric_isclose",
            expected=expected, actual=actual,
            metric=f"expected value is not a number (got {type(expected_num).__name__})",
        )
    if not isinstance(actual_num, (int, float)):
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator="numeric_isclose",
            expected=expected, actual=actual,
            metric=f"actual value is not a number (got {type(actual_num).__name__})",
        )

    rtol = float(tolerance.get("rtol", 1.0e-6))
    atol = float(tolerance.get("atol", 1.0e-9))

    if _isclose(float(expected_num), float(actual_num), rtol, atol):
        return None

    delta = abs(float(actual_num) - float(expected_num))
    denom = max(abs(float(expected_num)), abs(float(actual_num)), 1.0e-300)
    achieved_rtol = delta / denom
    metric = (
        f"rtol_exceeded: {achieved_rtol:.3g} > {rtol:.3g} "
        f"(expected={expected_num}, actual={actual_num}, |delta|={delta:.3g})"
    )
    return Diff(
        output_key=output_key, output_type=output_type,
        comparator="numeric_isclose",
        expected=expected_num, actual=actual_num, metric=metric,
    )


def _unwrap(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _isclose(a: float, b: float, rtol: float, atol: float) -> bool:
    # NaN-aware: two NaNs are considered equal under tolerance.
    if math.isnan(a) and math.isnan(b):
        return True
    if math.isnan(a) or math.isnan(b):
        return False
    return math.isclose(a, b, rel_tol=rtol, abs_tol=atol)
