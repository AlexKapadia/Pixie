---
name: copy-to-clipboard
description: Copies a small TEXTUAL Pixie output (text, markdown, number, boolean, json, csv, kv, log) to the system clipboard. Use when the user asks to copy, clipboard, grab, or yank a small text output. Do NOT use for binary outputs (export-as-format) or to copy a file to a path (copy-output-to).
allowed-tools: Bash, Read
---

# Copy a small Pixie output to the system clipboard

You put a Pixie output's value onto the system clipboard as text. Only small textual outputs are supported: `text`, `markdown`, `number`, `boolean`, `kv` (as JSON), `json`, `csv` (as text), `log` (as text), `stream_text`. Binary outputs (image, audio, video, file, charts) refuse — those need `export-as-format`.

## Routing check (do this first)

- If the output is BINARY (image, audio, video, file, chart_*, map_*), STOP and switch to `export-as-format`. Clipboard is text-only.
- If the user wants to write to a file on disk, switch to `copy-output-to` (raw bytes) or `export-as-format` (converted).
- If the user wants to copy a TOOL (the code), switch to `share-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Resolve the run + output_key

Accept any of:
- `run_id` + `output_key`
- `artefact_id` (the skill resolves its run + output_key from `/api/artefacts/<id>`)
- A unique substring of the output filename

Resolve via:

```bash
curl -s "http://127.0.0.1:8765/api/artefacts?q=<query>&limit=20"
```

If zero matches, STOP — suggest `find-output` or `list-outputs`. If multiple, list and ask.

### 2. Check the output type

Fetch metadata:

```bash
curl -s "http://127.0.0.1:8765/api/artefacts/<id>"
```

If the declared output type is binary (image, audio, video, file, chart_*, map_*, latex when rendered to PDF), REFUSE — point the user at `export-as-format`. Charts as `json` data or `csv` data are textual and allowed; charts as `png` are not.

Size guard: if the textual payload exceeds 1 MB, refuse and suggest `export-as-format` instead (the system clipboard isn't a good home for huge blobs).

### 3. Confirm Pixie is reachable

```bash
curl -s http://127.0.0.1:8765/api/healthz
```

If Pixie is offline, STOP — the clipboard endpoint serialises the output's value server-side from `pixie.db`. Tell the user to start Pixie (`uv run pixie`) and rerun.

### 4. Fetch the clipboard-ready string

```bash
curl -s -f "http://127.0.0.1:8765/api/clipboard?run_id=<run_id>&output_key=<key>&fmt=text" -o /tmp/pixie-clipboard.txt
```

On Windows, write to `$env:TEMP/pixie-clipboard.txt` instead.

The endpoint normalises the output to a single textual representation: `text`/`markdown`/`log`/`stream_text` → raw string; `number`/`boolean` → string form; `kv`/`json` → pretty-printed JSON; `csv` → CSV text.

If `curl` exits non-zero, surface the API error verbatim and STOP.

### 5. Put it on the system clipboard

Try `pyperclip` first; fall back to OS-native tools on failure.

```bash
uv run python -c "
import pathlib, sys, subprocess, platform
text = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
try:
    import pyperclip
    pyperclip.copy(text)
    print({'ok': True, 'via': 'pyperclip', 'bytes': len(text.encode('utf-8'))})
except Exception as e:
    sysname = platform.system()
    if sysname == 'Darwin':
        subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=True)
        via = 'pbcopy'
    elif sysname == 'Windows':
        subprocess.run(['clip.exe'], input=text.encode('utf-16le'), check=True)
        via = 'clip.exe'
    else:
        for cmd in (['wl-copy'], ['xclip','-selection','clipboard'], ['xsel','--clipboard','--input']):
            try:
                subprocess.run(cmd, input=text.encode('utf-8'), check=True)
                via = cmd[0]; break
            except FileNotFoundError:
                continue
        else:
            print({'ok': False, 'error': 'no clipboard tool found (install wl-clipboard, xclip, or xsel)'}); sys.exit(2)
    print({'ok': True, 'via': via, 'bytes': len(text.encode('utf-8'))})
" /tmp/pixie-clipboard.txt
```

If the fallback chain finds NO clipboard tool, STOP — tell the user to install `pyperclip` (`uv add pyperclip` in their environment) or a native clipboard helper.

### 6. Clean up the temp file

```bash
rm -f /tmp/pixie-clipboard.txt
```

On Windows, `Remove-Item "$env:TEMP/pixie-clipboard.txt" -ErrorAction SilentlyContinue`.

### 7. Confirm to the user

One line:

> "Copied output `<output_key>` from run `<run_id_short>` of `<tool_id>` to the clipboard (`<bytes>` bytes, via `<via>`)."

### 8. Do NOT run the validator

This skill does not modify any tool.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
Output `<key>` is type `<type>`, which is binary. Clipboard is text-only.
Use `export-as-format` to write it to a file in a viewer-supported format.
```

```
Output `<key>` is `<size>` MB — too large for the clipboard.
Use `export-as-format` to save it to a file, or `copy-output-to` to copy the raw bytes.
```

```
Pixie is not running. The clipboard endpoint reads the output value from pixie.db.
Start Pixie (`uv run pixie`) and rerun.
```

```
No clipboard tool found on this system. Install one:
  macOS:   pbcopy is built in (this should not have failed)
  Windows: clip.exe is built in (this should not have failed)
  Linux:   `apt install xclip` or `apt install wl-clipboard`
Or `uv add pyperclip` in your Python environment.
```

## Do NOT

- Do NOT attempt to put binary data on the clipboard — refuse for image/audio/video/file types.
- Do NOT silently truncate text — refuse if over 1 MB.
- Do NOT modify the source artefact or run row.
- Do NOT leave temp files behind — clean up step 6 always runs.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically — name them and stop.
