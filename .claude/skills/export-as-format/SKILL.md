---
name: export-as-format
description: Converts ONE saved Pixie artefact to a chosen format (PNG, SVG, PDF, XLSX, CSV, MP3) via the server-side exporter. Use when the user asks to export, convert, save as, or download an output AS a different format. Do NOT use for unchanged copy (copy-output-to), clipboard (copy-to-clipboard), or whole run (export-run).
allowed-tools: Bash, Read
---

# Export a Pixie artefact in a chosen format

You convert ONE saved artefact to a user-chosen format via Pixie's exporter dispatcher. Conversion is server-side; the skill only resolves the artefact, picks the format, calls the API, and writes the bytes to disk.

## Routing check (do this first)

- If the user wants the file COPIED unchanged (no conversion), switch to `copy-output-to`.
- If the user wants the WHOLE run as a markdown report + assets zip, switch to `export-run-as-report`.
- If the user wants a raw run zip (inputs.json + outputs.json + assets, no rendered report), switch to `export-run`.
- If the user wants many runs or artefacts bundled together, switch to `bulk-export`.
- If the user wants to drop a file into a named destination folder, switch to `send-to-folder`.
- If the user wants small text on the clipboard, switch to `copy-to-clipboard`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Supported formats per output type

Source of truth: `DECISIONS.md` → "Export-everything" matrix. Summary:

| Output type | Default | Also supports |
|---|---|---|
| text | txt | md, pdf, docx, html |
| markdown | md | html, pdf, docx, txt |
| number | txt | json, csv |
| boolean | txt | json |
| kv | json | csv, yaml, toml, md |
| table | csv | xlsx, parquet, json, md, html, tsv |
| chart_* | png | svg, pdf, html, json, csv |
| map_* | png | geojson, gpx, kml, html |
| image | original | png, jpg, webp, pdf |
| image_grid | zip | individual files |
| image_compare | png | zip |
| audio | original | wav, mp3, flac, ogg |
| video | original | mp4, webm, gif |
| latex | tex | pdf, png |
| code | original | source ext, html, png |
| diff | patch | html, pdf |
| tree | json | yaml, md |
| timeline | json | csv, ical, png |
| gantt | csv | png, json |
| log | txt | jsonl, csv |
| stream_text | txt | md |
| file | original | (already a file) |

If the user has not chosen a format, list the supported formats for that artefact's output type and ask.

## Steps

### 1. Resolve the artefact id

Accept a numeric `artefact_id`, a `run_id + output_key` pair, or a unique substring of the filename. Resolve via the API:

```bash
curl -s "http://127.0.0.1:8765/api/artefacts?q=<query>&limit=20"
```

If zero matches, STOP — suggest `find-output` or `list-outputs`. If multiple, list and ask.

### 2. Identify the output type

The artefact row includes `mime` and (via its run) the declared output type. Fetch metadata:

```bash
curl -s "http://127.0.0.1:8765/api/artefacts/<id>"
```

Map mime/type to the matrix above to enumerate supported formats.

### 3. Pick the target format

- If the user supplied a format, validate it against the matrix for this output type.
- If the format is NOT supported, refuse with a clear message AND suggest the closest supported alternatives.
- If the user did not pick, list the supported formats and ask.

### 4. Decide the output path

Default: `~/Downloads/<safe-name>.<fmt>` where `<safe-name>` is the artefact's original filename stem sanitised to `[a-zA-Z0-9._-]`.

If the user supplied a path:
- If it is a directory (ends in `/` or is an existing dir), append the default filename.
- If it is a filename, use it as-is.
- Verify the parent directory exists:

```bash
ls "<parent dir>"
```

If parent missing, refuse — Pixie skills do not create arbitrary parent directories.

### 5. Refuse to overwrite

If destination exists AND no `--force`, STOP:

> "`<dest>` already exists. Pass `--force` to overwrite or choose a different path."

### 6. Confirm Pixie is reachable

```bash
curl -s http://127.0.0.1:8765/api/healthz
```

If Pixie is offline, STOP — exporters run server-side (they may need pillow, openpyxl, kaleido, ffmpeg). Tell the user to start Pixie (`uv run pixie`) and rerun.

### 7. Stream the export from the API

```bash
curl -s -f -o "<dest>" "http://127.0.0.1:8765/api/artefacts/<id>/export?format=<fmt>"
```

Additional query params (resize, quality, encoding) may be passed if the user asked. Examples:

- `&width=1920` for image resize
- `&dpi=300` for PDF render
- `&bitrate=192k` for audio re-encode

If `curl` exits non-zero, delete any partial output and surface the API error verbatim.

### 8. Verify the result

Confirm the file is non-empty:

```bash
uv run python -c "
import pathlib, sys
p = pathlib.Path(sys.argv[1])
print({'path': str(p), 'size_bytes': p.stat().st_size})
" "<dest>"
```

If `size_bytes` is 0, STOP and surface an error — the export pipeline produced an empty file.

### 9. Confirm to the user

One line:

> "Exported artefact `<name>` from run `<run_id_short>` as `<fmt>` to `<dest>` (`<size>`)."

### 10. Do NOT run the validator

This skill does not modify any tool — exporting is read-only.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
Format `<fmt>` is not supported for output type `<type>`.
Supported formats for `<type>`: <list>.
Pick one of those, or use `copy-output-to` to copy the original file unchanged.
```

```
`<dest>` already exists. Pass `--force` to overwrite or pick a different path.
```

```
Pixie is not running, so I cannot run the exporter. Format conversion uses
server-side libraries (pillow, openpyxl, kaleido, ffmpeg). Start Pixie
(`uv run pixie`) and rerun.
```

```
Parent directory `<dir>` does not exist. Create it first, then rerun.
```

## Do NOT

- Do NOT silently substitute a different format when the user asks for an unsupported one — refuse and list alternatives.
- Do NOT overwrite an existing file without `--force`.
- Do NOT bundle multiple artefacts in one call — use `bulk-export` for that.
- Do NOT modify the source artefact.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically — name them and stop.
