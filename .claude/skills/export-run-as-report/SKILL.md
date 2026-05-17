---
name: export-run-as-report
description: Packages ONE Pixie run as a RENDERED markdown report.md plus an assets/ folder of artefacts (not raw JSON). Use when the user asks for a report, write-up, summary, or human-readable record of a run. Do NOT use for a raw JSON zip (export-run), one artefact (export-as-format), or many runs (bulk-export).
allowed-tools: Bash, Read
---

# Export a Pixie run as a markdown report + assets

You package ONE run into a zip containing a rendered `report.md`, an `assets/` folder with every artefact, plus the raw `inputs.json` and `outputs.json` for provenance. The report is human-readable: tool metadata, inputs, every output rendered inline (or referenced from assets/), timing, and a hash manifest.

## Routing check (do this first)

- If the user wants the raw zip (no rendered markdown, just inputs/outputs/assets), switch to `export-run`. This skill ADDS a rendered report; `export-run` does not.
- If the user wants ONE artefact converted to a different format, switch to `export-as-format`.
- If the user wants to share the TOOL's CODE (not its run data), switch to `share-tool`.
- If the user wants multiple runs bundled, switch to `bulk-export`.
- If the user wants a one-line summary, point them at `view-runs` and stop — that's not what this skill does.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Note on overlap with `export-run`

`export-run` and `export-run-as-report` both export a single run. The difference:
- `export-run` = raw zip: `inputs.json`, `outputs.json`, `assets/`.
- `export-run-as-report` = the same zip PLUS a rendered `report.md` that humans can read directly.

If unsure which the user wants, ask: "Do you want a raw zip for archiving, or a rendered markdown report to share?"

## Steps

### 1. Resolve the run_id

Accept a full `run_id` or short prefix. Resolve via the API:

```bash
curl -s "http://127.0.0.1:8765/api/runs?run_id_prefix=<prefix>&limit=10"
```

If zero matches, STOP — suggest `view-runs`. If multiple, list and ask. If the user described the run by tool + recency, run `view-runs <tool_id>` first to enumerate.

### 2. Decide the output path

Default: `~/Downloads/<tool_id>-<run_id_short>-report.zip` where `<run_id_short>` is the first 8 chars.

If the user supplied a path:
- If it's a directory, append the default filename.
- If it's a filename, use it as-is.
- Verify the parent directory exists:

```bash
ls "<parent dir>"
```

If parent missing, refuse — Pixie skills do not create arbitrary parent directories.

### 3. Refuse to overwrite

If destination exists AND no `--force`, STOP:

> "`<dest>` already exists. Pass `--force` to overwrite or choose a different path."

### 4. Confirm Pixie is reachable

```bash
curl -s http://127.0.0.1:8765/api/healthz
```

If Pixie is offline, STOP — the report is generated server-side from live db state. Tell the user to start Pixie (`uv run pixie`) and rerun.

### 5. Stream the report zip from the API

```bash
curl -s -f -o "<dest>" "http://127.0.0.1:8765/api/runs/<run_id>/report?include_assets=true"
```

The endpoint streams a zip with this layout:

```
<run_id_short>/
  report.md          # rendered human-readable report
  inputs.json        # raw input payload
  outputs.json       # raw output payload (with _artefact pointers rehydrated)
  assets/
    <output_key_1>.<ext>
    <output_key_2>.<ext>
    ...
  manifest.json      # filename + sha-256 + size per asset
```

`report.md` includes: tool id + name + version, run id, start/end timestamps, duration, status, declared inputs with values, every declared output rendered inline (text/markdown/number/kv embedded; binary outputs referenced as `![name](assets/name.png)` or download link), label/tags if set, and a one-line provenance footer.

If `curl` exits non-zero, delete any partial output and surface the API error verbatim.

### 6. Verify the zip

```bash
uv run python -c "
import zipfile, pathlib, sys
p = pathlib.Path(sys.argv[1])
with zipfile.ZipFile(p) as z:
    bad = z.testzip()
    names = z.namelist()
print({'path': str(p), 'size_bytes': p.stat().st_size, 'entries': len(names), 'has_report': any(n.endswith('report.md') for n in names), 'corrupt': bad})
" "<dest>"
```

If `corrupt` is non-null OR `has_report` is False, STOP and surface a corruption warning.

### 7. Confirm to the user

One line:

> "Exported report for run `<run_id_short>` of `<tool_id>` to `<dest>` (`<size>`, `<N>` entries, `report.md` included)."

Second line:

> "Unzip and open `report.md` in any markdown viewer. The `assets/` folder holds every output file."

### 8. Do NOT run the validator

This skill does not modify any tool — exporting is read-only.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
`<dest>` already exists. Pass `--force` to overwrite or pick a different path.
```

```
Pixie is not running, so I cannot generate the report. The report renderer runs
server-side and reads from `pixie.db`. Start Pixie (`uv run pixie`) and rerun.
```

```
Parent directory `<dir>` does not exist. Create it first, then rerun.
```

```
The downloaded zip is missing `report.md` or is corrupt. The destination has been
left in place for inspection but should not be shared.
```

## Do NOT

- Do NOT overwrite an existing file without `--force`.
- Do NOT include secret values from `.env` — the API endpoint omits them and you must too.
- Do NOT bundle multiple runs in one call — use `bulk-export` for that.
- Do NOT modify the run row, its artefacts, or the tool itself.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically — name them and stop.
