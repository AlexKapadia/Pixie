---
name: workspace-remove-tool
description: Removes one Pixie tool from one workspace via tool_workspaces - the tool itself is untouched. Use when the user asks to remove, unassign, ungroup, or take a NAMED tool OUT of a workspace, project, or section. Do NOT use to delete the tool (remove-tool), archive (archive-tool), or delete the workspace.
allowed-tools: Bash, Read, Glob
---

# Remove a Pixie tool from a workspace

You are deleting one row from the `tool_workspaces` join table. The tool itself stays installed, its files are untouched, and its `.venv/` is left alone. The tool just no longer appears under that workspace in the sidebar. It may still belong to other workspaces.

## Routing check (do this first)

- If the user wants to permanently delete the tool itself, switch to `remove-tool`.
- If the user wants to hide it from the sidebar entirely and free disk, switch to `archive-tool`.
- If the user wants to delete the whole workspace and all its links, this skill is for one link only — refuse and ask whether they want to delete the workspace via the Pixie API directly.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Gather the inputs

You need two ids:

1. The `tool_id` — which tool to unlink.
2. The `workspace_id` — which workspace to unlink it from.

If the user said something like "take the geocoder out of quant research", derive both as in `workspace-add-tool`. Verify against disk and database before writing.

### 2. Verify the link exists

```bash
uv run python -c "import sqlite3, pathlib; conn = sqlite3.connect(pathlib.Path('pixie.db')); row = conn.execute('SELECT 1 FROM tool_workspaces WHERE tool_id = ? AND workspace_id = ?', ('<tool_id>', '<workspace_id>')).fetchone(); print('exists' if row else 'missing')"
```

If `missing`, tell the user the tool is not in that workspace, then stop. No-op is success here.

### 3. Delete the link

Prefer the Pixie API:

```bash
curl -s -X DELETE http://127.0.0.1:7860/api/workspaces/<workspace_id>/tools/<tool_id>
```

If Pixie is not running, fall back to a direct delete:

```bash
uv run python -c "import sqlite3, pathlib; conn = sqlite3.connect(pathlib.Path('pixie.db')); conn.execute('DELETE FROM tool_workspaces WHERE tool_id = ? AND workspace_id = ?', ('<tool_id>', '<workspace_id>')); conn.commit(); conn.close(); print('unlinked')"
```

### 4. Report completion

Query the tool's remaining workspaces so the user knows where it still lives:

```bash
uv run python -c "import sqlite3, pathlib; conn = sqlite3.connect(pathlib.Path('pixie.db')); rows = conn.execute('SELECT workspace_id FROM tool_workspaces WHERE tool_id = ?', ('<tool_id>',)).fetchall(); print(','.join(r[0] for r in rows) or 'none')"
```

Then report:

> "Removed `<tool_id>` from workspace `<workspace_id>`. The tool is still installed. Remaining workspaces: `<list>` (or `none` — it now only appears in the flat sidebar)."

### 5. Do NOT run the validator

This skill does not modify the tool itself. Skip the validator handoff.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I will only unlink one tool from one workspace at a time in this skill. If you
want to delete the whole workspace, that is a different operation — call the
Pixie API directly: `DELETE /api/workspaces/<workspace_id>`. (Tools in that
workspace will keep existing; only the workspace and its links go.)
```

## Do NOT

- Do NOT delete the tool itself — that is `remove-tool`.
- Do NOT archive the tool — that is `archive-tool`.
- Do NOT delete the workspace itself — that is a separate API call, not this skill.
- Do NOT touch `tools/<tool_id>/` on disk in any way.
- Do NOT batch this silently across multiple workspaces or tools — confirm each unlink.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically.
