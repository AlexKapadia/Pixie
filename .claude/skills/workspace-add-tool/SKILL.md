---
name: workspace-add-tool
description: Adds an existing Pixie tool to an existing workspace via the tool_workspaces join - sidebar grouping only. Use when the user asks to add, assign, move, or group a NAMED tool INTO a workspace, project, or section. Do NOT use to create the workspace (workspace-create), tag (tag-tool), or duplicate (fork-tool).
allowed-tools: Bash, Read, Glob
---

# Add a Pixie tool to a workspace

You are inserting a row into the `tool_workspaces` join table linking one `tool_id` to one `workspace_id`. A tool can belong to multiple workspaces — adding to a second one does not remove it from the first. This skill does not modify the tool's `tool.json`, its `.venv`, or any runtime state.

## Routing check (do this first)

- If the user wants to create a new workspace, switch to `workspace-create`.
- If the user wants to take a tool out of a workspace, switch to `workspace-remove-tool`.
- If the user wants to add a free-form label (not a sidebar group), switch to `tag-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Gather the inputs

You need two ids:

1. The `tool_id` — the existing Pixie tool to add.
2. The `workspace_id` — the existing workspace to add it to.

If the user said something like "add the geocoder to quant research", derive both:

- `tool_id` = "geocoder" if `tools/geocoder/tool.json` exists.
- `workspace_id` = "quant-research" by lower-casing and hyphenating "quant research".

Verify each derivation against disk and database before writing.

### 2. Verify the tool exists

```bash
ls tools/<tool_id>/tool.json
```

If the file does not exist, STOP and tell the user the tool is not installed. Suggest `list-tools` so they can see what is available.

### 3. Verify the workspace exists

```bash
uv run python -c "import sqlite3, pathlib; conn = sqlite3.connect(pathlib.Path('pixie.db')); row = conn.execute('SELECT id, name FROM workspaces WHERE id = ?', ('<workspace_id>',)).fetchone(); print(row[1] if row else 'missing')"
```

If the result is `missing`, STOP and tell the user the workspace does not exist. Suggest `workspace-create` to make it first.

### 4. Check whether the link already exists

```bash
uv run python -c "import sqlite3, pathlib; conn = sqlite3.connect(pathlib.Path('pixie.db')); row = conn.execute('SELECT 1 FROM tool_workspaces WHERE tool_id = ? AND workspace_id = ?', ('<tool_id>', '<workspace_id>')).fetchone(); print('exists' if row else 'free')"
```

If `exists`, tell the user the tool is already in that workspace, then stop. Do not double-insert.

### 5. Insert the link

Prefer the Pixie API:

```bash
curl -s -X POST http://127.0.0.1:7860/api/workspaces/<workspace_id>/tools/<tool_id>
```

If Pixie is not running, fall back to a direct insert:

```bash
uv run python -c "import sqlite3, pathlib; conn = sqlite3.connect(pathlib.Path('pixie.db')); conn.execute('INSERT INTO tool_workspaces (tool_id, workspace_id, added_at) VALUES (?, ?, datetime(\"now\"))', ('<tool_id>', '<workspace_id>')); conn.commit(); conn.close(); print('linked')"
```

### 6. Report completion

> "Added `<tool_id>` to workspace `<workspace_name>`. The tool now appears under that workspace in the sidebar. It can still belong to other workspaces."

### 7. Do NOT run the validator

This skill does not modify the tool itself. The validator is not the right tool here. Skip the validator handoff.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I cannot add `<tool_id>` to `<workspace_id>` — the tool is not installed
(no `tools/<tool_id>/tool.json` found). Run `list-tools` to see what is
available, or install it first with `add-tool-from-repo` / `import-tool`.
```

```
I cannot add `<tool_id>` to `<workspace_id>` — the workspace does not exist.
Create it first with `workspace-create`, then run this skill again.
```

## Do NOT

- Do NOT create the workspace here — that is `workspace-create`.
- Do NOT create the tool here — that is `add-tool-from-repo` / `add-tool-from-description` / `import-tool` / `wrap-local-script` / etc.
- Do NOT remove the tool from any other workspace it already belongs to.
- Do NOT modify `tools/<tool_id>/tool.json`.
- Do NOT batch this skill silently across multiple tools or workspaces — confirm each pairing.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically.
