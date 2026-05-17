---
title: Secrets
description: Per-tool .env files, the masked UI, and how secrets stay out of logs.
sidebar:
  order: 6
---

Tools sometimes need API keys, database URLs, or other credentials. Pixie's
secrets model is built on three rules:

1. Secrets live in the **tool's own `.env`** — never in Pixie's SQLite,
   never in a central store.
2. Pixie's UI is **write-only** — set a value once, see "set" / "not set"
   thereafter, with a "Replace" button that opens an empty input.
3. Known secret values are **masked in logs** — a process-wide logging
   filter replaces them with `***`.

## Declaring secrets in `tool.json`

```json
{
  "secrets": [
    {
      "key": "OPENAI_API_KEY",
      "description": "OpenAI API key for the chat completion endpoint",
      "required": false
    },
    {
      "key": "DATABASE_URL",
      "description": "Postgres connection string",
      "required": true
    }
  ]
}
```

Fields:

- `key` — the env var name your tool will read.
- `description` — what it's for (shown in the UI).
- `required` — if `true`, the settings page warns when it's unset.

The field is called `description`, **not** `label`. Older tool.json files
that used `label` are rejected by the Pydantic model; migrate them with
the [`migrate-tool-format`](/Pixie/skills/edit-tools/) skill.

## Reading the secret in your tool

`main.py` should load `.env` once at module import:

```python
from dotenv import load_dotenv
import os

load_dotenv()  # reads tools/<id>/.env

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
```

The launcher passes the working directory (`cwd=tool_path`) so
`load_dotenv()` finds the local `.env` without needing a path.

## Setting a secret from the dashboard

Open `/tool/<id>/settings`. For each declared secret you'll see:

- The `key` (e.g. `OPENAI_API_KEY`).
- The `description`.
- A status pill: **set** (green) or **not set** (grey).
- An input field (HTML `type="password"`, always masked).
- A "Replace" button that opens an empty input.

Submitting writes the value to `tools/<id>/.env`. The file is created with
mode `600` on POSIX. The value is **never displayed back**, even immediately
after saving — the UI just shows the new "set" status.

## Setting a secret from Claude Code

```text
Set the OPENAI_API_KEY for whisper-transcription
```

This triggers the [`set-secret`](/Pixie/skills/data-secrets/) skill, which
asks for the value (reading it from stdin without echoing), writes it to
`.env`, and confirms — never logging or printing the value back.

## How secrets stay out of logs

`pixie/secrets.py` installs a `SecretMaskingFilter` on the root logger at
startup. Whenever a tool's `.env` is read, every value of length ≥ 4 is
registered with the filter. Subsequent log records have their `msg`
scrubbed for any registered value before being emitted.

This catches three common leak paths:

- **Exception messages** that interpolate secrets ("`Request failed with
  key sk-...`") — masked.
- **Debug logs** that dump the request env — masked.
- **Validator stderr** captured in `spawn_log` — masked.

The filter does **not** catch:

- Secrets your tool returns in its `outputs_json` (the runtime can't know
  which strings are secrets at output time). Don't include secrets in
  outputs.
- Secrets your tool writes to its own files outside the `.env`.
- Secrets baked into source code (this is why `lint-tool` flags hardcoded
  secrets).

## `.env` is gitignored, always

The `.gitignore` shipped with Pixie includes:

```text
tools/*/.env
```

If you fork a tool folder by hand, double-check this is honoured. The
`lint-tool` skill flags `.env` files that aren't covered by `.gitignore`.

## Sharing a tool that needs secrets

`share-tool` packages a tool's source as a `.zip` for distribution. It
**explicitly excludes**:

- `.venv/` (platform-specific bloat)
- `.env` (your secrets)
- `.git/` (irrelevant)
- `data/` (often large; not part of the tool)

The recipient runs `uv sync` to rebuild the venv and `set-secret` (or
edits `.env` by hand) to set their own credentials.

`import-tool` (the inverse) **refuses** zips that contain `.env` files for
the same reason.

## Pixie itself doesn't keep secrets

Pixie has no secrets of its own. There's no master password, no
admin token, no encryption key — the whole app binds to `127.0.0.1` and
trusts the OS user. If you need credentialed multi-user access to a tool,
Pixie isn't the right shape; reach for a hosted runtime that does AuthN/AuthZ.
