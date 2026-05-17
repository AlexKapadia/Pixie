---
title: Edit & maintain tools
description: Modifying, renaming, forking, archiving, removing, linting, and revalidating tools.
sidebar:
  order: 3
---

Once a tool exists, this group of skills handles every kind of change.

## update-tool

<span class="skill-pill">non-destructive</span>

**Trigger:** "Change the input X to Y", "Add an output for Z", "Make the
slider go up to 100", "Switch to multipart upload".

Surgical edits to `tool.json`, `main.py`, and `pyproject.toml`. If
dependencies change, runs `uv sync`. Then revalidates and surfaces the
report.

**Routes elsewhere if:**
- The change is just a rename ? `rename-tool`.
- The tool is broken, not being changed ? `debug-tool`.
- Just updating tags ? `tag-tool`.

---

## rename-tool

<span class="skill-pill">destructive</span>

**Trigger:** "Rename foo to bar", "Change the id from x to y".

**Side effects (listed before confirmation):**
1. Stop the tool if running (best-effort via `/api/tools/<id>/stop`).
2. Rename the folder via `pathlib.Path.rename` (on Windows, open `.venv`
   file handles may raise PermissionError).
3. Update `tool.json` `id` field.
4. Rewrite three tables in `pixie.db`: `runs`, `tool_state`,
   `validation_reports`.

The new id must be kebab-case and must not already exist. Validates
after rename.

---

## fork-tool

<span class="skill-pill">non-destructive</span>

**Trigger:** "Duplicate this tool", "Make a copy of foo called bar",
"Fork the lorenz tool".

Copies the entire tool folder (including `.venv/` via `uv sync` in the
copy) so the duplicate can be customised independently. Useful for
"like this tool but with a different model" scenarios.

---

## archive-tool / unarchive-tool

<span class="skill-pill">non-destructive (reversible)</span>

**Trigger:** "Archive foo", "Hide bar", "Mothball baz" / "Unarchive
foo", "Bring back bar".

**Archive:**
1. Set `tool_state.archived = 1` (hides from sidebar by default).
2. Delete `.venv/` to free disk.
3. Source code remains; runs and reports stay in `pixie.db`.

**Unarchive:**
1. Set `archived = 0`.
2. `uv sync` to rebuild `.venv/`.
3. Re-validate.

This is the answer when you don't want the tool around but aren't ready
to delete it (vs. `remove-tool`, which is permanent).

---

## remove-tool

<span class="skill-pill">destructive (permanent)</span>

**Trigger:** "Delete the foo tool", "Uninstall bar", "Remove the
example-compound-interest tool".

**Refuses to delete `tools/example-compound-interest/`** — the canonical
reference is protected.

**Side effects (listed before confirmation):**
1. Stop the tool (best-effort).
2. Recursively delete the folder including `.venv/` and `data/`.
3. (Run history and reports for the tool stay in `pixie.db` for
   historical accuracy.)

Requires explicit "yes" confirmation. No undo.

---

## lint-tool

<span class="skill-pill">non-destructive (read-only)</span>

**Trigger:** "Lint foo", "Check the style of bar", "Scan baz for
hardcoded secrets".

Static checks only — never runs the tool or the validator. Catches:

- Missing `tool.json` metadata fields (description, version, category, icon).
- Labels not in sentence case.
- Missing input descriptions.
- Heavy imports at module level (slows cold-start).
- `print()` calls in `main.py` (should use `logging`).
- `requests` instead of `httpx`.
- Hardcoded API keys / tokens / passwords (reports line numbers only,
  never values; recognises common prefixes like `sk-`, `ghp-`, `xoxb-`).
- `.env` not in `.gitignore`.

**Allowed tools:** `Bash`, `Read`, `Glob`, `Grep`. Cannot modify files.

---

## inspect-tool

<span class="skill-pill">non-destructive (read-only)</span>

**Trigger:** "Show me the foo tool", "Describe bar", "What does baz do?"

Reads `tool.json`, `main.py`, `pyproject.toml`, `README.md` and the
latest validation report. Returns a one-page summary: id, name, layout,
inputs (count + types), outputs (count + types), dependencies, secrets,
status. Doesn't list every run — use `view-runs` for that.

---

## organise-tool

<span class="skill-pill">non-destructive</span>

**Trigger:** "Tidy the foo tool", "Restructure bar's files", "Organise
baz".

Restructures the tool's internal Python files into the `src/<id>/`
layout, adds `tests/`, `notebooks/`, `CHANGELOG.md` skeletons, then
re-validates. For tools that have outgrown the initial flat layout.

---

## migrate-tool-format

<span class="skill-pill">non-destructive</span>

**Trigger:** "Migrate foo to the latest schema", mentions of "old
format" / "schema version" / "deprecated field".

Upgrades a tool whose `tool.json` uses an older `schema_version` to the
current one, preserving behaviour and re-validating. Useful after a
Pixie release that bumps the schema.

---

## revalidate-all

<span class="skill-pill">non-destructive (read-only writes only reports)</span>

**Trigger:** "Re-validate every tool", "Re-check all tools", "Audit
after upgrade".

Walks `tools/` and runs the validator against every tool. Reports
pass/warn/fail counts. Use after a Python or Pixie upgrade, or when
you've just installed a batch of tools.

The skill emits a small per-tool status line so you can spot regressions:

```text
? pass    compound-interest
? pass    lorenz-ode-solver
? warn    whisper-transcription   (slow shutdown — 5.7s)
? fail    rag-with-citations      (sample run failed: APIConnectionError)
```

When done, suggests `debug-tool <id>` for any failures.
