---
name: view-logs
description: Surfaces stderr or stdout from a Pixie tool - live ring buffer of a warm subprocess or captured logs from a previous run. Use when the user asks for logs, console output, stderr, or stdout. Do NOT use for run outputs (view-runs) or to fix a broken tool (debug-tool).
allowed-tools: Bash, Read, Glob
---

# View a Pixie tool's live stderr

You are tailing the stderr ring buffer of a currently-running tool subprocess. This is the right surface for diagnosing silent failures, slow startup, or unexpected behaviour mid-run.

## Routing check (do this first)

- If the user wants the historical run table (when, duration, status), switch to `view-runs`.
- If the user wants the full failing-validator diagnostic loop, switch to `debug-tool`.
- If the tool isn't running, this skill will say so and stop — direct the user to start it from the dashboard.

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

### 3. Hit the logs endpoint

```bash
uv run python -c "
import httpx, os, json
port = os.environ.get('PIXIE_PORT', '7860')
try:
    r = httpx.get(f'http://127.0.0.1:{port}/api/tools/<tool_id>/logs', timeout=3.0)
    if r.status_code == 404:
        print('NOT_RUNNING'); raise SystemExit
    r.raise_for_status()
    body = r.json()
    print(json.dumps(body, indent=2))
except httpx.ConnectError:
    print('PIXIE_UNREACHABLE'); raise SystemExit
except Exception as e:
    print('ERROR: ' + str(e)); raise SystemExit
"
```

Note for the orchestrator: this assumes a `GET /api/tools/{id}/logs` endpoint exists, returning the stderr ring buffer for the warm subprocess. If the tool isn't warm, the endpoint should return 404 so this skill can fall through.

### 4. Branch on the response

- **`PIXIE_UNREACHABLE`** — tell the user: "Pixie isn't running. Start it with `uv run pixie` from the repo root, then open the tool in the dashboard so it becomes warm." Stop.
- **`NOT_RUNNING`** — tell the user: "Tool `<tool_id>` is not currently running. Open it in the Pixie dashboard (or run it once) so it becomes warm, then re-run this skill." Stop.
- **Logs returned** — render them in step 5.

### 5. Render the logs

Wrap the captured stderr in a fenced code block (no language tag). Above it, print a one-line header:

> "Live stderr ring buffer for `<tool_id>` — N lines, captured at <local time>."

If the buffer is empty, say so plainly:

> "Tool `<tool_id>` is running but its stderr ring buffer is empty."

### 6. Footer

After the logs block, add:

> "This is a snapshot. Re-run the skill to refresh. The ring buffer holds the most recent stderr from this subprocess — older output is dropped."

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Do NOT

- Do NOT scrape `print()` from stdout — Pixie tools log to stderr.
- Do NOT modify the tool, restart it, or send any non-GET requests.
- Do NOT run the validator.
- Do NOT mask the logs — they are local-only and the user wants them raw. If a secret value happens to be in the logs, warn the user once that their tool is logging secrets and they should clean that up.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
