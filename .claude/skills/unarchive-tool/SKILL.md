---
name: unarchive-tool
description: Unarchives a previously archived Pixie tool - restores it to the sidebar, rebuilds .venv via uv sync, then validates. Use when the user asks to unarchive, restore, bring back, un-hide, or re-enable an archived tool. Do NOT use to install from scratch (add-tool-from-description, add-tool-from-repo) or from a zip (import-tool).
allowed-tools: Bash, Read, Glob
---

# Unarchive a previously archived Pixie tool

You are restoring a tool that was previously archived via `archive-tool`. Its source files (`tool.json`, `main.py`, `pyproject.toml`, `.env`) are still on disk at `tools/<tool_id>/`; only the `.venv/` was removed and the `archived` flag was set. You flip the flag back, run `uv sync` to rebuild the virtual environment, and then validate.

## Routing check (do this first)

- If the tool was permanently deleted (`tools/<tool_id>/` no longer exists), this skill cannot help. Direct the user to `add-tool-from-repo`, `import-tool`, or whichever creation skill matches what they have.
- If the user wants to install a fresh tool from a zip or repo, switch to `import-tool` or `add-tool-from-repo`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Identify the tool

If the user did not name a specific tool, query the archived list via the Pixie API:

```bash
curl -s http://127.0.0.1:7860/api/tools?archived=true
```

If Pixie is not running, fall back to scanning `pixie.db` directly:

```bash
uv run python -c "import sqlite3, pathlib; conn = sqlite3.connect(pathlib.Path('pixie.db')); rows = conn.execute('SELECT tool_id FROM tool_state WHERE archived = 1').fetchall(); print('\n'.join(r[0] for r in rows))"
```

Show the list and ask which tool to restore.

### 2. Verify the source is still on disk

```bash
ls tools/<tool_id>/tool.json
```

If the file does not exist, STOP. Tell the user the tool was deleted, not just archived, and that they need to reinstall it via `add-tool-from-repo` or `import-tool`.

### 3. Flip the archived flag back

Prefer the Pixie API:

```bash
curl -s -X POST http://127.0.0.1:7860/api/tools/<tool_id>/unarchive
```

If Pixie is not running, write the flag directly:

```bash
uv run python -c "import sqlite3, pathlib; conn = sqlite3.connect(pathlib.Path('pixie.db')); conn.execute('UPDATE tool_state SET archived = 0 WHERE tool_id = ?', ('<tool_id>',)); conn.commit(); conn.close(); print('unarchived')"
```

### 4. Rebuild the `.venv/`

```bash
cd tools/<tool_id> && uv sync
```

`uv` recreates the platform-specific venv (`tools/<tool_id>/.venv/Scripts/python.exe` on Windows, `tools/<tool_id>/.venv/bin/python` on POSIX) using the locked dependencies in `pyproject.toml` and (if present) `uv.lock`.

If `uv sync` fails with a dependency-resolution error, STOP, surface the full stderr verbatim, and offer to hand off to `debug-tool`. Do NOT continue to the validator on a failed sync.

### 5. Validator handoff (mandatory final step)

From the repo root:

```bash
uv run pixie validate <tool_id> --json
```

Parse the JSON. Branch on `overall`:

- `"pass"` — report success in one line. Tell the user the tool is back in the sidebar. Surface any `warn` checks verbatim.
- `"warn"` — report success and list every check where `status == "warn"` verbatim, with `name`, `message`, and `details`.
- `"fail"` — DO NOT claim success. Output the entire JSON report verbatim in a fenced `json` block, then explain in plain language which checks failed. The most likely cause is a dependency that no longer resolves on the current Python or platform. End with: "Would you like me to hand this off to the `debug-tool` skill?" Stop.

Hard stop after two consecutive failed runs. Surface both reports and stop iterating.

### 6. Report completion

> "Unarchived `<tool_id>`. The `.venv/` was rebuilt and the validator reports `<overall>`. The tool is back in the sidebar; refresh the dashboard if it is open."

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I cannot unarchive `<tool_id>` — its source folder `tools/<tool_id>/` is not on disk.
That means it was removed (with `remove-tool`), not archived. To get it back you
need to reinstall it: `add-tool-from-repo` if you have the URL, `import-tool` if
you have a zip, or `add-tool-from-description` to rebuild it from scratch.
```

## Do NOT

- Do NOT create a new tool here. If the source is missing, refuse and point at the right creation skill.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT add authentication or multi-user concepts.
- Do NOT modify `tool.json`, `main.py`, or `pyproject.toml`.
- Do NOT clear or rewrite the tool's `.env` — the user's secrets must survive a round-trip through archive/unarchive.
- Do NOT skip the validator after rebuilding the `.venv/`.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
