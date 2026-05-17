# {{TOOL_NAME}}

*{{DESCRIPTION}}*

## What it does

Echoes its input back as a single text reply. Replace the body of `run()`
in `main.py` with your own logic.

## Install

```sh
cd tools/{{TOOL_ID}}
uv sync
```

## Run standalone

```sh
uv run python main.py --port 8001
```

Then `curl -s http://127.0.0.1:8001/healthz` to confirm it's up.

## Inputs

| Key | Type | Description |
|---|---|---|
| `message` | text | Text to echo back. |

## Outputs

| Key | Type | Description |
|---|---|---|
| `reply` | text | The echoed reply. |

## External services / API keys

None.
