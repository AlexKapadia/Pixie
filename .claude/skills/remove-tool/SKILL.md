---
name: remove-tool
description: Permanently deletes an ENTIRE Pixie tool - folder, .venv, data/, .env, warm subprocess. Use when the user asks to remove, delete, uninstall, or get rid of a tool forever. Do NOT use to hide reversibly (archive-tool), delete old runs (clear-old-outputs), unassign from a workspace (workspace-remove-tool), or clear a secret (set-secret).
allowed-tools: Bash, Read, Glob
---

# Remove a Pixie tool

You are permanently deleting a Pixie tool. This is destructive — confirm with the user before acting.

## Routing check (do this first)

- If the user wants to change a tool rather than delete it, switch to `update-tool`.
- If the path they gave is outside `tools/`, refuse — this skill only deletes folders directly under `tools/`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Identify the tool

If the user did not name a specific tool, list the candidates with `Glob` on `tools/*/tool.json` and ask which one.

### 2. Confirm explicitly

Ask the user, verbatim:

> "I am about to delete `tools/<tool_id>/` permanently, including its `.venv` and `data/` folders. This cannot be undone unless you have the tool committed to git. Proceed? (yes/no)"

Wait for an explicit "yes" (or equivalent affirmative). Anything else, stop and report no action taken.

### 3. Stop the running process (best effort)

Pixie may be running and the tool may have a warm subprocess. Try to stop it gracefully:

```bash
curl -s -X POST http://127.0.0.1:7860/api/tools/<tool_id>/stop
```

Handle non-zero exit codes silently — Pixie may not be running, or the tool may not be warm. That is fine. Do not fail the skill on a curl error.

### 4. Delete the folder

On POSIX (or Git Bash on Windows):

```bash
rm -rf tools/<tool_id>
```

On PowerShell:

```powershell
Remove-Item -Recurse -Force tools/<tool_id>
```

This removes the source files, the `.venv/` (including `Scripts/python.exe` on Windows or `bin/python` on POSIX), and any `data/` folder.

### 5. Confirm completion

Tell the user: "Removed `tools/<tool_id>`. Refresh the Pixie dashboard — the tool will be gone from the sidebar."

### 6. Do NOT run the validator

The tool no longer exists; there is nothing to validate. Skip the validator handoff that other skills use.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I won't delete that. The path you gave is outside `tools/` — this skill only deletes
folders directly under `tools/`. If you want to remove something else, do it manually.
```

```
I won't proceed without an explicit "yes". Deletion is permanent (unless the tool is in
git), so I need a clear confirmation before I touch anything.
```

## Do NOT

- Do NOT delete anything outside `tools/<tool_id>/`.
- Do NOT delete `tools/example-compound-interest/` — it is the canonical reference; refuse and explain.
- Do NOT proceed without an explicit "yes" from the user.
- Do NOT fail the skill if the stop endpoint returns non-zero — Pixie may not be running.
- Do NOT run the Pixie validator after deletion.
- Do NOT delete `pixie.db`, `.env` at the repo root, or anything outside the chosen tool folder.
- Do NOT invoke other Pixie skills programmatically.
