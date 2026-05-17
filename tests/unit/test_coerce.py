"""Unit tests for ``pixie.routes._coerce``."""

from __future__ import annotations

import json

import pytest

from pixie.discovery import (
    CheckboxInput,
    JsonInput,
    MultiselectInput,
    NumberInput,
    SelectInput,
    SelectOption,
    SliderInput,
    TableInput,
    TagsInput,
    TextInput,
    TextareaInput,
    ToggleInput,
)
from pixie.routes._coerce import (
    JSON_BRIDGED_TYPES,
    _coerce_one,
    _coerce_to_type,
    coerce_form,
)


class _MultiDict(dict):
    def getlist(self, key):
        v = self.get(key)
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return [v]


def test_json_bridged_types_constants() -> None:
    for t in ("multiselect", "tags", "json", "table",
              "date_range", "map_point", "map_bbox",
              "map_polygon", "map_multipoint"):
        assert t in JSON_BRIDGED_TYPES


def test_coerce_to_type_bool_truthy() -> None:
    assert _coerce_to_type(bool, "true") is True
    assert _coerce_to_type(bool, "on") is True
    assert _coerce_to_type(bool, "1") is True
    assert _coerce_to_type(bool, "yes") is True


def test_coerce_to_type_bool_falsy() -> None:
    assert _coerce_to_type(bool, "false") is False
    assert _coerce_to_type(bool, "off") is False
    assert _coerce_to_type(bool, "") is False


def test_coerce_to_type_int_via_float() -> None:
    assert _coerce_to_type(int, "3.0") == 3


def test_coerce_one_number_returns_int_for_int_steps() -> None:
    spec = NumberInput(key="n", type="number", label="N", step=1, default=0)
    assert _coerce_one(spec, "5") == 5


def test_coerce_one_number_returns_float() -> None:
    spec = NumberInput(key="n", type="number", label="N", step=0.1, default=0)
    out = _coerce_one(spec, "5.5")
    assert out == 5.5


def test_coerce_one_number_empty_returns_none() -> None:
    spec = NumberInput(key="n", type="number", label="N", default=0)
    assert _coerce_one(spec, "") is None


def test_coerce_one_number_invalid_returns_none() -> None:
    spec = NumberInput(key="n", type="number", label="N", default=0)
    assert _coerce_one(spec, "abc") is None


def test_coerce_one_slider_returns_float() -> None:
    spec = SliderInput(key="s", type="slider", label="S",
                       min=0, max=100, default=50)
    assert _coerce_one(spec, "75") == 75.0


def test_coerce_one_slider_range_parses_json() -> None:
    spec = SliderInput(key="s", type="slider", label="S",
                       min=0, max=100, default=[0, 100], range=True)
    out = _coerce_one(spec, "[10, 50]")
    assert out == [10, 50]


def test_coerce_one_select_uses_option_type() -> None:
    spec = SelectInput(
        key="s", type="select", label="S",
        options=[SelectOption(value=1, label="one"),
                  SelectOption(value=2, label="two")],
    )
    assert _coerce_one(spec, "2") == 2


def test_coerce_one_select_empty_returns_none() -> None:
    spec = SelectInput(key="s", type="select", label="S",
                       options=[SelectOption(value="a", label="A")])
    assert _coerce_one(spec, "") is None


def test_coerce_one_text() -> None:
    spec = TextInput(key="t", type="text", label="T")
    assert _coerce_one(spec, "hello") == "hello"


def test_coerce_one_textarea() -> None:
    spec = TextareaInput(key="t", type="textarea", label="T")
    assert _coerce_one(spec, "multi\nline") == "multi\nline"


def test_coerce_one_json_bridged_value() -> None:
    spec = JsonInput(key="j", type="json", label="J", default={})
    out = _coerce_one(spec, '{"a": 1}')
    assert out == {"a": 1}


def test_coerce_one_json_bridged_invalid_returns_raw_text() -> None:
    spec = JsonInput(key="j", type="json", label="J", default={})
    out = _coerce_one(spec, "garbled")
    assert out == "garbled"


def test_coerce_one_json_bridged_empty_returns_none() -> None:
    spec = JsonInput(key="j", type="json", label="J", default={})
    assert _coerce_one(spec, "") is None


def test_coerce_one_tags_parses_json_array() -> None:
    spec = TagsInput(key="tg", type="tags", label="Tags", default=[])
    out = _coerce_one(spec, '["a", "b"]')
    assert out == ["a", "b"]


def test_coerce_one_table_parses_json() -> None:
    spec = TableInput(key="t", type="table", label="T",
                      columns=[{"key": "a", "label": "A", "type": "text"}],
                      default=[])
    out = _coerce_one(spec, '[{"a": 1}]')
    assert out == [{"a": 1}]


def test_coerce_one_checkbox_returns_bool() -> None:
    spec = CheckboxInput(key="c", type="checkbox", label="C", default=False)
    assert _coerce_one(spec, "true") is True


def test_coerce_one_toggle_returns_bool() -> None:
    spec = ToggleInput(key="c", type="toggle", label="C", default=False)
    assert _coerce_one(spec, "on") is True


def test_coerce_one_none_returns_none() -> None:
    spec = TextInput(key="t", type="text", label="T")
    assert _coerce_one(spec, None) is None


# --- coerce_form ----------------------------------------------------------


def test_coerce_form_unchecked_checkbox_is_false() -> None:
    inputs = [CheckboxInput(key="c", type="checkbox", label="C", default=False)]
    out = coerce_form(inputs, _MultiDict({}))
    assert out["c"] is False


def test_coerce_form_unchecked_toggle_is_false() -> None:
    inputs = [ToggleInput(key="c", type="toggle", label="C", default=False)]
    out = coerce_form(inputs, _MultiDict({}))
    assert out["c"] is False


def test_coerce_form_applies_defaults_for_omitted_optional() -> None:
    inputs = [TextInput(key="t", type="text", label="T", default="hello", required=False)]
    out = coerce_form(inputs, _MultiDict({}))
    assert out["t"] == "hello"


def test_coerce_form_skips_optional_with_no_default() -> None:
    inputs = [TextInput(key="t", type="text", label="T", required=False)]
    out = coerce_form(inputs, _MultiDict({}))
    assert "t" not in out


def test_coerce_form_multiselect_repeated_values() -> None:
    inputs = [MultiselectInput(
        key="m", type="multiselect", label="M",
        options=[SelectOption(value="a", label="A"),
                  SelectOption(value="b", label="B")],
        default=[],
    )]
    out = coerce_form(inputs, _MultiDict({"m": ["a", "b"]}))
    assert out["m"] == ["a", "b"]


def test_coerce_form_with_typed_number() -> None:
    inputs = [NumberInput(key="n", type="number", label="N", default=0)]
    out = coerce_form(inputs, _MultiDict({"n": "42"}))
    assert out["n"] == 42


def test_coerce_form_with_select() -> None:
    inputs = [SelectInput(
        key="s", type="select", label="S",
        options=[SelectOption(value="x", label="X")],
    )]
    out = coerce_form(inputs, _MultiDict({"s": "x"}))
    assert out["s"] == "x"
