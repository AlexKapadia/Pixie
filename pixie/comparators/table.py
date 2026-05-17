"""Table comparator: rows_unordered, rows_ordered, per-cell dispatch."""

from __future__ import annotations

import math
from typing import Any

from pixie.comparators._base import Diff


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _cells_equal(a: Any, b: Any, rtol: float, atol: float) -> bool:
    if _is_number(a) and _is_number(b):
        if math.isnan(a) and math.isnan(b):
            return True
        if math.isnan(a) or math.isnan(b):
            return False
        return math.isclose(float(a), float(b), rel_tol=rtol, abs_tol=atol)
    return a == b


def _row_to_dict(row: Any, columns: list[str]) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if isinstance(row, (list, tuple)):
        return {columns[i]: row[i] for i in range(min(len(columns), len(row)))}
    return {"_value": row}


def _sort_key(row: dict[str, Any], columns: list[str]) -> tuple:
    out: list[Any] = []
    for column in columns:
        value = row.get(column)
        if value is None:
            out.append((0, ""))
        elif _is_number(value):
            out.append((1, float(value)))
        else:
            out.append((2, str(value)))
    return tuple(out)


def compare_table(
    output_key: str,
    output_type: str,
    expected: Any,
    actual: Any,
    tolerance: dict[str, Any],
) -> Diff | None:
    """Compare two table outputs."""

    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator="table_rows_unordered",
            expected=expected, actual=actual,
            metric=f"table value must be a dict (got {type(expected).__name__}/{type(actual).__name__})",
        )

    exp_cols = _normalise_columns(expected.get("columns"))
    act_cols = _normalise_columns(actual.get("columns"))
    if exp_cols and act_cols and exp_cols != act_cols:
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator="table_rows_unordered",
            expected=exp_cols, actual=act_cols,
            metric=f"column names differ: {exp_cols} vs {act_cols}",
        )
    columns = exp_cols or act_cols or []

    exp_rows = expected.get("rows", []) or []
    act_rows = actual.get("rows", []) or []
    if len(exp_rows) != len(act_rows):
        return Diff(
            output_key=output_key, output_type=output_type,
            comparator="table_rows_unordered",
            expected=len(exp_rows), actual=len(act_rows),
            metric=f"row counts differ: {len(exp_rows)} vs {len(act_rows)}",
        )

    rtol = float(tolerance.get("float_rtol", 1.0e-6))
    atol = float(tolerance.get("float_atol", 1.0e-9))
    mode = tolerance.get("compare", "rows_unordered")

    if mode == "rows_unordered":
        exp_d = [_row_to_dict(r, columns) for r in exp_rows]
        act_d = [_row_to_dict(r, columns) for r in act_rows]
        if columns:
            exp_d.sort(key=lambda r: _sort_key(r, columns))
            act_d.sort(key=lambda r: _sort_key(r, columns))
    else:  # rows_ordered
        exp_d = [_row_to_dict(r, columns) for r in exp_rows]
        act_d = [_row_to_dict(r, columns) for r in act_rows]

    for index, (e_row, a_row) in enumerate(zip(exp_d, act_d)):
        keys = columns or sorted(set(e_row) | set(a_row))
        for column in keys:
            e_val = e_row.get(column)
            a_val = a_row.get(column)
            if not _cells_equal(e_val, a_val, rtol, atol):
                if _is_number(e_val) and _is_number(a_val):
                    delta = abs(float(a_val) - float(e_val))
                    denom = max(abs(float(e_val)), abs(float(a_val)), 1.0e-300)
                    achieved = delta / denom
                    metric = (
                        f"row {index} column {column!r}: rtol_exceeded "
                        f"{achieved:.3g} > {rtol:.3g} ({e_val} vs {a_val})"
                    )
                else:
                    metric = f"row {index} column {column!r}: {e_val!r} vs {a_val!r}"
                return Diff(
                    output_key=output_key, output_type=output_type,
                    comparator=f"table_{mode}",
                    expected=e_val, actual=a_val,
                    path=f"rows[{index}].{column}",
                    metric=metric,
                )
    return None


def _normalise_columns(columns: Any) -> list[str]:
    """Return column keys as a list of strings."""

    if not isinstance(columns, list):
        return []
    out: list[str] = []
    for col in columns:
        if isinstance(col, str):
            out.append(col)
        elif isinstance(col, dict):
            key = col.get("key") or col.get("label")
            if key is not None:
                out.append(str(key))
    return out
