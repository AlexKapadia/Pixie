---
name: inspect-tool
description: Shows one Pixie tool's current schema, inputs, outputs, dependencies, secrets, and validator status - read-only. Use when the user asks what THIS tool does, or to show, describe, or inspect a single named tool. Do NOT use to list all tools (list-tools), show past runs (view-runs), or fix anything (debug-tool).
allowed-tools: Bash, Read, Glob, Grep
---

# Inspect a Pixie tool (read-only)

You are producing a complete read-only snapshot of a single Pixie tool. This skill never modifies anything, never runs the validator, never installs dependencies. It just reads disk and `pixie.db` and renders the result as a markdown report.

## Routing check (do this first)

- If the user wants a one-line summary across ALL tools, switch to `list-tools`.
- If the user asks to fix, repair, or change anything, switch to `debug-tool` or `update-tool`.
- If the user wants to re-run the validator, switch to `revalidate-all`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Identify the tool

If the user did not name one, list available tools:

```bash
ls tools/
```

Ask which to inspect. Verify `tools/<tool_id>/tool.json` exists.

### 2. Read tool.json and render prettified

`Read` `tools/<tool_id>/tool.json`. Show the parsed JSON in a fenced `json` block. Highlight: `id`, `name`, `version`, `category`, `icon`, `layout`, `warm_keep_seconds`, `max_memory_mb`, `max_runtime_seconds`, the count of inputs, the count of outputs, the count of declared secrets.

### 3. Inspect pyproject.toml

`Read` `tools/<tool_id>/pyproject.toml`. List the third-party dependencies and the `requires-python` pin. Note `author` and `description` if present.

### 4. Inspect main.py

Use `Bash` to count lines: `wc -l tools/<tool_id>/main.py` (PowerShell: `(Get-Content tools/<tool_id>/main.py | Measure-Object -Line).Lines`). Use `Grep` to list endpoints declared:

```
grep -nE "@app\.(get|post)" tools/<tool_id>/main.py
```

Report endpoint paths and line counts.

### 5. Check the venv

```bash
ls tools/<tool_id>/.venv 2>&1 || echo "MISSING"
```

If present, report Python version:

```bash
tools/<tool_id>/.venv/bin/python --version 2>&1 || tools/<tool_id>/.venv/Scripts/python.exe --version 2>&1
```

If missing, note it without running `uv sync`.

### 6. Pull the latest validation report from pixie.db

```bash
uv run python -c "
import sqlite3, json, pathlib
db = pathlib.Path('pixie.db')
if not db.exists():
    print('NO_DB'); raise SystemExit
con = sqlite3.connect(db)
row = con.execute('SELECT overall, timestamp FROM validation_reports WHERE tool_id=? ORDER BY timestamp DESC LIMIT 1', ('<tool_id>',)).fetchone()
print(json.dumps({'overall': row[0], 'timestamp': row[1]}) if row else 'NO_REPORT')
"
```

Report overall + timestamp. Do not run the validator.

### 7. Pull run history summary

```bash
uv run python -c "
import sqlite3, pathlib
con = sqlite3.connect('pixie.db')
row = con.execute('SELECT COUNT(*), MAX(started_at) FROM runs WHERE tool_id=?', ('<tool_id>',)).fetchone()
print(f'count={row[0]} last={row[1]}')
last_err = con.execute('SELECT error FROM runs WHERE tool_id=? AND error IS NOT NULL ORDER BY started_at DESC LIMIT 1', ('<tool_id>',)).fetchone()
print('last_error=' + (last_err[0] if last_err else 'none'))
"
```

Report count, last run time, last error if any.

### 8. Inspect secret status

For each secret declared in `tool.json` `secrets`, check whether the key is present in `tools/<tool_id>/.env`:

```bash
uv run python -c "
import pathlib
env = pathlib.Path('tools/<tool_id>/.env')
keys = set()
if env.exists():
    for line in env.read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.strip().startswith('#'):
            keys.add(line.split('=', 1)[0].strip())
print(sorted(keys))
"
```

Render a table: each declared secret → `set` or `not set`. Never print the value.

### 9. Check warm-keep status

```bash
uv run python -c "
import httpx, os
port = os.environ.get('PIXIE_PORT', '7860')
try:
    r = httpx.get(f'http://127.0.0.1:{port}/api/tools', timeout=2.0)
    for entry in r.json():
        if entry.get('id') == '<tool_id>':
            print(entry); break
except Exception as e:
    print('PIXIE_UNREACHABLE: ' + str(e))
"
```

Report whether the tool is currently warm, its PID, port, and uptime. If Pixie is not running, say so plainly.

### 10. Report folder size

```bash
uv run python -c "
import pathlib
total = sum(p.stat().st_size for p in pathlib.Path('tools/<tool_id>').rglob('*') if p.is_file())
print(f'{total / (1024*1024):.2f} MiB')
"
```

### 11. Render the final report

Combine all sections under a single markdown heading `## Inspection report — <tool_id>`. Use subsections for: metadata, files, dependencies, venv, validation, runs, secrets, runtime, size. End with one line: "This was a read-only inspection. No files were modified."

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Do NOT

- Do NOT run the validator. This is read-only.
- Do NOT run `uv sync`, `git`, or any state-modifying command.
- Do NOT print secret values.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
