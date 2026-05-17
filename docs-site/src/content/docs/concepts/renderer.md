---
title: Schema-driven UI
description: How tool.json becomes HTML, how the renderer dispatches, and how to add a new type.
sidebar:
  order: 4
---

Pixie has no tool-specific frontend code. Every tool's UI is generated from
its `tool.json` schema. This is the single most important design decision
in the codebase.

## The pipeline

```text
tool.json (on disk)
   │
   ▼
discovery.py        ── Pydantic parse → DiscoveredTool
   │
   ▼
renderer/inputs.py  ── for input in schema.inputs:
                          partial = inputs/<type>.html
                          ctx = {spec, prefilled_value, name_attr}
                          yield render_partial(partial, ctx)
   │
   ▼
templates/tool.html ── lays out the form, output panel, headers
   │
   ▼
Browser (htmx + Alpine) ── submits form, swaps output panel
                            ▲
                            │
renderer/outputs.py ── for key, value in response:
                          partial = outputs/<type>.html
                          yield render_partial(partial, {spec, value})
```

The browser never knows which tool it's looking at — every interaction is a
form post or an htmx swap. There's no router, no client state, no SPA. If
htmx fails to load, Pixie still works (the form posts via standard HTML
form submission and the page navigates).

## The partial dispatch

`renderer/inputs.py` is essentially:

```python
PARTIAL = {
    "text": "inputs/text.html",
    "textarea": "inputs/textarea.html",
    "number": "inputs/number.html",
    "slider": "inputs/slider.html",
    "select": "inputs/select.html",
    "multiselect": "inputs/multiselect.html",
    # ... 25 types total
}

def render_input(spec: InputSpec, value: Any) -> str:
    partial = PARTIAL[spec.type]
    return template_env.get_template(partial).render(
        spec=spec, value=value, name_attr=spec.key
    )
```

Outputs mirror this with their own partial map. The dispatch table is the
**only** place that needs to change to add a new type.

## What each partial looks like

Inputs are kept boring. A `select` partial is:

```jinja
<label class="form-label">
  {{ spec.label }}
  {% if spec.description %}<small>{{ spec.description }}</small>{% endif %}
</label>
<select
  name="{{ name_attr }}"
  class="form-input"
  {% if spec.searchable %}x-data="searchSelect()"{% endif %}
  {% if spec.show_if %}x-show="{{ spec.show_if.key }} == {{ spec.show_if.equals | tojson }}"{% endif %}
>
  {% for opt in spec.options %}
    <option value="{{ opt.value }}" {% if opt.value == value %}selected{% endif %}>
      {{ opt.label }}
    </option>
  {% endfor %}
</select>
```

Outputs are similar — most are 10–40 lines of Jinja that pull `value` apart
and feed it into a Plotly chart, a Leaflet map, a `<table>`, an `<audio>`,
etc.

## Conditional visibility (`show_if`)

The renderer emits Alpine.js `x-show` bindings instead of doing server-side
filtering. When a user toggles an input that another input depends on,
visibility flips client-side — no round-trip.

```json
{
  "key": "advanced_temperature",
  "type": "slider",
  "label": "Temperature",
  "min": 0, "max": 2, "step": 0.1,
  "show_if": {"key": "mode", "equals": "advanced"}
}
```

The rendered HTML has `x-show="mode == 'advanced'"`. Alpine.js handles the
rest.

## The output panel

After a `POST /tool/<id>/run`, the route handler:

1. Calls `proxy.run_tool(tool, payload, run_id)` which forwards to the tool
   subprocess.
2. Receives the JSON response.
3. For each declared output key, dispatches to the matching `outputs/*.html`
   partial.
4. Returns the rendered HTML as the response body.

htmx swaps that HTML into `<div id="output-panel">`. Charts initialise via
inline `<script>` tags that call `Plotly.newPlot(...)`. Maps initialise via
Leaflet. The first paint typically lands within ~30 ms of the response.

## Streaming outputs

If any output declares `streaming: true`:

1. The initial `POST /run` returns the `run_id` and a placeholder.
2. The browser opens an SSE connection to `/tool/<id>/stream?run_id=<id>`.
3. Pixie proxies events from the tool's own `/stream` endpoint.
4. Each event is `{output_key, value, done}` — htmx's SSE extension applies
   it via a small JS hook that knows how to append `stream_text`, update
   a chart series, etc.

See [Streaming outputs](/Pixie/build/streaming/) for the implementation
guide.

## Adding a new input or output type

Three steps:

1. **Add the Pydantic class** in `discovery.py`:
   ```python
   class FrequencyInput(_InputBase):
       type: Literal["frequency"]
       min_hz: float = 20.0
       max_hz: float = 20000.0
   ```
   Add it to the discriminated `InputSpec` union.

2. **Add the partial** at `templates/partials/inputs/frequency.html`. Keep
   it under 40 lines; use Tailwind classes you can copy from neighbouring
   partials.

3. **Add the dispatch entry** in `renderer/inputs.py`:
   ```python
   PARTIAL["frequency"] = "inputs/frequency.html"
   ```

4. **Add a sample-input rule** to `validator._INPUT_DEFAULTS` so the
   validator can synthesise one when no `default` is given.

That's the whole "add a new input type" workflow. The same shape applies to
outputs — partial, dispatch entry, output requirements entry in
`_OUTPUT_OBJECT_REQUIREMENTS`.

Read more: [Contributing → adding a new input/output type](/Pixie/contributing/new-type/).

## Why no JavaScript framework

React, Vue, and Svelte all want to own the page. They want to render their
own components, manage their own state, route their own clicks. That works
beautifully when the whole product is one app; it's a tax when the product
is a renderer that does nothing but turn schemas into HTML.

Htmx + Alpine + server-rendered Jinja:

- The contract is HTML over the wire.
- State lives where it logically lives (forms on the server, transient UI
  state on the client).
- There's no build step. Editing a partial is editing a file.
- The bundle is ~20 KB (htmx) + ~30 KB (Alpine) + Plotly/Leaflet from CDN.

Tools never write frontend code, period. If something a tool produces needs
custom interactivity (zoomable charts, draggable map points, code-editor
syntax highlighting), it's the renderer's job to provide that, once, in a
shared partial.
