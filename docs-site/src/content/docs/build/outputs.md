---
title: Output types
description: Every output type with required value shape and an example response.
sidebar:
  order: 5
---

Outputs are JSON objects in the `outputs` array of `tool.json`. They share
these **base fields**:

| Field                       | Type                            | Required | Notes                                                                                |
| --------------------------- | ------------------------------- | -------- | ------------------------------------------------------------------------------------ |
| `key`                       | `string`                        | yes      | Becomes the response dict key.                                                       |
| `type`                      | one of the types below          | yes      | Discriminator.                                                                       |
| `label`                     | `string`                        | yes      | Shown above the output.                                                              |
| `description`               | `string`                        | no       | Help text.                                                                           |
| `caption`                   | `string`                        | no       | Small text under the value.                                                          |
| `unit`                      | `string`                        | no       | e.g. `"GBP"`, `"km"`, `"%"`.                                                         |
| `streaming`                 | `bool`                          | no       | Default `false`. If `true`, Pixie uses `/stream` instead of waiting on `/run`.       |
| `layout`                    | `"panel" \| "tab" \| "inline"`  | no       | Default `panel` (stacked). `tab` puts adjacent outputs into a tabset; `inline` row.  |
| `default_export_format`     | `string`                        | no       | Override the exporter's default (e.g. `"csv"` for a table).                          |
| `supported_export_formats`  | `list[string]`                  | no       | Restrict the export-as menu.                                                         |

## The big catalog

The validator's `_OUTPUT_OBJECT_REQUIREMENTS` map (see `validator.py`)
defines the **required value shape** per type. Anything missing fails
check 9; extras are warnings.

### Text & basic

| Type       | Required value keys              | Example response value                       |
| ---------- | -------------------------------- | -------------------------------------------- |
| `text`     | scalar string OR `{value}`       | `"Hello"` or `{"value": "Hello"}`            |
| `markdown` | scalar string OR `{value}`       | `"# Heading\n\nBody."`                       |
| `number`   | scalar OR `{value, format?, precision?}` | `42` or `{"value": 1234.5, "format": "currency", "precision": 2}` |
| `boolean`  | scalar bool OR `{value, true_label?, false_label?}` | `true`                            |
| `latex`    | scalar string                    | `"x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}"` |
| `code`     | scalar string OR `{value, language?}` | `{"value": "def foo(): pass", "language": "python"}` |
| `progress` | scalar `0..1` or `null`          | `0.75` or `null` (indeterminate)             |

### Structured

| Type    | Required keys                  | Example                                                                                                       |
| ------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| `table` | `columns`, `rows`              | `{"columns": [{"key":"x","label":"X","type":"number"}], "rows": [{"x": 1}, {"x": 2}], "downloadable": true}`  |
| `kv`    | `pairs`                        | `{"pairs": [{"key": "Sharpe", "value": 1.42}, {"key": "MaxDD", "value": "-12%"}]}`                            |
| `log`   | `lines`                        | `{"lines": [{"level":"info","message":"loaded","t":"2026-05-17T12:00:00Z"}, ...]}`                            |
| `diff`  | `before`, `after`              | `{"before": "old text", "after": "new text"}`                                                                  |
| `tree`  | `root`                         | `{"root": {"label": "/", "children": [{"label": "a", "children": []}]}}`                                       |
| `timeline` | `events`                    | `{"events": [{"t": "2026-01-01", "label": "Started"}, ...]}`                                                  |
| `gantt` | `tasks`                        | `{"tasks": [{"name": "Phase 1", "start": "2026-01-01", "end": "2026-02-01"}]}`                                |

### Charts (all rendered with Plotly)

| Type                | Required keys                                                                          |
| ------------------- | -------------------------------------------------------------------------------------- |
| `chart_line`        | `x: [number]`, `series: [{name, y: [number]}]` (plus `x_label`, `y_label`, `log_x`, `log_y`) |
| `chart_area`        | same as line                                                                           |
| `chart_bar`         | `x: [string]`, `series: [{name, y: [number]}]`                                         |
| `chart_scatter`     | `series: [{name, points: [{x, y, label?}]}]`                                           |
| `chart_pie`         | `slices: [{label, value}]`                                                             |
| `chart_histogram`   | `values: [number]`, `bins: number` (optional)                                          |
| `chart_boxplot`     | `series: [{name, values: [number]}]`                                                   |
| `chart_heatmap`     | `x_labels`, `y_labels`, `z: [[number]]`                                                |
| `chart_candlestick` | `points: [{t, open, high, low, close}]`                                                |
| `chart_radar`       | `axes: [string]`, `series: [{name, values: [number]}]`                                 |
| `chart_sankey`      | `nodes: [{id, label}]`, `links: [{source, target, value}]`                             |
| `chart_treemap`     | `nodes: [{id, label, value, parent?}]`                                                 |
| `chart_network`     | `nodes: [{id, label}]`, `edges: [{source, target, label?}]`                            |

### Maps (Leaflet)

| Type             | Required keys                                                                          |
| ---------------- | -------------------------------------------------------------------------------------- |
| `map_points`     | `points: [{lat, lng, label?, colour?}]` (plus `default_center`, `default_zoom`)        |
| `map_heatmap`    | `points: [{lat, lng, weight?}]`                                                        |
| `map_choropleth` | `geojson: object`, `values: {feature_id: number}`                                      |
| `map_polygons`   | `polygons: [{coords: [[lat, lng]], colour?, label?}]`                                  |
| `map_route`      | `points: [{lat, lng}]`                                                                 |

### Media

| Type            | Required keys                              |
| --------------- | ------------------------------------------ |
| `image`         | `value: string` (data URL or http URL)     |
| `image_grid`    | `images: [{value, label?}]`                |
| `image_compare` | `before: string`, `after: string`          |
| `audio`         | `value: string`                            |
| `video`         | `value: string`                            |
| `stream_text`   | `value: string` (appended over SSE)        |
| `file`          | `filename: string`, `data: string`, `mime_type: string` |

## Worked examples

### A formatted currency number

`tool.json`:
```json
{"key": "final_balance", "type": "number", "label": "Final balance",
 "unit": "GBP"}
```

Response value:
```json
{"final_balance": {"value": 25967.50, "format": "currency", "precision": 2}}
```

The renderer formats `£25,967.50`.

### A table with downloadable CSV

`tool.json`:
```json
{"key": "yearly", "type": "table", "label": "Year-by-year"}
```

Response value:
```json
{
  "yearly": {
    "columns": [
      {"key": "year",        "label": "Year",        "type": "number"},
      {"key": "contributions", "label": "Contributed", "type": "number"},
      {"key": "interest",    "label": "Interest",    "type": "number"},
      {"key": "balance",     "label": "Balance",     "type": "number"}
    ],
    "rows": [
      {"year": 1, "contributions": 2400, "interest": 350, "balance": 12750},
      {"year": 2, "contributions": 4800, "interest": 1240, "balance": 16040}
    ],
    "downloadable": true
  }
}
```

### A line chart with two series

```json
{
  "growth_chart": {
    "x_label": "Year",
    "y_label": "Balance (GBP)",
    "x": [0, 1, 2, 3, 4, 5],
    "series": [
      {"name": "Principal + contributions", "y": [10000, 12400, 14800, 17200, 19600, 22000]},
      {"name": "Total balance",              "y": [10000, 12750, 16040, 19980, 24680, 30260]}
    ]
  }
}
```

### A map with coloured points

```json
{
  "stops": {
    "default_center": [51.5, -0.1],
    "default_zoom": 11,
    "points": [
      {"lat": 51.51, "lng": -0.11, "label": "Charing Cross",   "colour": "#2563eb"},
      {"lat": 51.52, "lng": -0.08, "label": "Liverpool Street","colour": "#16a34a"}
    ]
  }
}
```

### A streaming text reply

`tool.json`:
```json
{"key": "reply", "type": "stream_text", "label": "Reply", "streaming": true}
```

`/run` returns the initial placeholder. Then `/stream` emits:
```text
data: {"output_key": "reply", "value": "The ",        "done": false}
data: {"output_key": "reply", "value": "answer is ",  "done": false}
data: {"output_key": "reply", "value": "42.",          "done": true}
```

The renderer appends each `value` to the displayed `<pre>`.

### A file output

```json
{
  "transcript_pdf": {
    "filename": "transcript.pdf",
    "data": "data:application/pdf;base64,JVBERi0xLjQK...",
    "mime_type": "application/pdf"
  }
}
```

If the value exceeds `inline_output_max_bytes` (64 KiB by default), the
proxy spills it to `artefacts/<tool>/<run>/transcript.pdf` and rewrites
the response to point at the artefact endpoint — your tool code doesn't
need to handle this.

## Layout grouping

Two adjacent outputs with the same non-default `layout` value are grouped:

```json
[
  {"key": "metric_a", "type": "number", "label": "A", "layout": "inline"},
  {"key": "metric_b", "type": "number", "label": "B", "layout": "inline"},
  {"key": "metric_c", "type": "number", "label": "C", "layout": "inline"}
]
```

Renders as a single row of three cards instead of three stacked panels.
`tab` works the same way — adjacent outputs become tabs in one tabset.

## Common mistakes

- Returning `{"value": ...}` for a `table` output. Tables don't use
  `value`; they use `columns` and `rows`.
- Returning `chart_scatter` data as `points` at the top level. The shape
  is `{series: [{name, points: [...]}]}`. (This bit the lorenz tool
  early — see memory observation 14445.)
- Forgetting `mime_type` on a `file` output. Without it, the browser
  guesses, often wrongly.
- Sending `chart_line.x` as strings. Use numbers; if you want
  date axis ticks, use `chart_bar` or `chart_candlestick` (which accept
  string x-axes).
