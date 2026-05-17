---
title: HTTP contract
description: Every endpoint your tool must expose, with request and response shapes.
sidebar:
  order: 3
---

Your tool's `main.py` is a FastAPI app bound to `127.0.0.1:<port>` where
the port is passed in via `--port` at spawn time. The app must expose
**three** endpoints and may expose **two** optional ones.

## Required

### `GET /healthz`

The fastest possible "I'm ready" signal. Pixie polls this every 100 ms
after spawn (up to 30 s).

```python
@app.get("/healthz")
async def healthz():
    return {"ok": True}
```

Response:

```json
{"ok": true}
```

### `GET /schema`

Returns the `tool.json` contents. The validator's check 7 compares this
to the on-disk file; drift is a `warn`.

```python
@app.get("/schema")
async def schema():
    import json, pathlib
    return json.loads((pathlib.Path(__file__).parent / "tool.json").read_text())
```

### `POST /run`

The actual work. Body matches the input schema; response matches the
output schema.

**Request:**

```http
POST /run HTTP/1.1
Host: 127.0.0.1:51234
Content-Type: application/json

{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "inputs": {
    "principal": 10000,
    "rate": 5,
    "years": 10
  },
  "principal": 10000,
  "rate": 5,
  "years": 10,
  "_pixie": {
    "run_id": "550e8400-e29b-41d4-a716-446655440000",
    "artefacts_dir": "/abs/path/to/artefacts/<tool_id>/<run_id>"
  }
}
```

Notes:

- `run_id` and `_pixie` are added by Pixie's proxy. Tools that don't care
  can ignore them entirely.
- `inputs` is a nested dict matching the input schema; the top-level
  fields are a **backward-compatibility shim** so older tools that
  declared a flat Pydantic model on the body still work. Recommend the
  nested form for new code.

**Response:** flat dict keyed by your output `key`s.

```json
{
  "final_value": {"value": 25967.50, "format": "currency", "precision": 2},
  "yearly_breakdown": {
    "columns": [{"key": "year", "label": "Year"}, {"key": "balance", "label": "Balance"}],
    "rows":    [{"year": 1, "balance": 10500}, ...]
  },
  "growth_chart": {
    "x": [0, 1, 2, ..., 10],
    "series": [{"name": "Balance", "y": [10000, 10500, ..., 25967.50]}]
  }
}
```

For scalar output types (`text`, `number`, `boolean`, `image`, `audio`,
`video`, `progress`, `markdown`, `latex`, `code`), the value may be the
raw scalar (`42`, `"hello"`, `true`) or wrapped as `{"value": ...}`.
Both shapes are accepted by the renderer.

A `RunInput` / `RunOutput` Pydantic model is the recommended way to
implement this:

```python
from pydantic import BaseModel

class RunInput(BaseModel):
    principal: float
    rate: float
    years: int

class RunOutput(BaseModel):
    final_value: dict
    growth_chart: dict
    yearly_breakdown: dict

@app.post("/run")
async def run(body: RunInput) -> RunOutput:
    ...
```

The timeout is `max_runtime_seconds + 5` from `tool.json`. Exceed it and
Pixie SIGKILLs the process.

## Optional

### `GET /stream?run_id=<id>`

Server-Sent Events for tools that produce output incrementally. Used
when any output declares `streaming: true`.

```python
from fastapi.responses import EventSourceResponse  # pip install sse-starlette
# Or implement raw SSE if you don't want the dep.

@app.get("/stream")
async def stream(run_id: str):
    async def event_gen():
        for chunk in compute_thing():
            yield {"event": "message", "data": json.dumps({
                "output_key": "reply",
                "value": chunk,
                "done": False
            })}
        yield {"event": "message", "data": json.dumps({
            "output_key": "reply", "value": "", "done": True
        })}
    return EventSourceResponse(event_gen())
```

Each event must be a JSON object with `output_key`, `value`, and `done`.
Pixie relays them to the browser via its own SSE proxy at
`/tool/<id>/stream`.

See [Streaming outputs](/Pixie/build/streaming/) for the full guide.

### `POST /cancel?run_id=<id>`

Lets the user abort a long-running operation cleanly. If you don't
implement this, Pixie falls back to SIGTERM.

```python
_cancel_flags: dict[str, asyncio.Event] = {}

@app.post("/cancel")
async def cancel(run_id: str):
    if ev := _cancel_flags.get(run_id):
        ev.set()
    return {"cancelled": True}

@app.post("/run")
async def run(body: RunInput, request: Request):
    run_id = body.run_id
    flag = _cancel_flags.setdefault(run_id, asyncio.Event())
    try:
        for step in expensive_loop():
            if flag.is_set():
                return {"status": "cancelled"}
            await step()
    finally:
        _cancel_flags.pop(run_id, None)
    return {"result": ...}
```

## Error responses

A 4xx or 5xx response is captured by Pixie and rendered in the output
panel with a "view stderr" disclosure.

```python
from fastapi import HTTPException

@app.post("/run")
async def run(body: RunInput) -> RunOutput:
    if body.principal <= 0:
        raise HTTPException(status_code=422, detail="Principal must be positive.")
    ...
```

Pixie unwraps the `detail` field and shows it as the user-facing message.

## Headers

Pixie adds two headers on every `/run` call:

- `X-Pixie-Run-Id: <uuid>` — same as `run_id` in body, for tools that
  parse headers only.
- `X-Pixie-Artefacts-Dir: <abs path>` — where you should write large
  outputs if you don't want them inline in `outputs_json`.

The proxy itself sets `Content-Type: application/json` and times out the
request at `max_runtime_seconds + 5`.

## Concurrency

The `concurrent` field in `tool.json` controls how Pixie serialises
requests:

- `concurrent: true` (default) — Pixie sends `/run` requests in parallel.
  Your tool must be thread-safe.
- `concurrent: false` — Pixie queues `/run` requests; at most one is
  in-flight. Use for tools holding non-thread-safe model state (PyTorch
  models, Whisper, etc.).

## Tip: read tool.json once at import

Many tools have to return `tool.json` from `/schema` *and* read its
defaults at startup. Cache the parse once:

```python
import json, pathlib

_TOOL_JSON = json.loads(
    (pathlib.Path(__file__).parent / "tool.json").read_text()
)

@app.get("/schema")
async def schema():
    return _TOOL_JSON
```

This avoids per-request disk I/O and guarantees the served schema is
exactly what was on disk at boot.
