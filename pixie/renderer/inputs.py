"""Input rendering — dispatch each ``InputSpec`` to its Jinja partial.

The dispatcher loads ``pixie/templates/partials/inputs/<type>.html`` per
input type via a shared Jinja2 environment. Every partial receives the
``spec`` (a discriminated-union variant from ``pixie.discovery``), the
current ``value``, a stable ``field_id`` derived from ``spec.key``, and
``initial_json`` — a JSON-encoded representation of ``value`` used by
inputs that bind through Alpine.js (sliders, code/json editors, tags,
table, map_*).

``render_inputs`` wraps the full list in an Alpine ``x-data`` scope that
tracks every field by key. This lets ``show_if`` work without a server
round-trip: each conditional field is rendered with ``x-show`` against
the parent scope's ``values`` dictionary.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup

from pixie.discovery import InputSpec

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
PARTIALS_DIR = TEMPLATES_DIR / "partials" / "inputs"

# why: a dedicated environment keeps these partials independent from app-level
# globals (toasts, sidebar state) and skips a round-trip through templates.env.
_env = Environment(
    loader=FileSystemLoader(str(PARTIALS_DIR)),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.globals["tojsonattr"] = lambda v: json.dumps(v, ensure_ascii=True)


def _dump_options(opts: Any) -> list[dict[str, Any]]:
    """Serialise a list of Pydantic SelectOption to plain dicts for JSON."""

    return [o.model_dump() if hasattr(o, "model_dump") else dict(o) for o in opts]


_env.filters["dump_options"] = _dump_options


def _dump_pydantic(items: Any) -> list[dict[str, Any]]:
    """Serialise a list of Pydantic models (e.g. ColumnSpec) to plain dicts."""

    return [i.model_dump() if hasattr(i, "model_dump") else dict(i) for i in items]


_env.filters["dump_pydantic"] = _dump_pydantic

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _field_id(key: str) -> str:
    """Stable DOM id derived from the schema key."""

    cleaned = _SAFE_ID_RE.sub("-", key).strip("-")
    return f"f-{cleaned or 'field'}"


def _initial_value(spec: InputSpec, value: Any) -> Any:
    if value is not None:
        return value
    return getattr(spec, "default", None)


def _partial_name(type_: str) -> str:
    return f"{type_}.html"


def render_input(spec: InputSpec, value: Any = None) -> Markup:
    """Render a single ``InputSpec`` to HTML via its per-type partial."""

    type_ = getattr(spec, "type", None)
    if not type_:
        raise ValueError(f"input spec missing type: {spec!r}")
    try:
        template = _env.get_template(_partial_name(type_))
    except Exception as exc:
        raise ValueError(f"no partial for input type {type_!r}") from exc

    effective = _initial_value(spec, value)
    return Markup(
        template.render(
            spec=spec,
            value=effective,
            initial_json=json.dumps(effective, ensure_ascii=True),
            field_id=_field_id(spec.key),
        )
    )


def _group_specs(specs: list[InputSpec]) -> list[tuple[str | None, list[InputSpec]]]:
    """Group inputs by their ``group`` field, preserving JSON order."""

    groups: list[tuple[str | None, list[InputSpec]]] = []
    current: tuple[str | None, list[InputSpec]] | None = None
    for spec in specs:
        group_name = getattr(spec, "group", None)
        if current is None or current[0] != group_name:
            current = (group_name, [])
            groups.append(current)
        current[1].append(spec)
    return groups


def _values_for_scope(
    specs: list[InputSpec], values: dict[str, Any]
) -> dict[str, Any]:
    """Build the initial ``values`` map for the form's Alpine scope."""

    out: dict[str, Any] = {}
    for spec in specs:
        out[spec.key] = _initial_value(spec, values.get(spec.key))
    return out


def render_inputs(
    specs: Iterable[InputSpec], values: dict[str, Any] | None = None
) -> Markup:
    """Render every ``InputSpec`` and wrap them in an Alpine ``x-data`` scope.

    The wrapping ``<div>`` carries an ``x-data`` dictionary so per-input
    ``show_if`` clauses can read sibling values without a round-trip.
    """

    spec_list = list(specs)
    values = values or {}
    scope = _values_for_scope(spec_list, values)
    scope_attr = json.dumps({"values": scope}, ensure_ascii=True)

    parts: list[str] = [
        f'<div class="input-form" x-data=\'{scope_attr}\'>'
    ]
    for group_name, group_specs in _group_specs(spec_list):
        if group_name:
            parts.append(
                '<div class="input-form__group-head">'
                f'<span class="t-eyebrow">{group_name}</span>'
                '</div>'
            )
        for spec in group_specs:
            parts.append(str(render_input(spec, values.get(spec.key))))
    parts.append("</div>")
    return Markup("".join(parts))
