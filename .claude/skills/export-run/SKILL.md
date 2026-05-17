---
name: export-run
description: Exports ONE Pixie run as a RAW zip - inputs.json, outputs.json, every artefact file - no rendering. Use when the user asks to export, download, dump, or package one run's raw data. Do NOT use for rendered markdown report (export-run-as-report), many runs (bulk-export), one artefact (export-as-format), or tool source (share-tool).
allowed-tools: Bash, Read
---

# Export a Pixie run as a zip

You are packaging one run's full record — `inputs.json`, `outputs.json`, every file under `artefacts/<tool>/<run>/`, and a generated markdown report — into a single zip the user can archive or send. You do not modify the run or its artefacts in any way.

## Routing check (do this first)

- If the user wants to share a TOOL's CODE (so someone else can run it), switch to `share-tool`. `share-tool` packages source; `export-run` packages one run's data.
- If the user wants to list runs to choose one to export, switch to `view-runs` first.
- If the user wants to copy a single artefact file (not the whole run), switch to `copy-output-to`.
- If the user wants to delete old runs to reclaim space, switch to `clear-old-outputs`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Resolve the run_id

Accept a full `run_id` or a short prefix. Resolve prefixes via the API (`GET /api/runs?run_id_prefix=...` or list and filter). If zero matches, STOP and suggest `view-runs`. If multiple, list and ask.

If the user described the run by tool + recency, use `view-runs <tool_id>` first to enumerate — do NOT guess.

### 2. Decide the output path

Default: `./<tool_id>-<run_id_short>.zip` in the current working directory, where `<run_id_short>` is the first 8 chars.

If the user supplied a path, use that. If the path ends in `/` or is a directory, append the default filename. Verify the parent directory exists:

```bash
ls "<parent dir>"
```

### 3. Refuse to overwrite

If the chosen output path already exists AND the user did NOT pass `--force`, STOP. Print:

> "`<path>` already exists. Pass `--force` to overwrite or choose a different path."

### 4. Confirm Pixie is reachable

```bash
curl -s http://127.0.0.1:8765/api/healthz
```

If Pixie is not running, STOP — the export endpoint generates the markdown report server-side and reads from `pixie.db` consistently. Tell the user to start Pixie (`uv run pixie`) and rerun.

### 5. Stream the zip from the API

```bash
curl -s -f -o "<output path>" "http://127.0.0.1:8765/api/runs/<run_id>/export"
```

The endpoint streams a zip with this layout:

```
<run_id_short>/
  inputs.json
  outputs.json
  report.md
  artefacts/
    <output_key_1>.<ext>
    <output_key_2>.<ext>
    ...
```

`report.md` is generated server-side and includes: tool id + name, run id, start/end timestamps, duration, status, input summary, output summary, artefact list with sha-256 hashes, and (if the run had a label) the label.

If `curl` exits non-zero, delete any partial output file and surface the API error verbatim.

### 6. Verify the zip

After download, confirm size and integrity:

```bash
uv run python -c "
import zipfile, pathlib, sys
p = pathlib.Path(sys.argv[1])
with zipfile.ZipFile(p) as z:
    bad = z.testzip()
print({'path': str(p), 'size_bytes': p.stat().st_size, 'entries': len(z.namelist()), 'corrupt': bad})
" "<output path>"
```

If `corrupt` is non-null, surface the bad entry and STOP.

### 7. Confirm to the user

Print one line:

> "Exported run `<run_id_short>` of `<tool_id>` to `<path>` (`<size>`, `<N>` entries)."

Then a second line:

> "The zip contains `inputs.json`, `outputs.json`, a markdown report, and every artefact file. To share, send the zip — the recipient can unzip it with any tool."

### 8. Do NOT run the validator

This skill does not modify any tool — exporting is read-only.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
`<path>` already exists. Pass `--force` to overwrite or pick a different path.
I will not silently clobber an existing file.
```

```
Pixie is not running, so I cannot generate the export. The export endpoint produces
the markdown report from live database state. Start Pixie (`uv run pixie`) and rerun.
```

## Do NOT

- Do NOT overwrite an existing file without `--force`.
- Do NOT include secret values from the tool's `.env` in the export — the API endpoint does not, and you must not synthesise them in either.
- Do NOT export multiple runs in one call — one zip per run keeps provenance clean.
- Do NOT modify the run row, its artefacts, or the tool itself.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically — name them and stop.
