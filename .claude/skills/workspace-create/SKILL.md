---
name: workspace-create
description: Creates a new Pixie workspace - a named collapsible sidebar GROUP for organising tools by project or topic. Use when the user asks to create, make, or set up a new workspace, sidebar group, or project section. Do NOT use to add a tool (workspace-add-tool) or tag a tool (tag-tool).
allowed-tools: Bash, Read, Glob
---

# Create a new Pixie workspace

You are creating a new workspace — a named, collapsible group that appears in the dashboard sidebar above the flat tools list. A workspace has a unique kebab-case `id`, a display `name`, an optional accent `colour` (one of Pixie's palette tokens), and a `sort_order` integer for stable display ordering. Workspaces are stored in the `workspaces` table in `pixie.db`. Tools belong to a workspace via the `tool_workspaces` join table, populated separately by `workspace-add-tool`.

## Routing check (do this first)

- If the user wants to add an existing tool to a workspace, switch to `workspace-add-tool`.
- If the user wants to take a tool out of a workspace, switch to `workspace-remove-tool`.
- If the user wants to tag a tool (a free-form label, not a sidebar group), switch to `tag-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Gather the inputs

You need three things:

1. The workspace `name` — human-readable, sentence case (e.g. "Quant research", "Image work").
2. The accent `colour` — optional. One of: `indigo`, `slate`, `forest`, `ember`, `none`. Default `none`.
3. The `sort_order` — optional. Integer; lower numbers sort higher. Default: max existing `sort_order` + 10.

If the user supplied the name in their first message, do not re-ask. If `colour` and `sort_order` are absent, do not ask — fill the defaults.

Derive the `id` from the name: lowercase, replace spaces and underscores with hyphens, strip any character outside `[a-z0-9-]`. Show the user the derived id and confirm before writing.

### 2. Refuse if the workspace id already exists

Query `pixie.db`:

```bash
uv run python -c "import sqlite3, pathlib; conn = sqlite3.connect(pathlib.Path('pixie.db')); row = conn.execute('SELECT id FROM workspaces WHERE id = ?', ('<workspace_id>',)).fetchone(); print('exists' if row else 'free')"
```

If the result is `exists`, STOP and surface the refusal block. The user must pick a different name or use `workspace-add-tool` against the existing workspace.

### 3. Create the workspace

Prefer the Pixie API so the dashboard updates live:

```bash
curl -s -X POST http://127.0.0.1:7860/api/workspaces \
  -H "Content-Type: application/json" \
  -d '{"id": "<workspace_id>", "name": "<name>", "colour": "<colour>", "sort_order": <sort_order>}'
```

If Pixie is not running, fall back to a direct insert:

```bash
uv run python -c "import sqlite3, pathlib; conn = sqlite3.connect(pathlib.Path('pixie.db')); conn.execute('INSERT INTO workspaces (id, name, colour, sort_order, created_at) VALUES (?, ?, ?, ?, datetime(\"now\"))', ('<workspace_id>', '<name>', '<colour>', <sort_order>)); conn.commit(); conn.close(); print('created')"
```

### 4. Report completion

> "Created workspace `<name>` (id `<workspace_id>`). It is empty — add tools with `workspace-add-tool`. Refresh the Pixie sidebar if it is open."

### 5. Do NOT run the validator

This skill does not modify any tool. The validator is not the right tool here. Skip the validator handoff.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
A workspace with id `<workspace_id>` already exists. Pick a different name, or
if you actually wanted to put tools into that existing workspace, use the
`workspace-add-tool` skill instead.
```

```
The colour you gave is not one of Pixie's palette tokens. Pick one of
`indigo`, `slate`, `forest`, `ember`, or `none`. Decorative colour outside
the palette is forbidden by the design rules.
```

## Do NOT

- Do NOT create more than one workspace per invocation.
- Do NOT add tools to the workspace here — that is `workspace-add-tool`.
- Do NOT accept colour values outside the Pixie palette (`indigo`, `slate`, `forest`, `ember`, `none`).
- Do NOT pick a name that collides with an existing workspace id — refuse and explain.
- Do NOT modify any tool's `tool.json`.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT invoke other Pixie skills programmatically.
