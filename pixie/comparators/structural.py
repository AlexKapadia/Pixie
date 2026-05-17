"""Boolean, key-value, and tree comparators."""

from __future__ import annotations

import math
from typing import Any

from pixie.comparators._base import Diff


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numbers_close(a: float, b: float, rtol: float, atol: float) -> bool:
    if math.isnan(a) and math.isnan(b):
        return True
    if math.isnan(a) or math.isnan(b):
        return False
    return math.isclose(a, b, rel_tol=rtol, abs_tol=atol)


def compare_boolean(
    output_key: str,
    output_type: str,
    expected: Any,
    actual: Any,
    tolerance: dict[str, Any],
) -> Diff | None:
    """Strict boolean equality."""

    exp = expected.get("value") if isinstance(expected, dict) and "value" in expected else expected
    act = actual.get("value") if isinstance(actual, dict) and "value" in actual else actual
    if isinstance(exp, bool) and isinstance(act, bool) and exp == act:
        return None
    return Diff(
        output_key=output_key, output_type=output_type,
        comparator="eq",
        expected=exp, actual=act,
        metric=f"expected={exp!r}, actual={act!r}",
    )


def compare_kv(
    output_key: str,
    output_type: str,
    expected: Any,
    actual: Any,
    tolerance: dict[str, Any],
) -> Diff | None:
    """Compare a key-value object dict.

    Accepts either ``{pairs: {...}}`` (canonical) or a raw dict.
    """

    exp_dict = expected.get("pairs", expected) if isinstance(expected, dict) else expected
    act_dict = actual.get("pairs", actual) if isinstance(actual, dict) else actual

    if not isinstance(exp_dict, dict) or not isinstance(act_dict, dict):
        return Diff(
            output_key=output_key, output_type=output_type, comparator="dict_per_value",
            expected=expected, actual=actual,
            metric=f"non-dict kv ({type(exp_dict).__name__} vs {type(act_dict).__name__})",
        )

    allow_extra = bool(tolerance.get("allow_extra", False))
    rtol = float(tolerance.get("float_rtol", 1.0e-6))
    atol = float(tolerance.get("float_atol", 1.0e-9))

    missing = sorted(set(exp_dict) - set(act_dict))
    extra = sorted(set(act_dict) - set(exp_dict))
    if missing:
        return Diff(
            output_key=output_key, output_type=output_type, comparator="dict_per_value",
            expected=exp_dict, actual=act_dict,
            metric=f"missing key(s) in actual: {missing}",
        )
    if extra and not allow_extra:
        return Diff(
            output_key=output_key, output_type=output_type, comparator="dict_per_value",
            expected=exp_dict, actual=act_dict,
            metric=f"unexpected extra key(s) in actual: {extra}",
        )

    for key in exp_dict:
        ev = exp_dict[key]
        av = act_dict[key]
        if _is_number(ev) and _is_number(av):
            if _numbers_close(float(ev), float(av), rtol, atol):
                continue
            return Diff(
                output_key=output_key, output_type=output_type, comparator="dict_per_value",
                expected=ev, actual=av, path=key,
                metric=f"key {key!r}: numbers differ ({ev} vs {av})",
            )
        if ev != av:
            return Diff(
                output_key=output_key, output_type=output_type, comparator="dict_per_value",
                expected=ev, actual=av, path=key,
                metric=f"key {key!r}: values differ ({ev!r} vs {av!r})",
            )
    return None


def compare_tree(
    output_key: str,
    output_type: str,
    expected: Any,
    actual: Any,
    tolerance: dict[str, Any],
) -> Diff | None:
    """Compare two trees structurally (recursive).

    A "tree" here is a dict with ``id`` or ``name`` and an optional
    ``children`` list. Children may be matched ordered or set-keyed by
    the child node's identifier per ``tolerance.children_order``.
    """

    exp_root = expected.get("root", expected) if isinstance(expected, dict) else expected
    act_root = actual.get("root", actual) if isinstance(actual, dict) else actual
    ordered = tolerance.get("children_order", "unordered") == "ordered"

    diff_msg = _tree_walk(exp_root, act_root, ordered=ordered, path="/")
    if diff_msg is None:
        return None
    return Diff(
        output_key=output_key, output_type=output_type, comparator="tree_structural",
        expected=exp_root, actual=act_root, metric=diff_msg,
    )


def _node_id(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("id") or node.get("name") or "")
    return str(node)


def _tree_walk(exp: Any, act: Any, *, ordered: bool, path: str) -> str | None:
    if not isinstance(exp, dict) or not isinstance(act, dict):
        if exp == act:
            return None
        return f"node {path!r}: leaf mismatch ({exp!r} vs {act!r})"
    if _node_id(exp) != _node_id(act):
        return f"node {path!r}: id mismatch ({_node_id(exp)!r} vs {_node_id(act)!r})"

    exp_children = exp.get("children") or []
    act_children = act.get("children") or []
    if len(exp_children) != len(act_children):
        return (
            f"node {path!r}: child count differs "
            f"({len(exp_children)} vs {len(act_children)})"
        )

    if ordered:
        for index, (e_child, a_child) in enumerate(zip(exp_children, act_children)):
            sub = _tree_walk(e_child, a_child, ordered=True, path=f"{path}{index}/")
            if sub is not None:
                return sub
        return None

    # unordered: match children by id
    act_by_id = {_node_id(c): c for c in act_children}
    for e_child in exp_children:
        child_id = _node_id(e_child)
        if child_id not in act_by_id:
            return f"node {path!r}: child {child_id!r} missing in actual"
        sub = _tree_walk(
            e_child, act_by_id[child_id], ordered=False, path=f"{path}{child_id}/"
        )
        if sub is not None:
            return sub
    return None
