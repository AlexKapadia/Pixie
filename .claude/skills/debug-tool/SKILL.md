---
name: debug-tool
description: Diagnoses and fixes ONE Pixie tool that fails validation, crashes, hangs, or returns wrong output - validator-first. Use when the user says a named tool is broken, failing, or crashing. Do NOT use if Pixie itself is broken (pixie-doctor), for style (lint-tool), or just logs (view-logs).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Debug a Pixie tool

You are diagnosing a failing Pixie tool. The Pixie validator is your primary diagnostic instrument — run it before reading any code.

## Routing check (do this first)

- If the tool does not exist under `tools/`, stop and suggest `add-tool-from-description` or `add-tool-from-repo`.
- If the user wants to delete the tool, switch to `remove-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Identify the tool

If the user did not name a specific tool, list the candidates with `Glob` on `tools/*/tool.json` and ask which one.

### 2. Run the validator FIRST

From the repo root:

```bash
uv run pixie validate <tool_id> --json
```

Capture the full JSON stdout. The report is the primary input to your diagnosis — most failures are precisely located by which check failed, what the `message` says, and what `details` contains.

### 3. Read the relevant files

Based on which check failed, `Read`:

- `folder_structure` / `tool_json_parses` — `tools/<tool_id>/tool.json`
- `schema_coherence` — `tools/<tool_id>/tool.json` (inputs/outputs section)
- `pyproject_parses` — `tools/<tool_id>/pyproject.toml`
- `venv_exists` — confirm `tools/<tool_id>/.venv/` exists. If missing, run `cd tools/<tool_id> && uv sync`. On Windows the interpreter lives at `tools/<tool_id>/.venv/Scripts/python.exe`; on POSIX at `tools/<tool_id>/.venv/bin/python`.
- `tool_spawns` / `schema_matches_disk` / `sample_run_succeeds` / `output_conforms` — `tools/<tool_id>/main.py` plus `tools/<tool_id>/tool.json`
- `streaming_check` — the `/stream` endpoint in `main.py`
- `clean_shutdown` — signal handling in `main.py`

### 4. Diagnose

Common failure classes:

- **Missing dependency** — `pyproject.toml` does not declare what `main.py` imports. Add the dep, then `uv sync`.
- **Schema mismatch** — `/schema` returns something different from `tool.json` on disk. Usually means `main.py` hardcodes a schema. Make it read `tool.json` from the file.
- **Port conflict** — rare. The validator assigns the port; if you see this, the tool is binding to a fixed port. Switch to reading `--port` from argv.
- **Bind address wrong** — tool is binding to `0.0.0.0` or a public interface. Fix to `127.0.0.1`. Never relax this.
- **Syntax error** — visible in the spawn log. Fix the file.
- **Runtime exception in `/run`** — visible in `details`. Fix the logic.
- **Output type mismatch** — declared `chart_line` but returned `{"value": 5}`. Match the type's required shape.
- **Missing secret** — `/run` raises because an env var is unset. Confirm the secret is declared in `tool.json` and that the user has set it via the per-tool settings UI.

### 5. Propose and apply the fix

Explain in 1-3 sentences what you are changing and why, THEN apply with `Edit` (preferred) or `Write`. Do not silently rewrite files.

### 6. Re-run the validator

```bash
uv run pixie validate <tool_id> --json
```

Branch on `overall`:

- `"pass"` — one-line success. Surface any `warn` checks verbatim.
- `"warn"` — success summary plus every warning verbatim.
- `"fail"` — output the entire JSON report in a fenced `json` block, explain in plain language what is still wrong.

### 7. Hard stop after two attempts

If two consecutive validator runs after two distinct fix attempts still fail, stop. Surface both reports verbatim. Tell the user what was tried and what is still broken. Do not keep iterating silently.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't apply that fix because it would <break a Pixie rule — e.g. bind the tool to a
non-loopback interface, add authentication, install a system package>.

Pixie tools are constrained to: local 127.0.0.1 only, PyPI dependencies only, no GPU
required, no Docker, no database server, no auth.

If you want to keep the original behaviour, this tool may not be a good fit for Pixie.
Otherwise, I can apply a smaller fix that stays within the envelope.
```

## Do NOT

- Do NOT claim success when the validator reports `overall == "fail"`.
- Do NOT paraphrase a failed report; surface it verbatim.
- Do NOT change the bind address from `127.0.0.1` to anything else.
- Do NOT add authentication, sessions, or multi-user concepts to fix a tool.
- Do NOT install system packages or Docker as a "fix".
- Do NOT loop more than twice; surface what failed and stop.
- Do NOT silently rewrite files without explaining the change first.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
