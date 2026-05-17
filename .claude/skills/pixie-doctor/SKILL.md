---
name: pixie-doctor
description: Diagnoses Pixie ITSELF - server, database, ports, dashboard, .venv, Python and uv versions. Use when the user says Pixie won't start, the dashboard is broken, or tools aren't showing up. Do NOT use if one named tool is broken (debug-tool) or just checking status (pixie-status).
allowed-tools: Bash, Read, Glob
---

# Pixie installation health check

You are checking the Pixie installation itself — the host, not any one tool. This skill never modifies anything. It runs a fixed sequence of diagnostics and reports a markdown summary with a recommended-fixes list at the end.

## Routing check (do this first)

- If the user wants to know what Pixie is currently DOING (warm tools, uptime), switch to `pixie-status`.
- If the user is reporting a single failing tool, switch to `debug-tool`.
- If the user wants a per-tool list with cached validation status, switch to `list-tools`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Check Python version

```bash
uv run python --version
```

Pass if >= 3.12. Fail otherwise.

### 2. Check `uv` is installed and recent

```bash
uv --version
```

Pass if present. Warn if older than 0.4.0.

### 3. Check Pixie's own dependencies import

```bash
uv run python -c "import fastapi, uvicorn, httpx, pydantic, jinja2, typer, rich; print('ok')"
```

Pass if "ok". Fail with the import error otherwise — recommend `uv sync` at the repo root.

### 4. Check `pixie.db` is readable

```bash
uv run python -c "
import sqlite3, pathlib
db = pathlib.Path('pixie.db')
if not db.exists():
    print('MISSING'); raise SystemExit
con = sqlite3.connect(db)
tables = [r[0] for r in con.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
print('tables=' + ','.join(tables))
"
```

`MISSING` is a warn, not a fail (db is created on first run). Fail only if the file exists but is corrupt.

### 5. Check `tools/` folder readable

```bash
ls tools/ 2>&1
```

Fail if not readable. Warn if empty (no tools installed).

### 6. Check each tool's `.venv`

```bash
uv run python -c "
import pathlib, sys
results = []
for tool in sorted(pathlib.Path('tools').iterdir()):
    if not tool.is_dir() or not (tool/'tool.json').exists():
        continue
    venv = tool/'.venv'
    if not venv.exists():
        results.append((tool.name, 'MISSING'))
        continue
    py = venv/'Scripts'/'python.exe' if sys.platform == 'win32' else venv/'bin'/'python'
    results.append((tool.name, 'OK' if py.exists() else 'INCOMPLETE'))
for name, status in results: print(f'{name}\t{status}')
"
```

Render as a table. Recommend `cd tools/<id> && uv sync` for any `MISSING` or `INCOMPLETE` row.

### 7. Check each tool's latest validation status (from pixie.db, no re-run)

```bash
uv run python -c "
import sqlite3, pathlib
db = pathlib.Path('pixie.db')
if not db.exists(): raise SystemExit
con = sqlite3.connect(db)
rows = con.execute('SELECT tool_id, overall, MAX(timestamp) FROM validation_reports GROUP BY tool_id').fetchall()
for r in rows: print(f'{r[0]}\t{r[1]}\t{r[2]}')
"
```

Render as a table. Recommend `revalidate-all` if any tool's report is older than 14 days, or if there are tools on disk with no report at all.

### 8. Check disk space

```bash
uv run python -c "
import shutil, pathlib
total, used, free = shutil.disk_usage(pathlib.Path('.'))
gib = lambda n: n / (1024**3)
print(f'free={gib(free):.2f} GiB total={gib(total):.2f} GiB')
"
```

Warn if free < 1 GiB. Fail if free < 100 MiB.

### 9. Check port 7860 status

```bash
uv run python -c "
import socket, os
port = int(os.environ.get('PIXIE_PORT', '7860'))
s = socket.socket()
try:
    s.bind(('127.0.0.1', port))
    print(f'FREE port={port}')
except OSError:
    print(f'IN_USE port={port}')
finally:
    s.close()
"
```

If `IN_USE`, hit `/api/healthz` to see if it's Pixie:

```bash
uv run python -c "
import httpx, os
port = os.environ.get('PIXIE_PORT', '7860')
try:
    r = httpx.get(f'http://127.0.0.1:{port}/api/healthz', timeout=2.0)
    print('PIXIE' if r.status_code == 200 else 'OTHER')
except Exception:
    print('OTHER')
"
```

`PIXIE` is fine. `OTHER` is a fail — another process is squatting on the port.

### 10. Render the final report

Combine all sections under `## Pixie installation health`. Each subsection has a single-line status: `PASS`, `WARN`, or `FAIL`. End with a `## Recommended fixes` list — one bullet per actionable finding, in priority order (FAILs first, then WARNs). Plain shell commands the user can copy.

If everything passes:

> "Pixie installation is healthy. No action required."

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Do NOT

- Do NOT run `uv sync` automatically — recommend it, let the user run it.
- Do NOT run the validator on any tool — use cached reports only. Recommend `revalidate-all` if needed.
- Do NOT modify `pixie.db`, `tool.json`, or any source file.
- Do NOT start or stop Pixie processes.
- Do NOT bind to `0.0.0.0` or any non-loopback interface during port checks.
- Do NOT add Docker, container, or cloud-deployment files.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
