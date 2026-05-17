---
name: rename-tool
description: Renames an existing Pixie tool - changes its id, folder name, and tool.json name, updates run-history references, then re-validates. Use when the user asks to rename, change the id of, or re-slug a TOOL. Does NOT modify behaviour (update-tool), delete (remove-tool), or label a run (label-run).
allowed-tools: Bash, Read, Write, Edit, Glob
---

# Rename a Pixie tool

You are changing a tool's `id` (and its folder name to match). This is mildly destructive — it breaks bookmarks, breaks any cached URL the user has, and rewrites historical references in `pixie.db`. Confirm with the user before proceeding.

## Routing check (do this first)

- If the user wants to duplicate (keep the original AND create a new copy), switch to `fork-tool`.
- If the user wants to permanently delete the tool, switch to `remove-tool`.
- If the user wants to change the display `name` (not the `id`), switch to `update-tool` — display name changes are non-destructive and live entirely in `tool.json`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Identify the source tool and the new ID

If the user did not name both, ask. Both required:

- **Old ID** — must exist as `tools/<old_id>/`.
- **New ID** — must be kebab-case `[a-z0-9-]`, must NOT already exist under `tools/`.

Verify:

```bash
ls tools/<old_id>/tool.json 2>&1
ls tools/<new_id> 2>&1
```

If the old tool does not exist, STOP and tell the user. If `tools/<new_id>/` already exists, STOP and ask the user to pick a different ID — do not overwrite.

### 2. Confirm with the user

Explicit prompt:

> "About to rename `<old_id>` → `<new_id>`. This will:
> - Stop the tool if it's currently warm.
> - Rename the folder `tools/<old_id>/` → `tools/<new_id>/`.
> - Update `tool.json`'s `id` field.
> - Rewrite historical references in `pixie.db` (`runs.tool_id`, `tool_state.tool_id`, `validation_reports.tool_id`).
>
> Any bookmark or saved URL pointing at `/tool/<old_id>` will stop working. Proceed? (yes/no)"

Wait for an explicit yes. Anything else, STOP.

### 3. Stop the tool if running (best effort)

```bash
uv run python -c "
import httpx, os
port = os.environ.get('PIXIE_PORT', '7860')
try:
    httpx.post(f'http://127.0.0.1:{port}/api/tools/<old_id>/stop', timeout=5.0)
    print('stopped')
except Exception as e:
    print('not stopped: ' + str(e))
"
```

Don't fail the skill if Pixie isn't running — the rename can still proceed.

### 4. Rename the folder

Cross-platform via Python:

```bash
uv run python -c "
import pathlib
pathlib.Path('tools/<old_id>').rename(pathlib.Path('tools/<new_id>'))
print('renamed')
"
```

If this fails (`PermissionError`), the folder still has open file handles — usually a venv Python process. Tell the user to close anything using the folder and re-run.

### 5. Update `tool.json` in the new location

`Edit` `tools/<new_id>/tool.json`. Change the `id` field from `<old_id>` to `<new_id>`. Leave `name`, `description`, inputs, outputs, secrets, and limits untouched.

### 6. Rewrite db references

```bash
uv run python -c "
import sqlite3, pathlib
db = pathlib.Path('pixie.db')
if not db.exists():
    print('no db, skipping'); raise SystemExit
con = sqlite3.connect(db)
for table in ('runs', 'tool_state', 'validation_reports'):
    try:
        cur = con.execute(f'UPDATE {table} SET tool_id=? WHERE tool_id=?', ('<new_id>', '<old_id>'))
        print(f'{table}: {cur.rowcount} rows updated')
    except sqlite3.OperationalError as e:
        print(f'{table}: skipped ({e})')
con.commit()
"
```

If `pixie.db` does not exist, this is a no-op — the rename is just the filesystem change.

### 7. Validator handoff (mandatory final step)

1. From the repo root:
   ```bash
   uv run pixie validate <new_id> --json
   ```

2. Parse the JSON. Branch on `overall`:
   - `"pass"` — report success in one line. Surface any `warn` checks verbatim.
   - `"warn"` — report success and list every `warn` check verbatim.
   - `"fail"` — DO NOT claim success. Output the entire JSON in a fenced `json` block. The most likely cause is that the `id` field in `tool.json` doesn't match the new folder name — re-check step 5. End with: "Would you like me to hand this off to the `debug-tool` skill?" Stop.

3. Never paraphrase a failed report.

4. Hard stop after two consecutive failed runs.

### 8. Confirm completion

After a passing validator:

> "Renamed `<old_id>` → `<new_id>`. Refresh the Pixie dashboard to see the new ID in the sidebar."

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I won't rename `<old_id>` to `<new_id>` because `tools/<new_id>/` already
exists. Pick a different new ID, or remove the existing one first with
`remove-tool`.
```

## Do NOT

- Do NOT rename without explicit user confirmation.
- Do NOT overwrite an existing destination folder.
- Do NOT touch the `.venv` directory — the rename moves it intact.
- Do NOT touch the `data/` directory contents — they move intact with the folder.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT add authentication or multi-user concepts.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
