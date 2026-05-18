"""Gap tests for ``pixie.renderer.outputs`` — layouts, panel ids, tabs."""

from __future__ import annotations

from typing import Any

import pytest
from markupsafe import Markup

from pixie.renderer.outputs import (
    _escape,
    _panel_id,
    _spec_dict,
    _tojson_safe,
    render_output,
    render_outputs,
)


def _spec(key: str, type_: str = "text", layout: str = "panel", **extra) -> dict:
    return {"key": key, "type": type_, "label": key.title(), "layout": layout, **extra}


def test_panel_id_slugifies() -> None:
    assert _panel_id("hello world") == "out-hello-world"
    assert _panel_id("a/b\\c") == "out-a-b-c"


def test_tojson_safe_strips_control_chars() -> None:
    out = _tojson_safe({"x": "a\x00b\x1fc"})
    assert "\x00" not in out
    assert "\x1f" not in out


def test_tojson_safe_handles_non_serialisable() -> None:
    out = _tojson_safe(object())
    assert isinstance(out, str)


def test_spec_dict_from_dict_passthrough() -> None:
    assert _spec_dict({"key": "x", "type": "text", "label": "X"})["key"] == "x"


def test_spec_dict_from_pydantic_object() -> None:
    from pixie.discovery import OutputSpec, TextOutput
    spec = TextOutput(key="x", type="text", label="X")
    out = _spec_dict(spec)
    assert out["key"] == "x"


def test_escape_returns_safe_text() -> None:
    out = _escape("<b>x</b>")
    assert "&lt;" in out


def test_render_output_text_value() -> None:
    out = render_output(_spec("greeting"), value="hello")
    assert isinstance(out, Markup)
    assert "hello" in str(out)


def test_render_output_unknown_type_falls_back_to_text() -> None:
    out = render_output(_spec("x", type_="no_such_type"), value="hello")
    assert isinstance(out, Markup)


def test_render_outputs_empty_spec_list_returns_empty_state() -> None:
    out = render_outputs([])
    assert "output-empty" in str(out)


def test_render_outputs_renders_default_panel_layout() -> None:
    specs = [_spec("a", "text"), _spec("b", "text")]
    out = render_outputs(specs, {"a": "hi", "b": "yo"})
    s = str(out)
    assert "output-stack" in s
    assert "hi" in s and "yo" in s


def test_render_outputs_renders_tabs_layout() -> None:
    specs = [_spec("a", "text", layout="tab"),
              _spec("b", "text", layout="tab")]
    out = render_outputs(specs, {"a": "x", "b": "y"})
    s = str(out)
    assert "output-tabs" in s


def test_render_outputs_renders_inline_layout() -> None:
    specs = [_spec("a", "text", layout="inline"),
              _spec("b", "text", layout="inline")]
    out = render_outputs(specs, {"a": "x", "b": "y"})
    s = str(out)
    assert "output-inline" in s


def test_render_outputs_single_tab_falls_back_to_normal() -> None:
    specs = [_spec("a", "text", layout="tab")]
    out = render_outputs(specs, {"a": "x"})
    # single tab => simple render (no tabs strip)
    assert "x" in str(out)


def test_render_outputs_mixed_layouts_groups_correctly() -> None:
    specs = [
        _spec("a", "text", layout="panel"),
        _spec("b", "text", layout="inline"),
        _spec("c", "text", layout="inline"),
        _spec("d", "text", layout="panel"),
    ]
    out = render_outputs(specs, {"a": "1", "b": "2", "c": "3", "d": "4"})
    s = str(out)
    assert "output-inline" in s
    assert "output-stack" in s


def test_render_outputs_none_values_renders_empty_states() -> None:
    specs = [_spec("a", "text"), _spec("b", "text")]
    out = render_outputs(specs, None)
    s = str(out)
    # The renderer still emits panels.
    assert "output-stack" in s
