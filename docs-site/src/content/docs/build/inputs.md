---
title: Input types
description: Every input type with type-specific fields, examples, and the sample value the validator generates.
sidebar:
  order: 4
---

Every input is a JSON object in the `inputs` array of `tool.json`. All
inputs share these **base fields**:

| Field         | Type                                | Required | Notes                                                              |
| ------------- | ----------------------------------- | -------- | ------------------------------------------------------------------ |
| `key`         | `string`                            | yes      | Becomes the dict key in the `/run` body. Unique within `inputs`.   |
| `type`        | one of the types below              | yes      | Discriminator.                                                     |
| `label`       | `string`                            | yes      | Shown above the input. Sentence case.                              |
| `description` | `string`                            | no       | Help text below the label.                                         |
| `default`     | type-appropriate                    | no       | Pre-fills the form; used by the validator's sample input.          |
| `required`    | `bool`                              | no       | Defaults to `true`. If `false`, may be omitted from `/run` body.   |
| `group`       | `string`                            | no       | Inputs sharing a `group` are rendered under one heading.           |
| `show_if`     | `{key, equals}`                     | no       | Hide unless another input's value matches. Client-side via Alpine. |

## Type catalog

| Type             | Type-specific fields                                  | Sample value the validator generates                 |
| ---------------- | ----------------------------------------------------- | ---------------------------------------------------- |
| `text`           | `placeholder`, `max_length`                           | `""`                                                 |
| `textarea`       | `placeholder`, `max_length`, `monospace` (bool)       | `""`                                                 |
| `number`         | `min`, `max`, `step`, `unit`                          | `(min+max)/2` or `0`                                 |
| `slider`         | `min` (req), `max` (req), `step`, `range` (bool)      | `(min+max)/2`, or `[min, max]` if `range`            |
| `select`         | `options[{value,label}]` (req), `searchable` (bool)   | `options[0].value`                                   |
| `multiselect`    | `options[{value,label}]` (req)                        | `[]`                                                 |
| `checkbox`       | —                                                     | `false`                                              |
| `toggle`         | —                                                     | `false`                                              |
| `radio`          | `options[{value,label}]` (req)                        | `options[0].value`                                   |
| `date`           | `min`, `max`                                          | today                                                |
| `time`           | —                                                     | `"00:00"`                                            |
| `datetime`       | —                                                     | now                                                  |
| `date_range`     | —                                                     | `[today, today]`                                     |
| `file`           | `accept`, `max_size_mb`, `multiple` (bool)            | 1×1 transparent PNG as data URL                      |
| `image`          | `max_size_mb`, `multiple` (bool)                      | 1×1 transparent PNG as data URL                      |
| `audio`          | `max_size_mb`                                         | 1 s silent WAV as data URL                           |
| `colour`         | —                                                     | `"#000000"`                                          |
| `json`           | `schema` (optional JSON Schema)                       | `{}`                                                 |
| `code`           | `language` (python, sql, js, html, json, plain)       | `""`                                                 |
| `markdown`       | —                                                     | `""`                                                 |
| `tags`           | `suggestions: [string]`                               | `[]`                                                 |
| `autocomplete`   | `endpoint` (req — tool-internal URL like `/autocomplete/cities`) | `""`                                       |
| `table`          | `columns: [{key,label,type}]`, `min_rows`, `max_rows` | `[]`                                                 |
| `map_point`      | `default_center: [lat,lng]`, `default_zoom`           | `[0, 0]` or `default_center`                         |
| `map_bbox`       | `default_center`, `default_zoom`                      | small box around centre                              |
| `map_polygon`    | `default_center`, `default_zoom`                      | `[[lat, lng]]`                                       |
| `map_multipoint` | `default_center`, `default_zoom`                      | `[[lat, lng]]`                                       |
| `hidden`         | —                                                     | `default` (must be present, or check 3 fails)        |

## Worked examples

### `slider` with range

```json
{
  "key": "wavelength_band",
  "type": "slider",
  "label": "Wavelength band (nm)",
  "min": 380,
  "max": 750,
  "step": 5,
  "range": true,
  "default": [450, 650]
}
```

Renders a double-handle slider. The `/run` body receives `wavelength_band:
[450, 650]`.

### `select` with searchable options

```json
{
  "key": "country",
  "type": "select",
  "label": "Country",
  "searchable": true,
  "options": [
    {"value": "GB", "label": "United Kingdom"},
    {"value": "US", "label": "United States"},
    {"value": "DE", "label": "Germany"}
  ],
  "default": "GB"
}
```

### `file` accepting CSVs

```json
{
  "key": "prices_csv",
  "type": "file",
  "label": "Historic prices (CSV)",
  "accept": ".csv,text/csv",
  "max_size_mb": 10
}
```

The body receives `prices_csv` as a base64-encoded data URL string
(`"data:text/csv;base64,...."`). Decode in `main.py`:

```python
import base64, io, pandas as pd

@app.post("/run")
async def run(body: RunInput) -> RunOutput:
    header, b64 = body.prices_csv.split(",", 1)
    df = pd.read_csv(io.BytesIO(base64.b64decode(b64)))
    ...
```

### `image` for vision tools

```json
{
  "key": "input_image",
  "type": "image",
  "label": "Input image",
  "max_size_mb": 8
}
```

Same data-URL encoding; decode with PIL:

```python
from PIL import Image
import base64, io

img = Image.open(io.BytesIO(base64.b64decode(body.input_image.split(",", 1)[1])))
```

### `table` for tabular input

```json
{
  "key": "assets",
  "type": "table",
  "label": "Portfolio assets",
  "columns": [
    {"key": "ticker", "label": "Ticker",      "type": "text"},
    {"key": "weight", "label": "Weight (%)",  "type": "number"}
  ],
  "min_rows": 2,
  "max_rows": 20
}
```

Body receives `assets: [{ticker: "AAPL", weight: 30}, ...]`.

### `autocomplete` against a tool-internal endpoint

```json
{
  "key": "city",
  "type": "autocomplete",
  "label": "City",
  "endpoint": "/autocomplete/cities"
}
```

Your tool must implement `GET /autocomplete/cities?q=<query>` returning
a JSON array of `{value, label}` items:

```python
@app.get("/autocomplete/cities")
async def autocomplete_cities(q: str):
    matches = [c for c in CITIES if q.lower() in c["label"].lower()][:10]
    return matches
```

Don't forget to declare `provides_autocomplete: true` in `tool.json`.

### `map_polygon` for area selection

```json
{
  "key": "study_area",
  "type": "map_polygon",
  "label": "Study area",
  "default_center": [51.5, -0.1],
  "default_zoom": 10
}
```

Body receives `study_area: [[lat1, lng1], [lat2, lng2], ...]`.

### `code` for tools that take a script

```json
{
  "key": "script",
  "type": "code",
  "label": "Python script",
  "language": "python",
  "default": "# write your code here\n"
}
```

Renders a CodeMirror editor with Python syntax highlighting.

### `show_if` for conditional inputs

```json
[
  {"key": "mode", "type": "select", "label": "Mode",
   "options": [{"value": "fast", "label": "Fast"}, {"value": "tuned", "label": "Tuned"}],
   "default": "fast"},

  {"key": "temperature", "type": "slider", "label": "Temperature",
   "min": 0, "max": 2, "step": 0.1, "default": 0.7,
   "show_if": {"key": "mode", "equals": "tuned"}}
]
```

`temperature` is hidden until the user picks `tuned`. No round-trip
— Alpine.js toggles visibility client-side.

## Notes on validation behaviour

- Inputs with `required: false` and no `default` are **omitted** from the
  validator's sample `/run` body — the validator tests the most-zero-effort
  happy path.
- For `layout: "chat"` the validator ignores declared inputs and sends a
  synthetic `{messages: [{role:"user", content:"Validation probe"}], history: []}`.
- `hidden` inputs require a `default`; check 3 fails otherwise.
