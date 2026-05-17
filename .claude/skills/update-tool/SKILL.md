---
name: update-tool
description: Modifies an existing Pixie tool's inputs, outputs, behaviour, dependencies, or metadata, then re-validates. Use when the user asks to change, edit, tweak, or add/remove an input/output. Do NOT use to rename (rename-tool), delete (remove-tool), fix broken (debug-tool), set a secret (set-secret), migrate format (migrate-tool-format), tag (tag-tool), or restructure files (organise-tool).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Update an existing Pixie tool

You are modifying a tool that already exists under `tools/`. Every change to `tool.json`, `main.py`, or `pyproject.toml` must end with a passing validator report.

## Routing check (do this first)

- If the tool does not exist under `tools/`, stop and tell the user you are switching to `add-tool-from-description` or `add-tool-from-repo`.
- If the user wants to delete the tool, switch to `remove-tool`.
- If the tool is failing and the user is asking for a fix rather than a behaviour change, switch to `debug-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

Read these for reference on the canonical structure:

- `tools/example-compound-interest/tool.json`
- `tools/example-compound-interest/main.py`
- `tools/example-compound-interest/pyproject.toml`

## Steps

### 1. Identify the tool and the change

Ask the user only if either is ambiguous. Otherwise proceed.

### 2. Read current state

- `tools/<tool_id>/tool.json`
- `tools/<tool_id>/main.py`
- `tools/<tool_id>/pyproject.toml`

### 3. Apply the change

Use `Edit` for surgical changes. Use `Write` only when rewriting a file end-to-end.

Things to watch:

- Schema changes in `tool.json` MUST be reflected in `main.py` — both the Pydantic `RunInput` model and the response shape. The validator's `schema_matches_disk` check catches drift.
- If you add a `required: true` input with no default, existing pre-filled inputs in `pixie.db` will be missing it. That is the user's concern, not the skill's.
- Removing a secret entry from `tool.json` does NOT delete `tools/<tool_id>/.env`. The user can clear it manually if they want.
- Never change the bind address from `127.0.0.1` to anything else.
- Never inject auth, sessions, or login.

### 4. If dependencies changed, run uv sync

```bash
cd tools/<tool_id> && uv sync
```

`uv` resolves the platform-specific venv path on its own.

### 5. Validator handoff (mandatory final step)

1. From the repo root:
   ```bash
   uv run pixie validate <tool_id> --json
   ```
   Capture the full JSON stdout.

2. Parse and branch on `overall`:
   - `"pass"` — one-line success summary. Surface any `warn` checks verbatim.
   - `"warn"` — success summary plus every warning verbatim (`name`, `message`, `details`).
   - `"fail"` — DO NOT claim success. Output the entire JSON report in a fenced `json` block, then explain in plain language which checks failed and what the `message` and `details` mean. End with: "Would you like me to hand this off to the `debug-tool` skill?" Stop.

3. Never paraphrase a failed report.

4. Hard stop after two consecutive failed runs.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't make that change. <One-sentence reason citing the specific rule.>

Pixie tools always bind to 127.0.0.1, run as local Python subprocesses, and have no
authentication, no cloud sync, no Docker, no GPU requirement. The change you've asked
for crosses one of those lines.

If you want this tool reachable from another machine, that is outside Pixie's v1 scope.
Use an SSH tunnel or a reverse proxy you control instead.
```

## Do NOT

- Do NOT change the bind address from `127.0.0.1` to `0.0.0.0` or anything else.
- Do NOT add authentication, sessions, login, or multi-user concepts.
- Do NOT add Docker, container, or cloud-deployment files.
- Do NOT add telemetry or analytics to the tool.
- Do NOT hardcode API keys in `main.py` or `tool.json`; load them from `os.environ`.
- Do NOT echo, log, or display stored secret values.
- Do NOT add a marketplace, registry, or publishing concept.
- Do NOT claim success when the validator reports `overall == "fail"`.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
