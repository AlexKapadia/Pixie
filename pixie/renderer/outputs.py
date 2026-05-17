"""Output rendering — schema-driven dispatch to Jinja per-type partials.

Every output type in ``discovery.py`` has a matching partial under
``pixie/templates/partials/outputs/<type>.html``. This module renders
each spec by handing it (plus optional value) to its partial. The
empty-state hint panel (DESIGN_SPEC.md s13) is used when ``values`` is
``None`` and the tool has not yet run.

Layout grouping respects each output's ``layout`` field:

- ``panel`` (default) — stacked cards.
- ``tab`` — consecutive ``tab`` outputs are grouped into an ``OutputTabs``
  strip (DESIGN_SPEC.md s10).
- ``inline`` — consecutive ``inline`` outputs sit side-by-side in a flex row.

Each rendered card carries ``data-output-key`` and ``data-output-type``
so SSE streaming code (Phase 4d) can locate the right panel via
``[data-output-key="<key>"]``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from pixie.config import get_settings

logger = logging.getLogger("pixie.renderer.outputs")


_ENV: Environment | None = None


def _env() -> Environment:
    """Lazy-build a Jinja environment scoped at the package templates dir."""

    global _ENV
    if _ENV is None:
        settings = get_settings()
        _ENV = Environment(
            loader=FileSystemLoader(str(settings.templates_dir)),
            autoescape=select_autoescape(["html", "htm", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        _ENV.filters["tojson_safe"] = _tojson_safe
        _ENV.globals["panel_id"] = _panel_id
    return _ENV


def _tojson_safe(value: Any) -> str:
    """Serialise to a JSON string safe for embedding inside a ``data-*`` attribute.

    We rely on Jinja's autoescape on the surrounding attribute quotes,
    but we still pre-strip control characters that some browsers reject
    inside attribute values.
    """

    try:
        s = json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        s = json.dumps(str(value))
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)


_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def _panel_id(key: str) -> str:
    """Stable DOM id for an output panel, derived from the schema key."""

    safe = _SLUG_RE.sub("-", str(key))
    return f"out-{safe}"


def _spec_dict(spec: Any) -> dict[str, Any]:
    """Normalise a Pydantic OutputSpec (or dict) to a plain dict for templates."""

    if hasattr(spec, "model_dump"):
        return spec.model_dump()  # type: ignore[no-any-return]
    if isinstance(spec, dict):
        return spec
    return {
        attr: getattr(spec, attr)
        for attr in dir(spec)
        if not attr.startswith("_") and not callable(getattr(spec, attr))
    }


def render_output(spec: Any, value: Any | None = None) -> Markup:
    """Render a single output spec to HTML by dispatching to its partial.

    A missing partial falls back to a ``text`` rendering of the value
    (rather than a build-time error) so a new output type added in
    ``discovery.py`` without a partial still surfaces something useful
    instead of an empty page.
    """

    spec_d = _spec_dict(spec)
    type_ = spec_d.get("type", "text")
    env = _env()
    template_name = f"partials/outputs/{type_}.html"
    try:
        template = env.get_template(template_name)
    except Exception as exc:
        logger.warning("no partial for output type %r (%s)", type_, exc)
        template = env.get_template("partials/outputs/text.html")
        if value is None:
            value = ""
        else:
            value = {"text": str(value)} if not isinstance(value, dict) else value
    has_value = value is not None
    rendered = template.render(
        spec=spec_d,
        value=value,
        has_value=has_value,
        panel_id=_panel_id(spec_d["key"]),
    )
    return Markup(rendered)


def render_outputs(
    specs: Iterable[Any], values: dict[str, Any] | None = None
) -> Markup:
    """Render every output spec respecting ``panel`` / ``tab`` / ``inline`` layouts.

    When ``values`` is ``None`` we still render every output's empty-state
    panel — they're useful as "what this tool will produce" affordances,
    and they make the streaming target ids exist before the first event.

    Returns an empty-state hint when the tool declares no outputs.
    """

    spec_list = list(specs)
    if not spec_list:
        return Markup(
            '<div class="output-empty" role="status" aria-live="polite">'
            '<span class="t-meta">This tool produces no outputs.</span>'
            "</div>"
        )

    values_map: dict[str, Any] = values or {}

    parts: list[str] = []
    # Group consecutive specs with the same layout to allow tab / inline runs.
    group: list[tuple[Any, dict[str, Any]]] = []
    group_layout: str | None = None

    def flush() -> None:
        if not group:
            return
        layout = group_layout or "panel"
        if layout == "tab":
            parts.append(_render_tabs(group, values_map))
        elif layout == "inline":
            parts.append(_render_inline(group, values_map))
        else:
            for spec, spec_d in group:
                parts.append(
                    str(render_output(spec, values_map.get(spec_d["key"])))
                )
        group.clear()

    for spec in spec_list:
        spec_d = _spec_dict(spec)
        layout = spec_d.get("layout", "panel") or "panel"
        if layout != group_layout and group:
            flush()
        group_layout = layout
        group.append((spec, spec_d))
    flush()

    return Markup(
        '<div class="output-stack" role="region" aria-label="Outputs">'
        + "".join(parts)
        + "</div>"
    )


def _render_tabs(
    group: list[tuple[Any, dict[str, Any]]], values_map: dict[str, Any]
) -> str:
    """Render a tab strip + panels for consecutive tab-layout outputs."""

    if len(group) == 1:
        spec, spec_d = group[0]
        return str(render_output(spec, values_map.get(spec_d["key"])))

    tabs_html: list[str] = []
    panels_html: list[str] = []
    for index, (spec, spec_d) in enumerate(group):
        active = "is-active" if index == 0 else ""
        tabs_html.append(
            f'<button type="button" role="tab" '
            f'class="output-tab {active}" '
            f'data-tab-target="{_panel_id(spec_d["key"])}-tab" '
            f'aria-selected="{"true" if index == 0 else "false"}">'
            f'{_escape(spec_d["label"])}'
            f"</button>"
        )
        hidden = "" if index == 0 else 'hidden style="display:none;"'
        panels_html.append(
            f'<div id="{_panel_id(spec_d["key"])}-tab" role="tabpanel" {hidden}>'
            f"{render_output(spec, values_map.get(spec_d['key']))}"
            f"</div>"
        )
    return (
        '<div class="output-tabs-wrap" data-pixie-tabs>'
        f'<div class="output-tabs" role="tablist">{"".join(tabs_html)}</div>'
        f'<div class="output-tabs__panels">{"".join(panels_html)}</div>'
        "</div>"
    )


def _render_inline(
    group: list[tuple[Any, dict[str, Any]]], values_map: dict[str, Any]
) -> str:
    """Render side-by-side panels for consecutive inline-layout outputs."""

    cells = [
        f'<div class="output-inline__cell">'
        f"{render_output(spec, values_map.get(spec_d['key']))}"
        f"</div>"
        for spec, spec_d in group
    ]
    return f'<div class="output-inline">{"".join(cells)}</div>'


def _escape(text: Any) -> str:
    """Minimal HTML escape for short label strings in renderer-built markup."""

    s = "" if text is None else str(text)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
