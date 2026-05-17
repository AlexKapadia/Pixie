---
title: Troubleshooting
description: Common failure modes and how to diagnose them.
sidebar:
  order: 2
---

import { Aside } from "@astrojs/starlight/components";

Pixie fails in fairly predictable ways. This page walks through the
most common ones.

## The dashboard won't load

1. Is Pixie running? `curl http://127.0.0.1:7860/api/healthz`. Should
   return `{"ok": true}`.
2. Is the port free? Another Pixie instance, a Jupyter server, or
   Grafana may have claimed 7860. Use `PIXIE_PORT=8000 uv run pixie`.
3. Is your shell in the right venv? `which python` should point at
   `.venv/bin/python`. If not, run `uv sync` again.

If `pixie` itself is broken (not a tool), run [`pixie-doctor`](/Pixie/skills/diagnostics/#pixie-doctor)
from Claude Code or `uv run pixie validate example-compound-interest`
manually — the validator surfaces most installation issues.

## Empty sidebar

If `tools/` is empty or all tools have parse errors, the dashboard shows
an empty state.

- Check `ls tools/` — is the example tool present?
- Check the Pixie process stderr for "discovery failed" messages.
- Run `uv run pixie validate example-compound-interest` — if it fails
  with "tool.json doesn't parse", the install is broken.

## Tool stays red (validation failed)

Click the red dot in the sidebar — it shows the report inline. The most
common causes:

| Failing check         | Most likely cause                                                   |
| --------------------- | ------------------------------------------------------------------- |
| `tool_json_parses`    | Trailing comma or unknown field (`label` instead of `description`). |
| `schemas_coherent`    | Duplicate input key, missing `options` on a `select`, etc.          |
| `venv_functional`     | Forgot to `uv sync` inside the tool folder.                         |
| `tool_spawns`         | `main.py` raises on import; wrong port flag; uvicorn missing.       |
| `schema_matches_disk` | `tool.json` was edited but `main.py`'s `/schema` returns stale JSON.|
| `sample_input_run`    | Tool raises on the sample inputs (often a required env var missing).|
| `output_conforms`     | Returned `points` at the top level for a `chart_scatter` instead of `{series: [{name, points: [...]}]}`. |
| `clean_shutdown`      | Tool ignores SIGTERM; takes >5 s; locked file on Windows.            |

Run `uv run pixie validate <id> --summary` for the one-line cause, or
ask Claude Code to `debug the foo tool`.

## Tool spawns but every run fails 422

The body shape doesn't match your `RunInput` Pydantic model. The proxy
sends both the nested form (`{inputs: {...}}`) and the flat form
(`{...inputs}`) for backward compatibility — pick one in your model:

```python
# Recommended: nested
class RunInput(BaseModel):
    run_id: str
    inputs: MyInputs

# Older shape that still works:
class RunInput(MyInputs):
    pass
```

## Tool returns 200 but the output panel says "Output missing key X"

`X` is declared in `tool.json` but not in the response dict. Either:

- Add the key to your response.
- Remove the key from `tool.json` if it shouldn't exist.

Re-validate after the change.

## Tool runs hot — CPU at 100% even when idle

A subprocess that's busy-looping. Check:

- A `while True` in `main.py` without `await asyncio.sleep`.
- A `/healthz` that does real work instead of returning a constant.
- An autocomplete endpoint that gets called on every keystroke and hits
  a slow backend.

`pixie tail <id>` shows the recent stderr — usually obvious.

## Memory keeps climbing

A tool with a leak. Pixie enforces `max_memory_mb` on POSIX, so the OS
will eventually kill it. On Windows there's no memory limit — set
`max_runtime_seconds` aggressively or restart Pixie periodically.

Use `pixie sweep --dry-run` to see if accumulated artefacts are part of
the problem.

## `taskkill /F` fails to stop Pixie on Windows

Known quirk: in some shells (Git Bash, MSYS), `taskkill /F /PID nnn`
silently fails. Workaround:

```bash
cmd //c "taskkill /F /PID 21616"
```

Or use the Task Manager UI.

## Custom checkbox span intercepts Playwright clicks

When automating the dashboard via Playwright, our styled checkbox's
`<span>` overlay intercepts pointer events. Use the framework's retry
helper:

```python
await page.locator('input[type="checkbox"][name="my_input"]').click(force=True)
```

Or click the label instead of the input.

## `bertopic-modelling` fails because of missing ML wheels

The tool ships with a TF-IDF + KMeans fallback that activates when
`sentence-transformers` / `bertopic` aren't importable. If you want the
real BERTopic path:

```bash
cd tools/bertopic-modelling
uv sync --extra ml
```

The fallback isn't worse than the primary in terms of validity — just
in topic quality on large corpora.

## `whisper-transcription` returns `run_id` in the response body

If you're calling the tool directly (not through Pixie), your response
may include `run_id` echoed from the request. This is harmless — Pixie's
proxy strips it. Don't strip it yourself in your tool code; the proxy
handles it.

## `rag-with-citations` / `llm-tool-use-agent` says "secrets schema rejects label"

Old `tool.json`s used `label` on secret specs. The field is
`description`. Run [`migrate-tool-format`](/Pixie/skills/edit-tools/#migrate-tool-format)
or manually edit:

```diff
- {"key": "OPENAI_API_KEY", "label": "OpenAI key", "required": false}
+ {"key": "OPENAI_API_KEY", "description": "OpenAI key", "required": false}
```

## "Address already in use" on port 7860

Pixie wasn't shut down cleanly. Two options:

```bash
# Linux/macOS
lsof -i :7860
kill -9 <pid>

# Windows (cmd, not Bash)
netstat -ano | findstr :7860
taskkill /F /PID <pid>
```

Or just `PIXIE_PORT=8000 uv run pixie`.

## A tool's `.venv` got corrupted

Quickest recovery:

```bash
cd tools/foo
rm -rf .venv uv.lock
uv sync
cd ../..
uv run pixie validate foo
```

If `uv sync` itself fails, check `pyproject.toml` for impossible
constraints (`python>=3.13` when you have 3.12, conflicting dep
versions, etc.).

## The validator passes but the tool produces wrong answers

The validator doesn't check correctness — only the contract. To catch
correctness regressions:

1. Add reference fixtures (see [Fixtures & reference
   validation](/Pixie/build/fixtures/)).
2. Run `uv run pixie validate <id> --reference-only`.
3. Wire it into CI.

## I edited `tool.json` and the change didn't appear

Discovery caches the parsed schema; a hot reload should pick up the
new file but doesn't always. Restart Pixie (`Ctrl+C` then `uv run
pixie`) to be sure. In dev mode (`uv run pixie dev`), file watching is
on by default.

<Aside type="tip">
If you're stuck and the validator's output isn't enlightening, run
`pixie tail <id> -n 500` for the full recent stderr. The error usually
lives in there.
</Aside>
