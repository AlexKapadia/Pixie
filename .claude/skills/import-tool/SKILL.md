---
name: import-tool
description: Installs a Pixie tool from a .zip someone packaged via share-tool - unpacks under tools/, runs uv sync, validates. Use when the user has a .zip or says someone shared, sent, or zipped them a tool. Do NOT use for a Git URL (add-tool-from-repo), .py (wrap-local-script), or restoring archived (unarchive-tool).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Install a shared Pixie tool from a zip

You are installing a Pixie tool that someone else packaged with the `share-tool` skill. The zip's top-level folder is the `tool_id`; inside it lives `tool.json`, `pyproject.toml`, `main.py`, and any other tool files.

## Routing check (do this first)

- If the user is providing a Git URL, switch to `add-tool-from-repo`.
- If the user is pointing at a loose `.py` file, switch to `wrap-local-script`.
- If the user is pointing at a `.ipynb`, switch to `add-tool-from-notebook`.
- This skill only triggers when the path ends in `.zip`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

Read these canonical references first. The imported tool must look like this.

- `tools/example-compound-interest/tool.json`
- `tools/example-compound-interest/main.py`
- `tools/example-compound-interest/pyproject.toml`

## Steps

### 1. Inspect the zip's contents

Before extracting anything, list what is inside:

```bash
uv run python -c "
import zipfile, sys
with zipfile.ZipFile(sys.argv[1]) as z:
    for info in z.infolist():
        print(f'{info.file_size:>10}  {info.filename}')
" "<zip path>"
```

### 2. Security checks (refuse on any violation)

Refuse cleanly if the zip contains any of:

- A `.venv/` folder anywhere — someone tried to ship a virtual environment, which is broken across machines and a security smell.
- A `.env` file — someone tried to ship secrets. Refuse and tell them to send the values out-of-band.
- Any executable that is not `.py`, `.toml`, `.json`, `.md`, `.txt`, `.csv`, `.png`, `.jpg`, `.svg`, `.lock`. Native binaries (`.exe`, `.dll`, `.so`, `.dylib`, `.bin`, `.dat` of unknown shape) are a security smell.
- Path traversal entries (`..` segments or absolute paths).
- More than one top-level folder — the zip must contain exactly one directory at root that matches the `tool_id`.

If any of the above apply, surface the refusal block below and STOP.

### 3. Read `tool.json` from inside the zip

```bash
uv run python -c "
import zipfile, json, sys
with zipfile.ZipFile(sys.argv[1]) as z:
    members = [n for n in z.namelist() if n.endswith('tool.json')]
    if len(members) != 1:
        raise SystemExit(f'expected exactly one tool.json, found {len(members)}')
    print(z.read(members[0]).decode('utf-8'))
" "<zip path>"
```

Extract the `id` field. That is the `tool_id` we will install as.

### 4. Check for an existing tool with the same ID

```bash
ls tools/
```

If `tools/<tool_id>/` already exists, ask the user explicitly:

> "Tool `<tool_id>` already exists. Pick one:
> - `overwrite` — delete the existing tool and replace it
> - `fork` — install under a new ID (I'll switch to `fork-tool`)
> - `abort` — do nothing"

If `fork`, STOP and tell the user to invoke `fork-tool` on the existing tool first, then re-invoke this skill. Do not auto-route.
If `abort`, STOP cleanly.
If `overwrite`, proceed to step 5 but first delete the existing folder:

```bash
rm -rf tools/<tool_id>
```

PowerShell alternative: `Remove-Item -Recurse -Force tools/<tool_id>`.

### 5. Extract the zip under `tools/`

```bash
uv run python -c "
import zipfile, pathlib, sys
out = pathlib.Path('tools')
out.mkdir(exist_ok=True)
with zipfile.ZipFile(sys.argv[1]) as z:
    for member in z.infolist():
        # path traversal guard
        target = (out / member.filename).resolve()
        if not str(target).startswith(str(out.resolve())):
            raise SystemExit(f'path traversal blocked: {member.filename}')
    z.extractall(out)
print('extracted into tools/')
" "<zip path>"
```

### 6. Install dependencies

```bash
cd tools/<tool_id> && uv sync
```

### 7. Validator handoff (mandatory final step)

1. From the repo root:
   ```bash
   uv run pixie validate <tool_id> --json
   ```
   Capture the full `ValidationReport` JSON from stdout.

2. Parse the JSON. Branch on `overall`:
   - `"pass"` — report success in one line ("Imported tool `<tool_id>` successfully — refresh your Pixie dashboard."); surface any `warn` checks verbatim.
   - `"warn"` — report success and list every `warn` check verbatim.
   - `"fail"` — DO NOT claim success. Output the entire JSON report verbatim in a fenced `json` block, explain the failing checks in plain language. End with: "Would you like me to hand this off to the `debug-tool` skill?" Then stop.

3. Never paraphrase a failed report.

4. Hard stop after two consecutive failed runs.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't import this zip because <one-sentence reason>.

Shareable Pixie tool zips must contain:
- Exactly one top-level folder named after the tool_id
- `tool.json`, `pyproject.toml`, and `main.py` inside that folder
- Only Python source, config, and small data files

They must NOT contain:
- A `.venv/` (platform-specific, huge)
- A `.env` file (secrets must travel out-of-band, not in a shipped archive)
- Native executables or binaries of unknown shape
- Any `..` path traversal entries

If the zip came from someone else, ask them to repackage it using the
`share-tool` skill, which excludes these by default.
```

## Do NOT

- Do NOT extract `.venv/` or `.env` from the zip under any circumstance.
- Do NOT auto-overwrite an existing tool without explicit confirmation.
- Do NOT trust path entries — guard against `..` traversal.
- Do NOT install system packages via apt/brew/choco.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT add authentication, sessions, or multi-user concepts.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
