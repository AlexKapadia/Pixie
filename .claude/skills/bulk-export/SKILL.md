---
name: bulk-export
description: Bundles MANY Pixie runs or artefacts (a filtered set, not just one) into ONE zip server-side. Use when the user asks to bulk export, batch export, download many, archive runs, or package multiple outputs together. Do NOT use for one run (export-run, export-run-as-report), one artefact (export-as-format), or tool source (share-tool).
allowed-tools: Bash, Read
---

# Bulk-export multiple Pixie runs or artefacts as one zip

You package MANY runs (or many artefacts) into a single zip the user can archive or share. The selection is clarified up front; the API does the bundling server-side.

## Routing check (do this first)

- If the user wants ONE run as a report, switch to `export-run-as-report`.
- If the user wants ONE run as a raw zip, switch to `export-run`.
- If the user wants ONE artefact in a different format, switch to `export-as-format`.
- If the user wants to ship a TOOL's code, switch to `share-tool`. `share-tool` exports the code; `bulk-export` exports run RESULTS.
- If the user wants to delete old runs to free space, switch to `clear-old-outputs`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Clarify the selection

Pixie users describe bulk selections vaguely. Pin down EXACTLY what to include before doing anything else. Acceptable selection shapes:

- "all runs of tool `<id>`" — fetch via `GET /api/tools/<id>/runs`.
- "all runs of tool `<id>` in the last N days" — same, then filter by `started_at`.
- "all starred runs" — `GET /api/runs?starred=1`.
- "all runs with label `<label>`" — `GET /api/runs?label=<label>`.
- "these specific run ids: a, b, c" — explicit list.
- "all artefacts of type image" — `GET /api/artefacts?mime=image/*`.
- "all artefacts tagged `<tag>`" — `GET /api/artefacts?tag=<tag>`.

If the user's selection is ambiguous, STOP and ask one specific clarifying question (e.g. "Do you want every run of `<tool>`, or just the most recent 10?").

Enumerate the resolved selection and show counts BEFORE downloading:

```bash
curl -s "http://127.0.0.1:8765/api/runs?<filter>&limit=500" | uv run python -c "
import json, sys
rows = json.load(sys.stdin)
print({'count': len(rows), 'first': rows[0] if rows else None, 'last': rows[-1] if rows else None})
"
```

If the count is 0, STOP. If the count exceeds 500, warn the user and ask whether to narrow the selection or proceed anyway.

### 2. Pick the bundle format

- `format=report` — each run is exported as a markdown report + assets (uses the same renderer as `export-run-as-report`).
- `format=raw` — each run is exported as raw `inputs.json` + `outputs.json` + assets (uses the same as `export-run`).

Default: `report` unless the user explicitly asked for raw.

### 3. Decide the output path

Default: `~/Downloads/pixie-bulk-<YYYYMMDD-HHMMSS>.zip`.

If the user supplied a path:
- If directory, append the default filename.
- If filename, use as-is.
- Verify parent exists:

```bash
ls "<parent dir>"
```

If parent missing, refuse — Pixie skills do not create arbitrary parent directories.

### 4. Refuse to overwrite

If destination exists AND no `--force`, STOP:

> "`<dest>` already exists. Pass `--force` to overwrite or pick a different path."

### 5. Confirm Pixie is reachable

```bash
curl -s http://127.0.0.1:8765/api/healthz
```

If offline, STOP — bundling runs server-side. Start Pixie (`uv run pixie`) and rerun.

### 6. POST the selection to the bulk endpoint

```bash
uv run python -c "
import json, sys, urllib.request
body = json.dumps({'run_ids': <list>, 'format': '<report|raw>'}).encode('utf-8')
req = urllib.request.Request('http://127.0.0.1:8765/api/exports/bulk', data=body, headers={'Content-Type':'application/json'}, method='POST')
with urllib.request.urlopen(req) as r, open(sys.argv[1], 'wb') as f:
    while chunk := r.read(1024*1024):
        f.write(chunk)
print({'wrote': sys.argv[1]})
" "<dest>"
```

Alternative body shape: `{"artefact_ids": [...], "format": "raw"}` when the user selected by artefact rather than by run.

If the request fails, delete the partial file and surface the API error verbatim. The endpoint streams; very large bundles may take minutes.

### 7. Verify the zip

```bash
uv run python -c "
import zipfile, pathlib, sys
p = pathlib.Path(sys.argv[1])
with zipfile.ZipFile(p) as z:
    bad = z.testzip()
    names = z.namelist()
print({'path': str(p), 'size_bytes': p.stat().st_size, 'entries': len(names), 'corrupt': bad})
" "<dest>"
```

If `corrupt` is non-null, STOP — surface the bad entry, leave the file for inspection.

### 8. Confirm to the user

One line:

> "Bulk-exported `<count>` <runs|artefacts> as `<format>` to `<dest>` (`<size>`, `<N>` zip entries)."

Second line:

> "Each <run|artefact> is in its own subfolder inside the zip. Open it with any archive tool."

### 9. Do NOT run the validator

This skill does not modify any tool — exporting is read-only.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
Your selection is ambiguous. Did you mean:
  - all <N> runs of `<tool>` ever?
  - only the most recent <N>?
  - only starred / labelled runs?
Pick one and rerun.
```

```
Selection resolved to 0 <runs|artefacts>. Nothing to export.
Try `view-runs` or `list-outputs` to see what's available.
```

```
Selection resolved to <N> <runs|artefacts> (`<size estimate>`). That's large.
Narrow with a filter (date range, label, tag) or rerun with `--confirm-large`.
```

```
`<dest>` already exists. Pass `--force` to overwrite or pick a different path.
```

```
Pixie is not running. Bulk export bundles server-side. Start Pixie and rerun.
```

## Do NOT

- Do NOT proceed without the user confirming the selection size when it exceeds 500.
- Do NOT overwrite an existing file without `--force`.
- Do NOT include secret values from `.env` — the API endpoint omits them and you must too.
- Do NOT mix run ids and artefact ids in a single call — pick one selection shape.
- Do NOT modify any source data.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically — name them and stop.
