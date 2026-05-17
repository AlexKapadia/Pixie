# {{TOOL_NAME}}

*{{DESCRIPTION}}*

## What it does

A chat-layout tool that streams reply chunks back via Server-Sent
Events. The default implementation is an echo bot so you can verify the
plumbing before swapping in a real model.

## Install

```sh
cd tools/{{TOOL_ID}}
uv sync
```

## Run standalone

```sh
uv run python main.py --port 8001
```

## Chat layout convention

* `POST /run` accepts `{run_id, messages, history}` and returns
  `{run_id, reply: ""}` immediately.
* `GET /stream?run_id=<id>` returns SSE. Each event is JSON:
  `{"chunk": "<text>", "done": false}`. The final event has
  `"done": true` and the server closes the connection.
* `POST /cancel?run_id=<id>` stops a pending stream.

## Inputs

| Key | Type | Description |
|---|---|---|
| `messages` | json | The full conversation as `[{role, content}, ...]`. |

## Outputs

| Key | Type | Description |
|---|---|---|
| `reply` | stream_text | The assistant reply, streamed character by character. |

## External services / API keys

None by default. To wire up an LLM, declare its key in `tool.json` and
read it via `os.environ` inside `src/{{PACKAGE}}/streaming.py`.
