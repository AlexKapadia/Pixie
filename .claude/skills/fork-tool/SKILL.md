---
name: fork-tool
description: Duplicates an existing Pixie tool under a new id with its own .venv so the copy can be customised independently. Use when the user asks to copy, duplicate, fork, or branch a Pixie tool. Do NOT use for cloning a Git repo (add-tool-from-repo) or just renaming one tool (rename-tool).
allowed-tools: Bash, Read, Write, Edit, Glob
---

# Fork an existing Pixie tool

You are duplicating `tools/<old_id>/` to `tools/<new_id>/` so the user can experiment without disturbing the original. The fork is fully independent — its own venv, its own `tool.json` with a new `id` and `name`.

## Routing check (do this first)

- If the user wants to share the tool with someone else, switch to `share-tool`.
- If the user wants to install a tool received from someone else, switch to `import-tool`.
- If the user wants to modify the original in place, switch to `update-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Identify the source tool

If the user did not name a tool, list available tools:

```bash
ls tools/
```

Then ask which one to fork. Verify `tools/<old_id>/` exists and is well-formed (contains `tool.json`, `pyproject.toml`, `main.py`).

### 2. Pick the new ID and name

Ask the user for:

- The **new ID** — must be kebab-case `[a-z0-9-]`, must not already exist under `tools/`.
- The **new display name** — default to `"<original name> (fork)"`; let the user override.

Verify the new ID does not collide:

```bash
ls tools/<new_id> 2>&1 || true
```

If `tools/<new_id>/` already exists, STOP and ask the user to pick a different ID. Do not overwrite.

### 3. Copy the folder (excluding `.venv`)

```bash
uv run python -c "
import pathlib, shutil
src = pathlib.Path('tools/<old_id>')
dst = pathlib.Path('tools/<new_id>')
def ignore(_dir, names):
    return [n for n in names if n in {'.venv', '__pycache__', '.pytest_cache', '.mypy_cache'} or n.endswith('.pyc')]
shutil.copytree(src, dst, ignore=ignore)
print(f'copied to {dst}')
"
```

This is cross-platform — works the same on Windows, macOS, Linux. Do not use shell `cp -r` (the `.venv` exclude is awkward) or PowerShell `Copy-Item` (different syntax across versions).

Note: `data/` IS copied by default — the user may want to fork with state. If they want a clean fork, they can delete `tools/<new_id>/data/` manually after.

### 4. Update `tool.json`

`Edit` `tools/<new_id>/tool.json`:

- Change `id` from `<old_id>` to `<new_id>`.
- Change `name` to the chosen display name.

Leave everything else untouched — same inputs, outputs, secrets, category, limits.

### 5. Install dependencies for the fork

```bash
cd tools/<new_id> && uv sync
```

Each tool owns its own venv. The fork's venv is independent from the original's.

### 6. Validator handoff (mandatory final step)

1. From the repo root:
   ```bash
   uv run pixie validate <new_id> --json
   ```
   Capture the full `ValidationReport` JSON from stdout.

2. Parse the JSON. Branch on `overall`:
   - `"pass"` — report success in one line ("Forked `<old_id>` to `<new_id>` successfully — refresh your Pixie dashboard."); surface any `warn` checks verbatim.
   - `"warn"` — report success and list every `warn` check verbatim.
   - `"fail"` — DO NOT claim success. Output the entire JSON report verbatim in a fenced `json` block, explain the failing checks in plain language. End with: "Would you like me to hand this off to the `debug-tool` skill?" Then stop.

3. Never paraphrase a failed report.

4. Hard stop after two consecutive failed runs.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't fork this tool because <one-sentence reason>.

A fork requires:
- The source tool exists under tools/<old_id>/ and is well-formed
- The new ID is kebab-case and does not collide with an existing tool

If the original tool is broken, run `debug-tool` on it first. If the new
ID is taken, pick another one — I won't overwrite an existing tool here
(use `import-tool` with `overwrite` for that, or `remove-tool` first).
```

## Do NOT

- Do NOT overwrite an existing `tools/<new_id>/`. Always ask for a different ID.
- Do NOT copy the source tool's `.venv/`. The fork must build its own.
- Do NOT modify the source tool. The fork is independent.
- Do NOT carry the original `id` value in the new `tool.json` — Pixie indexes by ID, and a duplicate ID would break discovery.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT add authentication, sessions, or multi-user concepts.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
