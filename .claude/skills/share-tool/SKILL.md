---
name: share-tool
description: Packages a Pixie tool's SOURCE CODE folder into a sendable .zip - excludes .venv, data/, .env so secrets don't leak. Use when the user asks to share, package, or send a TOOL to someone. Do NOT use to export run outputs (export-run, export-run-as-report, bulk-export) or install an incoming zip (import-tool).
allowed-tools: Bash, Read, Glob
---

# Package a Pixie tool for sharing

You are packaging a `tools/<tool_id>/` folder into a single zip so the user can send it to someone else. The recipient will install it with the `import-tool` skill.

## Routing check (do this first)

- If the user is asking to install a zip they received, this is the wrong skill — switch to `import-tool`.
- If the user wants to duplicate a tool locally for experimentation, switch to `fork-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Confirm the tool exists

If the user did not name a tool, list available tools:

```bash
ls tools/
```

Then ask which one. Verify the folder `tools/<tool_id>/` exists and contains at minimum `tool.json`, `pyproject.toml`, and `main.py`. If any of those are missing, STOP and tell the user the tool looks malformed — suggest running `debug-tool` first.

### 2. Decide the output path

Default: `<tool_id>-<version>.zip` at the repo root, where `<version>` comes from `tool.json`'s `version` field (or `0.0.0` if missing).

If the user specified a different path, use that. Verify the parent directory exists:

```bash
ls "<parent of chosen path>"
```

### 3. Show the user what will be included

Before zipping, list everything that will go in and everything that will be excluded. Excluded by policy: `.venv/`, `.env`, `data/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `uv.lock` (optional — keep this so the recipient gets the same locked versions). Included: everything else under `tools/<tool_id>/`.

```bash
uv run python -c "
import pathlib, sys
root = pathlib.Path('tools/<tool_id>')
exclude = {'.venv', '.env', 'data', '__pycache__', '.pytest_cache', '.mypy_cache'}
for path in sorted(root.rglob('*')):
    rel = path.relative_to(root)
    if any(part in exclude or part.endswith('.pyc') for part in rel.parts):
        continue
    if path.is_file():
        print(rel.as_posix())
"
```

Show the list. Ask the user to confirm before proceeding.

### 4. Build the zip

```bash
uv run python -c "
import pathlib, zipfile, sys
tool_id = '<tool_id>'
out = pathlib.Path('<output path>')
root = pathlib.Path(f'tools/{tool_id}')
exclude = {'.venv', '.env', 'data', '__pycache__', '.pytest_cache', '.mypy_cache'}
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as z:
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if any(part in exclude or part.endswith('.pyc') for part in rel.parts):
            continue
        if path.is_file():
            z.write(path, arcname=pathlib.PurePosixPath(tool_id, rel.as_posix()))
print(f'Wrote {out} ({out.stat().st_size} bytes)')
"
```

The zip's top-level folder is the tool_id itself — this matches what `import-tool` expects.

### 5. Confirm completion

Tell the user the zip path, its size in bytes, and a one-line reminder: "Send this to the recipient. They can install it with the `import-tool` skill in their own Pixie repo."

### 6. Do not run the validator

Packaging does not modify the tool. The validator is not the right tool here — if the user wants to confirm the tool is healthy before sending, suggest they run `revalidate-all` separately first.

## Cross-platform note

The Python one-liner above is portable. Do not use shell-native `zip`/`7z`/`tar` — they vary across platforms (Windows users may not have any of them installed). `uv run python` is always available because the user is in a Pixie repo.

For very large tools, the one-liner may exceed shell argument limits when pasted inline. If that becomes a problem, write the script to a temporary file under `$env:TEMP` (Windows) or `/tmp` (POSIX) and run it with `uv run python <path>`.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I won't include <`.env` | `.venv/` | `data/`> in the zip. Those folders
contain secrets, machine-specific binaries, or local-only state that
shouldn't leave your machine. If you genuinely need to share secret
values with the recipient, send them out-of-band (a password manager,
not a zip).
```

## Do NOT

- Do NOT include `.env`. Secrets must never leave the user's machine.
- Do NOT include `.venv/`. The venv is platform-specific and huge.
- Do NOT include `data/`. That folder may contain run history or local user state.
- Do NOT add a hidden license, signing key, or any auto-extracted hook into the zip.
- Do NOT bind to `0.0.0.0` or upload the zip anywhere — this skill writes a local file only.
- Do NOT invoke other Pixie skills programmatically.
