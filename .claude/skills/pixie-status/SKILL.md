---
name: pixie-status
description: Shows Pixie's current runtime state - whether the server is up, which tools are warm, ports, recent activity, uptime - read-only. Use when the user asks if Pixie is running, what's running now, or what's warm. Do NOT use if Pixie is broken (pixie-doctor) or to enumerate installed tools (list-tools).
allowed-tools: Bash, Read, Glob
---

# Pixie runtime snapshot

You are producing a one-screen snapshot of the running Pixie process: uptime, currently-warm tool subprocesses, recent run count, database size. This is a live-state question, distinct from the installation-health check in `pixie-doctor`.

## Routing check (do this first)

- If the user wants a static install health check (Python version, deps), switch to `pixie-doctor`.
- If the user wants the list of installed tools with cached validation, switch to `list-tools`.
- If the user wants live stderr from one running tool, switch to `view-logs`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Determine the API port

Default `7860`. Honour `PIXIE_PORT` if set.

PowerShell: `$env:PIXIE_PORT`
Bash: `echo "${PIXIE_PORT:-7860}"`

### 2. Call `/api/healthz`

```bash
uv run python -c "
import httpx, os, json
port = os.environ.get('PIXIE_PORT', '7860')
try:
    r = httpx.get(f'http://127.0.0.1:{port}/api/healthz', timeout=2.0)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))
except httpx.ConnectError:
    print('PIXIE_NOT_RUNNING')
except Exception as e:
    print('ERROR: ' + str(e))
"
```

Note for the orchestrator: this assumes `GET /api/healthz` returns a JSON document with at least: `uptime_seconds`, `warm_tools` (list of `{id, pid, port, started_at, rss_mb?}`), `db_size_bytes`, `recent_runs_24h`. If the endpoint isn't shipped yet, this skill returns "not running" — the same as if the process were down.

### 3. Branch on the response

#### Case A — `PIXIE_NOT_RUNNING`

Tell the user plainly:

> "Pixie is not running on port `<port>`. Start it with:
> ```
> uv run pixie
> ```
> from the repo root (`C:\dev\Pixie`)."

Stop.

#### Case B — Pixie responded

Render a markdown summary:

```
## Pixie runtime snapshot

- **Uptime:** <human-readable, e.g., "2h 17m">
- **Listening on:** 127.0.0.1:<port>
- **Warm tools:** N
- **Recent runs (24h):** M
- **Database size:** <human-readable, e.g., "3.4 MiB">
```

Then a warm-tools table (only if N > 0):

| Tool | PID | Port | Warm since | RSS |
|---|---|---|---|---|

`Warm since` is the relative time (e.g., "12m ago"). `RSS` is in MiB if reported, else `—`.

If N == 0:

> "No tools are currently warm. Open a tool in the dashboard to spin one up."

### 4. Footer

End with a single line:

> "Snapshot at <local time>. Re-run the skill to refresh."

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Do NOT

- Do NOT start, stop, or restart Pixie.
- Do NOT call any non-GET endpoint.
- Do NOT modify any file.
- Do NOT run the validator.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
