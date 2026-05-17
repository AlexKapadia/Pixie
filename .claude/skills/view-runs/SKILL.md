---
name: view-runs
description: Lists previous runs of ONE named Pixie tool from pixie.db with inputs, status, duration, and truncated outputs. Use when the user names a tool and asks about ITS previous runs or last run. Do NOT use for live stderr (view-logs), saved artefacts across tools (list-outputs), or finding a file (find-output).
allowed-tools: Bash, Read, Glob
---

# View recent runs of a Pixie tool

You are showing the last ten runs of one tool as a markdown table. Prefer the live Pixie API; fall back to a direct sqlite read of `pixie.db` only when the host is unreachable.

## Routing check (do this first)

- If the user wants live stderr from a currently-running tool, switch to `view-logs`.
- If the user wants a full read-only snapshot of the tool (metadata, code, validation), switch to `inspect-tool`.
- If the user wants run history for ALL tools, do them one by one — this skill is per-tool.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Identify the tool

If not named, list tools:

```bash
ls tools/
```

Ask which to inspect. Verify `tools/<tool_id>/tool.json` exists.

### 2. Determine the API port

Default `7860`. Honour `PIXIE_PORT` if set.

PowerShell: `$env:PIXIE_PORT`
Bash: `echo "${PIXIE_PORT:-7860}"`

### 3. Try the live API first

```bash
uv run python -c "
import httpx, os, json
port = os.environ.get('PIXIE_PORT', '7860')
try:
    r = httpx.get(f'http://127.0.0.1:{port}/api/tools/<tool_id>/runs?limit=10', timeout=3.0)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))
except Exception as e:
    print('PIXIE_UNREACHABLE: ' + str(e))
"
```

Note for the orchestrator: this assumes a `GET /api/tools/{id}/runs?limit=N` endpoint exists. If the runtime hasn't shipped it yet, the request returns 404 and the skill falls through to step 4.

### 4. Fallback: read pixie.db directly

If the API was unreachable or returned 404:

```bash
uv run python -c "
import sqlite3, json, pathlib
db = pathlib.Path('pixie.db')
if not db.exists():
    print('NO_DB'); raise SystemExit
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
rows = con.execute(
    'SELECT run_id, started_at, finished_at, status, inputs, error FROM runs WHERE tool_id=? ORDER BY started_at DESC LIMIT 10',
    ('<tool_id>',),
).fetchall()
print(json.dumps([dict(r) for r in rows], default=str))
"
```

If `pixie.db` does not exist, tell the user Pixie has never run and there are no runs to show.

### 5. Render the markdown table

Columns:

| When | Duration | Status | Inputs (summary) | Error |
|---|---|---|---|---|

- **When** — `started_at` in the user's local timezone, formatted as `YYYY-MM-DD HH:MM:SS`.
- **Duration** — `finished_at - started_at` in seconds with one decimal, or `running` if `finished_at` is null.
- **Status** — `pass` / `fail` / `cancelled` / `running`. Use plain text, not badges.
- **Inputs** — first 60 characters of the input JSON, truncated with `...`. Mask anything in a key matching `password|secret|token|api_key` (regex, case-insensitive) as `***`.
- **Error** — first line of the error string, truncated to 80 chars. Empty for successful runs.

### 6. Footer

After the table, add a single line:

> "Showing the most recent N runs of `<tool_id>`. Full payloads are in `pixie.db` under the `runs` table."

If there are zero runs:

> "Tool `<tool_id>` has no recorded runs yet."

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Do NOT

- Do NOT run the validator.
- Do NOT modify `pixie.db`.
- Do NOT echo full input payloads if they contain anything matching `password`, `token`, `secret`, or `api_key` — mask those keys' values as `***`.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
