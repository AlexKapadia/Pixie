---
title: tool.json reference
description: Every field on the top-level schema, with types, defaults, and validation rules.
sidebar:
  order: 2
---

Authority: the `ToolSchema` Pydantic model at `pixie/discovery.py:449`.
The Pydantic model has `extra="forbid"` so any unknown top-level key
causes validation to fail.

## Required fields

| Field     | Type                | Notes                                                        |
| --------- | ------------------- | ------------------------------------------------------------ |
| `id`      | `string`            | Kebab-case, must match the folder name under `tools/`.       |
| `name`    | `string`            | Human-readable display name. Sentence case.                  |
| `inputs`  | `list[InputSpec]`   | At least one input. See [Input types](/Pixie/build/inputs/). |
| `outputs` | `list[OutputSpec]`  | At least one output. See [Output types](/Pixie/build/outputs/). |

## Optional fields with defaults

| Field                          | Type                                   | Default   | What it does                                                                                |
| ------------------------------ | -------------------------------------- | --------- | ------------------------------------------------------------------------------------------- |
| `description`                  | `string \| null`                       | `null`    | Sidebar tooltip and tool header subtitle.                                                   |
| `version`                      | `string \| null`                       | `null`    | Semantic version, e.g. `"0.1.0"`.                                                           |
| `category`                     | `string \| null`                       | `null`    | `/`-delimited (e.g. `"finance"`, `"science/dynamics"`). Sidebar grouping.                   |
| `icon`                         | `string \| null`                       | `null`    | Heroicons name (e.g. `"calculator"`, `"bot"`).                                              |
| `layout`                       | `"form" \| "chat" \| "split"`          | `"form"`  | Inputs left/outputs right (form), full-width chat, or vertical split.                       |
| `warm_keep_seconds`            | `int`                                  | `300`     | How long to keep the tool warm after last use.                                              |
| `max_memory_mb`                | `int`                                  | `512`     | Enforced via `setrlimit` on POSIX. Ignored on Windows.                                      |
| `max_runtime_seconds`          | `int`                                  | `60`      | Wall-clock timeout per `/run`. Exceeded = SIGKILL.                                          |
| `secrets`                      | `list[SecretSpec]`                     | `[]`      | API keys and env vars. See [Secrets](/Pixie/concepts/secrets/).                             |
| `schema_version`               | `string`                               | `"1.0"`   | Reserved for future schema evolution.                                                       |
| `concurrent`                   | `bool`                                 | `true`    | If `false`, runs are serialised. Use for tools holding non-thread-safe model state.         |
| `validator_timeout_override`   | `int \| null`                          | `null`    | Override validator's default spawn timeout for very slow boots.                             |
| `requires_data_persistence`    | `bool`                                 | `false`   | Hint that the tool stores state in `data/`.                                                 |
| `input_transport`              | `"json" \| "multipart"`                | `"json"`  | `multipart` for tools that need to accept files > a few MB efficiently.                     |
| `provides_file_endpoint`       | `bool`                                 | `false`   | Tool exposes a `/files/<run_id>/<name>` endpoint for streamed file output.                  |
| `provides_autocomplete`        | `bool`                                 | `false`   | Tool implements `/autocomplete/<endpoint>` for `autocomplete` inputs.                       |
| `retain_runs`                  | `int`                                  | `100`     | How many runs to keep in `pixie.db` per tool. LRU eviction, starred/labelled exempt.        |
| `tags`                         | `list[string]`                         | `[]`      | Sidebar filter pills.                                                                       |
| `archived`                     | `bool`                                 | `false`   | Hide from the sidebar without deleting.                                                     |
| `pinned_warm`                  | `bool`                                 | `false`   | Always keep warm. Counts against the global cap.                                            |
| `entrypoint`                   | `string`                               | `"main.py"` | Path to the FastAPI app entry script.                                                     |
| `package`                      | `string \| null`                       | `null`    | Python package name when the tool wraps a published library.                                |
| `workspace_default`            | `string \| null`                       | `null`    | Input key whose value is pre-filled for new workspace tabs.                                 |

## Validation rules

The `schemas_coherent` check (validator step 3) enforces:

- **Unique keys.** Every input `key` is unique within `inputs`; same for `outputs`. Duplicate → fail.
- **Valid types.** Every `type` is one of the supported input/output types. Unknown → fail.
- **Type-specific required fields.** `select` must have `options`; `slider` must have `min` and `max`; `autocomplete` must have `endpoint`; etc.
- **`show_if` resolves.** If an input has `show_if: {key: "x", equals: ...}`, then `x` must be another input key. Unresolved → fail.
- **Layout/inputs compatibility.** For `layout: "chat"` the validator passes a synthetic `{messages: [{role, content}], history: []}` payload for sample-run instead of walking declared inputs.

## Examples

### Minimal

```json
{
  "id": "echo",
  "name": "Echo",
  "inputs":  [{"key": "message", "type": "text", "label": "Message"}],
  "outputs": [{"key": "echo",    "type": "text", "label": "Echo"}]
}
```

### Realistic finance tool

```json
{
  "id": "black-scholes-greeks",
  "name": "Black–Scholes Greeks",
  "description": "European option pricer with first-order Greeks and strike × time heatmap.",
  "version": "0.1.0",
  "category": "finance/quant",
  "icon": "calculator",
  "layout": "form",
  "warm_keep_seconds": 120,
  "max_memory_mb": 256,
  "max_runtime_seconds": 15,
  "inputs": [
    {"key": "spot",       "type": "number", "label": "Spot price (£)",       "default": 100, "min": 0.01},
    {"key": "strike",     "type": "number", "label": "Strike (£)",           "default": 100, "min": 0.01},
    {"key": "days",       "type": "slider", "label": "Days to expiry",        "min": 1, "max": 730, "default": 90},
    {"key": "rate",       "type": "number", "label": "Risk-free rate (%)",    "default": 5, "step": 0.1},
    {"key": "volatility", "type": "number", "label": "Volatility (%)",        "default": 20, "step": 0.1, "min": 0.1},
    {"key": "kind",       "type": "select", "label": "Option type",
     "options": [{"value": "call", "label": "Call"}, {"value": "put", "label": "Put"}],
     "default": "call"}
  ],
  "outputs": [
    {"key": "price",      "type": "number",        "label": "Price",   "unit": "GBP", "format": "currency", "precision": 4},
    {"key": "greeks",     "type": "kv",            "label": "Greeks"},
    {"key": "price_spot", "type": "chart_line",    "label": "Price vs spot"},
    {"key": "price_time", "type": "chart_line",    "label": "Price vs days"},
    {"key": "heatmap",    "type": "chart_heatmap", "label": "Price across strike × time"}
  ]
}
```

### Chat tool

```json
{
  "id": "llm-tool-use-agent",
  "name": "LLM tool-use agent",
  "layout": "chat",
  "concurrent": false,
  "warm_keep_seconds": 600,
  "secrets": [
    {"key": "ANTHROPIC_API_KEY", "description": "Optional. If set, routes through Claude 3.5 Haiku.", "required": false}
  ],
  "inputs": [
    {"key": "messages", "type": "json", "label": "Conversation"},
    {"key": "tools",    "type": "multiselect", "label": "Available tools",
     "options": [{"value": "calc", "label": "Calculator"}, {"value": "search", "label": "Web search"}],
     "default": ["calc"]}
  ],
  "outputs": [
    {"key": "reply",     "type": "stream_text", "label": "Reply", "streaming": true},
    {"key": "tool_log",  "type": "log",         "label": "Tool calls"}
  ]
}
```

## Common mistakes

- Using `label` instead of `description` on a secret. The field is
  `description`. Validator check 2 will reject your schema.
- Calling outputs `value` and then returning `{value: ...}` for them.
  `value` is the standard *inner* key for scalar types; it's fine, just
  don't conflate it with the output's `key`.
- Forgetting `"required": false` on optional inputs — the default is
  `true`, and the validator will refuse to omit them from sample inputs.
- Declaring `streaming: true` on an output without implementing `/stream`.
  Validator check 10 will fail.
- Putting `min` / `max` on a `number` input expecting client-side
  enforcement — they're HTML attributes only. Server-side, validate
  yourself.
