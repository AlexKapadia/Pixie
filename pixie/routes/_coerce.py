"""Form-data coercion to typed input dicts.

The browser submits ``application/x-www-form-urlencoded`` form data via htmx.
Most inputs render to a single named ``<input>`` (text, number, slider,
checkbox, etc.). A subset of inputs use a hidden field that carries a
JSON-encoded value (see ``data-json-type="json"`` partials): ``slider``
with ``range:true``, ``multiselect``, ``tags``, ``json``, ``table``,
``date_range``, and all four ``map_*`` types.

``coerce_form`` walks the tool's ``InputSpec`` list and rebuilds a typed
dict from the raw form-encoded mapping. The result is suitable for direct
validation against the tool's input pydantic model. Type ambiguity
(strings-from-HTML) is resolved per-input by the type's known shape.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from pixie.discovery import (
    AudioInput,
    CheckboxInput,
    ColourInput,
    DateInput,
    DateRangeInput,
    DatetimeInput,
    FileInput,
    HiddenInput,
    ImageInput,
    InputSpec,
    JsonInput,
    MapBboxInput,
    MapMultipointInput,
    MapPointInput,
    MapPolygonInput,
    MarkdownInput,
    MultiselectInput,
    NumberInput,
    SelectInput,
    SliderInput,
    TableInput,
    TagsInput,
    TextInput,
    TextareaInput,
    TimeInput,
    ToggleInput,
)

JSON_BRIDGED_TYPES: frozenset[str] = frozenset(
    {
        "multiselect",
        "tags",
        "json",
        "table",
        "date_range",
        "map_point",
        "map_bbox",
        "map_polygon",
        "map_multipoint",
    }
)


def _option_value_type(spec: SelectInput) -> type:
    """Infer the actual Python type from the schema's first option value."""

    if not spec.options:
        return str
    first = spec.options[0].value
    return type(first)


def _coerce_to_type(target: type, raw: str) -> Any:
    """Convert a string form value to the schema-declared option type."""

    if target is bool:
        # The browser submits "true"/"false"/"on"/"off" depending on widget;
        # accept any truthy spelling.
        if raw.lower() in {"true", "on", "1", "yes"}:
            return True
        if raw.lower() in {"false", "off", "0", "no", ""}:
            return False
        return bool(raw)
    if target is int:
        try:
            return int(raw)
        except ValueError:
            return int(float(raw))
    if target is float:
        return float(raw)
    return raw


def _coerce_one(spec: InputSpec, raw: str | list[str] | None) -> Any:
    """Coerce a single form value (or list-of-values) for one input."""

    if raw is None:
        return None

    # JSON-bridged inputs always submit a JSON string in a single field.
    if spec.type in JSON_BRIDGED_TYPES:
        text = raw if isinstance(raw, str) else (raw[0] if raw else "")
        if text == "":
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    # Slider with range:true is in JSON_BRIDGED_TYPES via the partial,
    # but the discriminator class is SliderInput, not "range". Catch it:
    if isinstance(spec, SliderInput) and spec.range:
        text = raw if isinstance(raw, str) else (raw[0] if raw else "")
        try:
            return json.loads(text) if text else None
        except json.JSONDecodeError:
            return None

    text = raw if isinstance(raw, str) else (raw[0] if raw else "")

    if isinstance(spec, NumberInput):
        if text == "":
            return None
        try:
            value = float(text)
            return int(value) if value.is_integer() and (spec.step is None or float(spec.step).is_integer()) else value
        except ValueError:
            return None

    if isinstance(spec, SliderInput):
        if text == "":
            return None
        try:
            return float(text)
        except ValueError:
            return None

    if isinstance(spec, (CheckboxInput, ToggleInput)):
        # Unchecked checkboxes/toggles are absent; presence means True.
        return _coerce_to_type(bool, text)

    if isinstance(spec, SelectInput):
        if text == "":
            return None
        return _coerce_to_type(_option_value_type(spec), text)

    if isinstance(spec, (TextInput, TextareaInput, DateInput, TimeInput,
                          DatetimeInput, ColourInput, MarkdownInput,
                          HiddenInput)):
        return text

    if isinstance(spec, (FileInput, ImageInput, AudioInput)):
        # Multipart inputs are handled separately by the route handler;
        # fall through to the raw value for now (None if not present).
        return text or None

    # Default: return text as-is.
    return text


def coerce_form(
    inputs: list[InputSpec], form_data: Mapping[str, Any]
) -> dict[str, Any]:
    """Walk a tool's input schema and produce a typed dict from the raw form.

    ``form_data`` is what FastAPI hands back from ``await request.form()``
    or ``request.form().multi_items()`` — a multi-dict-like mapping where
    keys may repeat (for multi-value fields). We pick ``getlist`` if
    available, else fall back to a single ``.get``.
    """

    getlist = getattr(form_data, "getlist", None)
    out: dict[str, Any] = {}
    for spec in inputs:
        raw: Any
        if getlist is not None:
            many = getlist(spec.key)
            if not many:
                raw = None
            elif len(many) == 1:
                raw = many[0]
            else:
                raw = many
        else:
            raw = form_data.get(spec.key)

        # Special-case: an unchecked checkbox is *absent* from form data.
        # The browser only submits checked checkboxes.
        if raw is None and isinstance(spec, (CheckboxInput, ToggleInput)):
            out[spec.key] = False
            continue

        # multiselect arrives as repeated form values OR as a JSON-bridged
        # hidden field. The hidden-field path is handled above; the repeated-
        # values path lands here.
        if isinstance(spec, MultiselectInput) and isinstance(raw, list):
            out[spec.key] = raw
            continue

        coerced = _coerce_one(spec, raw)
        # Skip omitted optional fields entirely so pydantic defaults apply.
        if coerced is None and not spec.required:
            if spec.default is not None:
                out[spec.key] = spec.default
            continue
        out[spec.key] = coerced
    return out


__all__ = ["coerce_form", "JSON_BRIDGED_TYPES"]
