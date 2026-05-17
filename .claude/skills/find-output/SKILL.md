---
name: find-output
description: Searches saved Pixie output ARTEFACTS by substring against filename, label, or tags across all tools. Use when the user asks to find, search, look for, locate, or grep a saved output, artefact, or file. Do NOT use to list everything (list-outputs), one tool's runs (view-runs), or open a folder (open-artefacts-folder).
allowed-tools: Bash, Read
---

# Find a saved Pixie output by substring

You are searching the artefact index for files whose `filename`, `label`, or any entry in `tags` contains the user's query substring. You return rows with full context so the user can act — open, copy, export. You do not modify anything.

## Routing check (do this first)

- If the user wants to enumerate every saved output without a search query, switch to `list-outputs`.
- If the user wants to find runs (the events) rather than the FILES produced, switch to `view-runs`.
- If the user wants to inspect one tool's schema, switch to `inspect-tool`.
- If the user is searching for tools by name/tag (not outputs), switch to `list-tools` or `tag-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Confirm the query

The user must supply a search substring. If they did not (e.g. "find my outputs"), STOP and ask what they're looking for. Suggest `list-outputs` for an unfiltered listing.

Trim the query. If it contains glob wildcards (`*`, `?`), strip them and tell the user the search is plain substring (case-insensitive) — not glob.

### 2. Confirm Pixie is reachable

```bash
curl -s http://127.0.0.1:8765/api/healthz
```

If Pixie is not running, fall back to a local SQLite query (step 3b) rather than refusing.

### 3a. Query the API (preferred)

```bash
curl -s --get "http://127.0.0.1:8765/api/artefacts" --data-urlencode "q=<query>" --data-urlencode "limit=100"
```

The `q` parameter does a case-insensitive `LIKE %q%` across `filename`, `label`, and the JSON `tags` array. Returns the same artefact row shape as `list-outputs`.

### 3b. Fallback SQLite query (Pixie offline)

```bash
uv run python -c "
import sqlite3, json, pathlib, sys
q = sys.argv[1].lower()
conn = sqlite3.connect(pathlib.Path('pixie.db'))
conn.row_factory = sqlite3.Row
rows = conn.execute('''
  SELECT * FROM artefacts
  WHERE LOWER(filename) LIKE ?
     OR LOWER(COALESCE(label,'')) LIKE ?
     OR LOWER(COALESCE(tags,'[]')) LIKE ?
  ORDER BY created_at DESC LIMIT 100
''', (f'%{q}%', f'%{q}%', f'%{q}%')).fetchall()
print(json.dumps([dict(r) for r in rows], default=str))
" "<query>"
```

### 4. Format the result

If zero matches, print one line — "No artefacts match `<query>`." — and stop. Suggest `list-outputs` to see what does exist.

Otherwise format a markdown table with the FULL context the user needs to act:

| Created | Tool | Run | File | MIME | Size | Star | Label | Tags | Path on disk |
|---|---|---|---|---|---|---|---|---|---|

- `Run` is the first 8 chars of `run_id`.
- `Path on disk` is `artefacts/<rel_path>` — clickable for the user to copy.
- `Tags` is comma-joined.
- `Size` is `MB`/`GB` with one decimal.
- Sizes/dates as in `list-outputs`.

### 5. Summary line

Below the table:

> "`<N>` artefact(s) match `<query>`, total `<size>`."

If results were capped at 100, append: "Narrow the query to see more."

### 6. Suggest next steps

> "Use `copy-output-to <id> <dest>` to copy a specific artefact, `star-run <run_id>` to protect a run from auto-prune, or `open-artefacts-folder` to browse the folder."

### 7. Do NOT run the validator

This skill is read-only.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I need a search query — the substring to look for in filenames, labels, or tags.
For an unfiltered listing of every saved output, use `list-outputs`.
```

## Do NOT

- Do NOT modify, delete, rename, or move any artefact.
- Do NOT download artefact contents inside the search results — use `copy-output-to`.
- Do NOT include SHA-256 hashes in the output — they are noise for search.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically — name them and stop.
