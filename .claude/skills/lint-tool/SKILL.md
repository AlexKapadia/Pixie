---
name: lint-tool
description: Statically checks one Pixie tool against style and convention rules - metadata, labels, imports, hardcoded-secret smells, log hygiene. Use when the user asks to lint, style-check, or review best practices on one tool. Do NOT use for a broken tool (debug-tool), disk usage (audit-disk-usage), or layout cleanup (organise-tool).
allowed-tools: Bash, Read, Glob, Grep
---

# Lint a Pixie tool (static-only)

You are running a static lint over one tool's source files. This skill never spawns the tool, never runs the validator, never installs anything. It produces a markdown report with one section per check, plus a recommended-fixes list.

## Routing check (do this first)

- If the user wants to actually run the tool end-to-end to confirm it works, switch to `debug-tool` or `revalidate-all` (which both invoke the validator — and the validator spawns the tool).
- If the user wants a read-only full inspection (metadata, code, validation, runs), switch to `inspect-tool`.
- If the user wants to fix the issues, switch to `update-tool` after seeing the lint report.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Identify the tool

If not named, ask. Verify `tools/<tool_id>/tool.json` exists.

### 2. Lint `tool.json` metadata

`Read` `tools/<tool_id>/tool.json`. Check each:

- `description` present and non-empty. WARN if missing.
- `version` present. WARN if missing.
- `category` present. WARN if missing (Pixie groups the sidebar by category).
- `icon` present. WARN if missing (the sidebar falls back to a generic glyph).
- `warm_keep_seconds`, `max_memory_mb`, `max_runtime_seconds` present. WARN if missing (Pixie applies defaults but explicit is better).
- For each input: `label` present and non-empty. FAIL if missing.
- For each output: `label` present. FAIL if missing.

### 3. Label-case lint

For every `label` field in inputs and outputs:

- Should be sentence case (first word capitalised, rest lowercase unless proper nouns).
- WARN on Title Case (`Annual Interest Rate` should be `Annual interest rate`).
- WARN on ALL CAPS.

Per repo style (`.build/RULES.md` §5), British English and sentence case are required UI conventions.

### 4. Description present on every input

For each input, check `description` is present and non-empty. WARN if missing — Pixie renders the description as helper text below the field, and missing descriptions feel sparse.

### 5. Lint `main.py` imports

`Read` `tools/<tool_id>/main.py`. Check:

- Heavy imports inside function bodies, NOT at module top. Use `Grep` to find inside-function imports:
  ```
  grep -nE "^\s{4,}(import|from) " tools/<tool_id>/main.py
  ```
  WARN if heavy modules (`torch`, `tensorflow`, `transformers`, `pandas`, `numpy`, `scipy`, `sklearn`, `cv2`, `PIL`) are imported at module top. They should be imported inside the function that uses them so `/healthz` and `/schema` respond quickly.
- `print(` statements (Pixie tools should use stderr only — WARN per file).
- `requests` import — WARN, Pixie tools should use `httpx`.

### 6. Lint `pyproject.toml`

`Read` `tools/<tool_id>/pyproject.toml`. Check:

- `[project]` has `name`, `version`, `description`, `requires-python`. WARN on each missing.
- `requires-python` includes `>=3.12`. WARN otherwise.
- `[project] authors` present. WARN if missing.
- `dependencies` includes `fastapi`, `uvicorn`, `python-dotenv`. FAIL on any missing.

### 7. Check for README.md

```bash
ls tools/<tool_id>/README.md 2>&1
```

WARN if missing. A short README helps the user remember what the tool does six months from now.

### 8. Hardcoded-secret scan

Use `Grep` to look for suspicious patterns in `main.py`:

```
grep -nE "(api_key|token|secret|password|bearer)\s*=\s*[\"'][^\"']{8,}[\"']" tools/<tool_id>/main.py
```

Also scan for common key prefixes:

```
grep -nE "(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|xoxb-)" tools/<tool_id>/main.py
```

Apply the same scan to `tool.json` and `pyproject.toml`. Any match is a FAIL — surface the line number and tell the user to move the value into `.env` via `set-secret` and read it via `os.environ.get(...)`.

### 9. Check `.gitignore` coverage at tool level

If `tools/<tool_id>/.gitignore` exists, check it contains `.venv/`, `.env`, `data/`. WARN on missing entries. If the file doesn't exist, WARN — the repo-level `.gitignore` covers most cases, but a tool-level file is a good belt-and-braces.

### 10. Render the lint report

Combine all sections under `## Lint report — <tool_id>`. Group findings by severity:

```
### Errors (must fix)
- <file:line> <message>

### Warnings (recommended)
- <file:line> <message>
```

Followed by a `## Recommended fixes` list — one bullet per error and warning, ordered by severity. Plain instructions, not commands (since most of these need the user's judgement).

If the lint is clean:

> "Lint clean for `<tool_id>` — N checks ran, no findings."

### 11. Do not run the validator

This skill is static-only. After the lint report, suggest the user follow up with `revalidate-all` or `debug-tool` if they want to confirm runtime behaviour, but do not invoke them.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Do NOT

- Do NOT spawn the tool subprocess.
- Do NOT run the validator.
- Do NOT modify any file. This is read-only.
- Do NOT print or surface any value matched by the hardcoded-secret scan — surface only the line number and a generic "secret-like value" message.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
