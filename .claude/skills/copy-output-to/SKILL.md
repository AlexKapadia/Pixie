---
name: copy-output-to
description: Copies ONE saved Pixie artefact file byte-for-byte to a user-supplied filesystem path. Use when the user asks to copy, save, write, or move ONE specific output to a one-off file or folder path. Do NOT use for a named recurring destination (send-to-folder), clipboard (copy-to-clipboard), or format conversion (export-as-format).
allowed-tools: Bash, Read
---

# Copy a Pixie artefact to disk

You are copying ONE saved artefact file out of `artefacts/<tool>/<run>/<file>` to a destination path the user supplies. The copy is byte-for-byte; metadata is preserved where the OS supports it.

## Routing check (do this first)

- If the user wants the FULL run (inputs, outputs, all artefacts, report) as a zip, switch to `export-run`.
- If the user wants to OPEN the artefacts folder in their file browser instead of copying one file, switch to `open-artefacts-folder`.
- If the user wants to find which artefact to copy, switch to `find-output` or `list-outputs`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Resolve the artefact id

The user must identify ONE artefact. Accept:

- A numeric `artefact_id` from the database.
- A run_id + filename pair (e.g. "the vocals.wav from run abc12345").
- A unique substring of the filename if it matches only one artefact across the index.

Resolve via the API:

```bash
curl -s "http://127.0.0.1:8765/api/artefacts?q=<query>&limit=20"
```

If zero matches, STOP — suggest `find-output` or `list-outputs`. If multiple, list them and ask which.

### 2. Decide the destination path

Required: `--to <path>` (or positional second argument). The user MUST supply it. If missing, STOP and ask.

If the path is a directory, append the artefact's original filename. If the path ends in a filename, use it as-is. If the parent directory does not exist:

```bash
ls "<parent dir>"
```

If parent missing, refuse — tell the user the directory does not exist and suggest creating it first (Pixie skills do not create arbitrary directories on disk for the user).

### 3. Refuse to overwrite

If the destination already exists AND the user did NOT pass `--force`, STOP:

> "`<dest>` already exists. Pass `--force` to overwrite or choose a different path."

### 4. Fetch the file (Pixie running)

```bash
curl -s -f -o "<dest>" "http://127.0.0.1:8765/api/artefacts/<id>/file"
```

The endpoint sets `Content-Disposition: attachment; filename=<original>`. The byte stream is identical to the source file.

### 4b. Fallback (Pixie offline)

If `curl` to `/api/healthz` fails, read the file directly from disk. The path is `artefacts/<rel_path>` where `rel_path` comes from the artefact row.

Query the `artefacts` table for the path:

```bash
uv run python -c "
import sqlite3, pathlib, shutil, sys
conn = sqlite3.connect(pathlib.Path('pixie.db'))
row = conn.execute('SELECT rel_path FROM artefacts WHERE id = ?', (int(sys.argv[1]),)).fetchone()
if not row:
    print('no such artefact'); sys.exit(2)
src = pathlib.Path('artefacts') / row[0]
dst = pathlib.Path(sys.argv[2])
shutil.copy2(src, dst)
print({'src': str(src), 'dst': str(dst), 'bytes': dst.stat().st_size})
" "<id>" "<dest>"
```

### 5. Verify the copy

After the copy, confirm size and sha-256 match the database row:

```bash
uv run python -c "
import hashlib, pathlib, sqlite3, sys
p = pathlib.Path(sys.argv[1])
h = hashlib.sha256(p.read_bytes()).hexdigest()
conn = sqlite3.connect(pathlib.Path('pixie.db'))
expected = conn.execute('SELECT sha256, size_bytes FROM artefacts WHERE id = ?', (int(sys.argv[2]),)).fetchone()
print({'ok': h == expected[0] and p.stat().st_size == expected[1], 'sha256': h, 'expected_sha256': expected[0]})
" "<dest>" "<id>"
```

If `ok` is false, STOP and surface a corruption warning — do not silently confirm a bad copy.

### 6. Confirm to the user

Print one line:

> "Copied `<filename>` from run `<run_id_short>` of `<tool_id>` to `<dest>` (`<size>`, sha-256 verified)."

### 7. Do NOT run the validator

This skill does not modify any tool.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
You need to tell me where to copy it. Pass a destination path, e.g.
`copy-output-to <artefact-id> --to ~/Desktop/transcript.txt`.
```

```
`<dest>` already exists. Pass `--force` to overwrite or pick a different path.
```

```
Parent directory `<dir>` does not exist. Create it first, then rerun.
```

```
SHA-256 mismatch after copy — the destination file does not match the source.
The destination has been left in place for inspection but is corrupt. Do not use it.
```

## Do NOT

- Do NOT overwrite an existing file without `--force`.
- Do NOT copy multiple artefacts in one call — one file per invocation keeps intent clear. Use `export-run` for bulk.
- Do NOT modify, rename, or delete the source artefact.
- Do NOT silently confirm a corrupt copy — sha-256 mismatch is a hard stop.
- Do NOT create arbitrary parent directories on disk — refuse if the parent is missing.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically — name them and stop.
