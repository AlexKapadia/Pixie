---
title: Streaming outputs
description: When and how to use SSE for tools that produce output incrementally.
sidebar:
  order: 8
---

For tools that produce output over time — LLM token streams, training
loss curves, transcription segments — Pixie supports Server-Sent Events.

## When to stream

Use streaming when:

- The user benefits from **seeing intermediate output** before the full
  run completes (LLM replies, transcriptions, long training runs).
- The run takes **more than a few seconds** and there's a sensible
  progress signal to send.
- You're producing a `chart_line` whose **series grow** during the run
  (training loss per epoch).

Don't stream when:

- The run is fast (<1 s) — the overhead isn't worth it.
- The result is only meaningful at the end (everything-or-nothing
  computations).
- You can't reasonably produce intermediate output.

## Declaring streaming in `tool.json`

Add `"streaming": true` to any output that should arrive incrementally:

```json
{
  "outputs": [
    {"key": "reply",    "type": "stream_text", "label": "Reply", "streaming": true},
    {"key": "tool_log", "type": "log",          "label": "Tool calls"}
  ]
}
```

The presence of any `streaming: true` output causes Pixie to use the
`/stream` endpoint after the initial `POST /run`.

## Implementing `/stream`

Two endpoints get involved:

- `POST /run` — returns the initial placeholder (often `{}`).
- `GET /stream?run_id=<id>` — emits SSE events until done.

The pattern:

```python
import asyncio, json
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()
_queues: dict[str, asyncio.Queue] = {}

@app.post("/run")
async def run(body: dict):
    run_id = body["run_id"]
    queue = asyncio.Queue()
    _queues[run_id] = queue

    asyncio.create_task(do_work(body, queue))

    # Return immediately — the actual content comes via /stream
    return {"reply": {"value": ""}}

async def do_work(body: dict, queue: asyncio.Queue):
    try:
        for token in stream_from_llm(body["inputs"]):
            await queue.put({
                "output_key": "reply",
                "value": token,
                "done": False,
            })
        await queue.put({"output_key": "reply", "value": "", "done": True})
    finally:
        await queue.put(None)  # sentinel

@app.get("/stream")
async def stream(run_id: str):
    queue = _queues.pop(run_id, None)
    if queue is None:
        return {"error": "unknown run_id"}, 404

    async def event_gen():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")
```

Each event is a JSON object with three required keys:

| Key          | Type      | Meaning                                                       |
| ------------ | --------- | ------------------------------------------------------------- |
| `output_key` | `string`  | Which declared output this update belongs to.                 |
| `value`      | any       | The increment (appended to prior value).                      |
| `done`       | `bool`    | `true` on the last event for this `output_key`.               |

## Behaviour per output type

The renderer applies the update differently depending on the output type:

| Output type       | How `value` is applied                                       |
| ----------------- | ------------------------------------------------------------ |
| `stream_text`     | Appended to the displayed string.                            |
| `log`             | `value` should be `{lines: [...]}` — appended to log buffer. |
| `chart_line`      | `value` should include `x` and `series.y` deltas to append.  |
| `chart_bar`       | Same — `x` and `series.y` appended.                          |
| `progress`        | `value` overwrites — show fraction complete.                 |
| anything else     | Treated as final value replacement.                          |

For `chart_line`, the event shape is:

```json
{
  "output_key": "loss",
  "value": {"x": [12], "series": [{"name": "train", "y": [0.823]}]},
  "done": false
}
```

The renderer appends `12` to the chart's `x` array and `0.823` to the
`train` series.

## What Pixie does with the stream

When the browser receives the run response from `POST /tool/<id>/run`:

1. Pixie sees that the tool declared `streaming: true` outputs.
2. Pixie returns the response and inserts an `<div hx-ext="sse"
   sse-connect="/tool/<id>/stream?run_id=<id>">` block.
3. Htmx's SSE extension opens an `EventSource` to that URL.
4. Pixie's `/tool/<id>/stream` route proxies the tool's `/stream` events
   to the browser, one-to-one.
5. A small custom JS dispatcher in `pixie.js` applies each event to the
   appropriate output partial.

The browser doesn't need to know anything about the tool — it just
applies events by `output_key`.

## Validator's streaming check

If any output has `streaming: true`, the validator's check 10 opens an
SSE connection to `/stream?run_id=<id>` and confirms at least one event
arrives within 10 seconds. No event → `fail`.

The validator doesn't verify event correctness in detail — just that
streaming is wired up. Use reference fixtures (check 12) to verify
content if needed.

## Cancellation

When a user clicks "Cancel" on a streaming run, Pixie sends
`POST /cancel?run_id=<id>` to your tool. If you implemented `/cancel`
(see [HTTP contract](/Pixie/build/http-contract/)), set a cancel flag
that your `do_work` loop checks between yields:

```python
async def do_work(body, queue):
    for token in stream_from_llm(...):
        if _cancel_flags.get(body["run_id"]):
            await queue.put({"output_key": "reply", "value": "", "done": True})
            break
        await queue.put({"output_key": "reply", "value": token, "done": False})
```

If you don't implement `/cancel`, the launcher SIGTERMs your tool —
which kills the stream but loses the chance for a graceful "stopped"
message.

## Tools that stream

- [`whisper-transcription`](/Pixie/cookbook/whisper-transcription/) — streams transcript segments as they're decoded.
- [`live-mlp-training`](/Pixie/cookbook/live-mlp-training/) — streams loss and accuracy per epoch.
- [`style-transfer`](/Pixie/cookbook/style-transfer/) — streams the loss curve per iteration.
- [`rag-with-citations`](/Pixie/cookbook/rag-with-citations/) — streams the LLM-synthesised answer.
- [`llm-tool-use-agent`](/Pixie/cookbook/llm-tool-use-agent/) — streams the reply token by token.

Read their `main.py` files for production examples.
