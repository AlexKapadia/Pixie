---
name: audit-disk-usage
description: Reports disk usage across EVERY Pixie tool - .venv, data, models, cache - sorted largest first, flagging archive candidates. Read-only. Use when the user asks about disk usage, storage, space, or footprint Pixie is taking. Do NOT use to inspect ONE tool (inspect-tool), live runtime (pixie-status), or lint style (lint-tool).
allowed-tools: Bash, Read, Glob
---

# Audit disk usage across all Pixie tools

You are producing a single read-only report on where disk space is going across every tool under `tools/`. Per tool you measure `.venv/`, `data/`, `models/` (if it exists), and `__pycache__/` (anywhere recursively). You sort tools descending by total footprint, flag any tool with a `.venv/` larger than 500 MB whose last run was more than 60 days ago as a candidate for `archive-tool`, and print a grand total at the end. You do not delete or modify anything.

## Routing check (do this first)

- If the user asks about ONE tool's details (schema, dependencies, etc.), switch to `inspect-tool` — that is the per-tool inspector.
- If the user wants the live runtime view (what is warm now), switch to `pixie-status`.
- If the user wants to actually delete the cruft, this skill only reports — direct them to `archive-tool` for individual reclaims after they have read the report.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Enumerate every tool

`Glob` `tools/*/tool.json`. The matched directories are the tools. Skip any path that does not exist after the glob (race-safe).

If there are zero tools, surface a one-line message ("No Pixie tools installed.") and stop.

### 2. Measure each tool's footprint

For each `<tool_id>`, capture four numbers in bytes:

| Bucket | Path |
|---|---|
| `venv_bytes` | `tools/<tool_id>/.venv` |
| `data_bytes` | `tools/<tool_id>/data` |
| `models_bytes` | `tools/<tool_id>/models` |
| `cache_bytes` | every `__pycache__` under `tools/<tool_id>` (recursive) |

Use a single Python one-liner per tool so the measurement is cross-platform (POSIX `du` is unreliable on Windows):

```bash
uv run python -c "import pathlib, sys; root = pathlib.Path('tools/<tool_id>'); buckets = {'venv': root / '.venv', 'data': root / 'data', 'models': root / 'models'}; out = {}; [out.__setitem__(k, sum(p.stat().st_size for p in v.rglob('*') if p.is_file()) if v.exists() else 0) for k, v in buckets.items()]; out['cache'] = sum(p.stat().st_size for p in root.rglob('__pycache__/*') if p.is_file()); import json; print(json.dumps({'tool': '<tool_id>'} | out))"
```

Collect every JSON line into a list.

### 3. Read each tool's last-run timestamp

Query `pixie.db` once for the most recent run per tool:

```bash
uv run python -c "import sqlite3, pathlib, json; conn = sqlite3.connect(pathlib.Path('pixie.db')); rows = conn.execute('SELECT tool_id, MAX(started_at) AS last_run FROM runs GROUP BY tool_id').fetchall(); print(json.dumps({r[0]: r[1] for r in rows}))"
```

Tools with no run history get `last_run = null`.

### 4. Sort and format the table

Sort tools by `total = venv + data + models + cache` descending. Format bytes in the smallest unit that yields a number with at most one decimal (`MB` for ≤ 1024 MB, otherwise `GB`). Use British English in the column headers.

The table goes:

| Tool | venv | data | models | cache | Total | Last run | Note |
|---|---|---|---|---|---|---|---|

The `Note` column carries the flag from step 5.

### 5. Flag archival candidates

A tool is flagged when **both**:

- `venv_bytes > 500 * 1024 * 1024` (over 500 MB), AND
- `last_run` is `null` or older than 60 days from today's date.

Note column reads: `archive candidate — venv X MB, last run Y days ago`. Y is `never` if `last_run is None`.

### 6. Print the grand total

After the table, a single line:

> "Total Pixie disk usage: `<N> GB` across `<M>` tools. Of that, `<V> GB` is virtual environments, `<D> GB` is data, `<W> GB` is model weights, `<C> MB` is Python cache."

### 7. Print actionable suggestions

If any tool was flagged in step 5, print:

> "Candidates for `archive-tool` (reversible, frees the `.venv/`):"

Followed by one bullet per flagged tool with the freed estimate. If none were flagged, print:

> "No obvious archive candidates — every tool with a large `.venv/` was used in the last 60 days."

### 8. Do NOT run the validator

This skill is read-only. Skip the validator.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I will not delete anything in this skill — it only reports. To actually reclaim
space, archive the candidates one by one with `archive-tool`, or remove unwanted
tools entirely with `remove-tool`. Both confirm before destroying.
```

## Do NOT

- Do NOT delete, move, or modify any file or folder.
- Do NOT touch `tool.json`, `main.py`, `.env`, or `pixie.db`.
- Do NOT call `archive-tool` or `remove-tool` programmatically — list the candidates and let the user decide.
- Do NOT measure folders outside `tools/`.
- Do NOT include `.git/` in any measurement.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically.
