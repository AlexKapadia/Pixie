---
name: archive-tool
description: Archives a Pixie tool reversibly - hides it from the sidebar and deletes .venv to free disk; source kept. Use when the user asks to archive, hide, mothball, shelve, or stop using a tool without losing it. Do NOT use to delete forever (remove-tool), restore (unarchive-tool), or prune runs (clear-old-outputs).
allowed-tools: Bash, Read, Glob
---

# Archive a Pixie tool

You are hiding a tool from the sidebar and freeing its disk footprint, **without deleting its source**. The tool's folder, `tool.json`, `main.py`, `pyproject.toml`, and any committed files all stay on disk. The `.venv/` is removed. The tool's row in the `tool_state` table is flipped to `archived = 1` so the sidebar filter hides it. The user can restore it later with `unarchive-tool`, which rebuilds the `.venv` via `uv sync` and re-validates.

This is the difference from `remove-tool`: archive is reversible without re-fetching anything; remove is permanent and destroys the source.

## Routing check (do this first)

- If the user wants to permanently delete a tool (folder and all), switch to `remove-tool`.
- If the user wants to stop a warm subprocess but keep the tool visible, this is not the right skill — direct them to the Pixie dashboard's Stop button or `pixie-status`.
- If the tool is currently warm (a subprocess is running), stop it first via the Pixie API (see step 3).

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Identify the tool

If the user did not name a specific tool, `Glob` `tools/*/tool.json` and ask which one. Confirm the tool's folder exists at `tools/<tool_id>/`.

### 2. Confirm explicitly

Ask the user, verbatim:

> "I am about to archive `<tool_id>`. The sidebar will hide it and I will delete `tools/<tool_id>/.venv/` to free disk. The source files (`tool.json`, `main.py`, `pyproject.toml`) stay on disk and you can restore the tool later with `unarchive-tool`. Proceed? (yes/no)"

Wait for an explicit "yes". Anything else, stop and report no action taken.

### 3. Archive via the Pixie API

Prefer the orchestrated endpoint — Pixie will stop any warm subprocess, flip the `archived` flag in `tool_state`, and emit the dashboard event in one step.

```bash
curl -s -X POST http://127.0.0.1:7860/api/tools/<tool_id>/archive
```

If the API returns a 409 (`tool is warm`), call:

```bash
curl -s -X POST http://127.0.0.1:7860/api/tools/<tool_id>/stop
```

Then retry the archive call. If Pixie is not running (curl connection refused), fall back to step 3b.

### 3b. Fallback: write the archived flag directly

Only if the Pixie process is not running. Use a Python one-liner against `pixie.db`:

```bash
uv run python -c "import sqlite3, pathlib; conn = sqlite3.connect(pathlib.Path('pixie.db')); conn.execute('INSERT INTO tool_state (tool_id, archived) VALUES (?, 1) ON CONFLICT(tool_id) DO UPDATE SET archived = 1', ('<tool_id>',)); conn.commit(); conn.close(); print('archived')"
```

### 4. Delete the `.venv/` folder

On POSIX (or Git Bash on Windows):

```bash
rm -rf tools/<tool_id>/.venv
```

On PowerShell:

```powershell
Remove-Item -Recurse -Force tools/<tool_id>/.venv
```

Do NOT touch any other folder. Do NOT delete `data/`, `tool.json`, `main.py`, `pyproject.toml`, `.env`, or `README.md`. The `.env` keeps the user's secrets in place so an unarchive restores them without re-prompting.

### 5. Report disk freed

Before deletion in step 4, capture the `.venv/` size and surface it in the completion message:

> "Archived `<tool_id>`. Freed roughly `<N> MB`. The sidebar has hidden the tool; the source files are intact at `tools/<tool_id>/`. Run `unarchive-tool` to restore."

### 6. Do NOT run the validator

The tool's contract has not changed — only its visibility and `.venv`. The validator is not the right tool here. Skip the validator handoff.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I cannot archive `<tool_id>` while it is warm — a subprocess is still running.
Stop it from the Pixie dashboard (or via `pixie-status`) and try again. I can
also stop it automatically if you confirm — that will cancel any in-flight run.
```

```
`<tool_id>` is the canonical example tool. I will not archive it — it is the
reference layout every other skill points at. If you really want it gone,
remove it manually after copying it elsewhere.
```

## Do NOT

- Do NOT delete `tools/<tool_id>/` itself.
- Do NOT delete `tools/<tool_id>/data/`, `tool.json`, `main.py`, `pyproject.toml`, `README.md`, or `.env`.
- Do NOT archive `tools/example-compound-interest/` — refuse and explain.
- Do NOT proceed without an explicit "yes" from the user.
- Do NOT run the Pixie validator after archiving.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT invoke other Pixie skills programmatically.
