# {{TOOL_NAME}}

*{{DESCRIPTION}}*

## What it does

Sends the user's prompt to an upstream HTTP API with retry and
exponential backoff, then returns the parsed response as key-value
pairs. Defaults to `httpbin.org/post` so the tool works end-to-end the
moment you set an API key.

## Install

```sh
cd tools/{{TOOL_ID}}
uv sync
```

## Configure the API key

The tool reads its API key from the `API_KEY` environment variable. Two
ways to set it:

1. **Recommended:** open the tool in Pixie, go to *settings*, and paste
   the key into the *Secrets* form. Pixie writes it to `.env` and
   passes it as `env=...` on subprocess spawn (never via CLI args).
2. **Quick local dev:** ask Claude Code: *"set the API key for
   {{TOOL_ID}}"*. The `set-secret` skill walks you through it.

Without a key, `/run` returns
`{"status": "secret_missing", "secret": "API_KEY", ...}` and the
renderer surfaces a "Set API_KEY" button.

## Run standalone

```sh
uv run python main.py --port 8001
```

## Inputs

| Key | Type | Description |
|---|---|---|
| `prompt` | textarea | Free-text query to send to the upstream API. |

## Outputs

| Key | Type | Description |
|---|---|---|
| `result` | kv | Response status, attempts, and parsed body. |

## External services / API keys

| Name | Required | Source |
|---|---|---|
| `API_KEY` | recommended | The upstream API provider. |
