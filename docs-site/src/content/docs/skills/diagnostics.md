---
title: Diagnostics
description: Debug tools, check Pixie's health, inspect runtime state, validate against references.
sidebar:
  order: 7
---

When something's wrong, start here.

## debug-tool

<span class="skill-pill">non-destructive (may write fixes)</span>

**Trigger:** "Debug the foo tool", "Why is bar failing?", "Fix the
validation errors on baz".

**Steps:**

1. Run the validator **first** — `uv run pixie validate <id> --json`.
   The report is the primary diagnostic; read it before reading the
   code.
2. For each failing check, map to the most likely file:
   - `tool_json_parses` → `tool.json`
   - `pyproject_ok` → `pyproject.toml`
   - `venv_functional` → `pyproject.toml` + run `uv sync`
   - `schema_matches_disk` → both `tool.json` and `main.py`
   - `sample_input_run` → `main.py`
   - `output_conforms` → `main.py` (especially the response shape)
   - `clean_shutdown` → `main.py` lifespan / signal handling
3. Read the relevant lines.
4. Propose and apply a fix.
5. Re-run the validator.
6. **Two-attempt cap.** If two attempts fail, surface both reports
   verbatim and stop. No further automatic suggestions — the user is
   better placed to debug a stubborn case.

**Does not:**
- Run the tool outside the validator.
- Modify `tool.json` to "make the test pass" without understanding why
  the test failed.
- Suggest running the validator manually — the skill does this
  automatically.

---

## pixie-status

<span class="skill-pill">read-only</span>

**Trigger:** "Is Pixie running?", "What's warm?", "How many tools are
spawned?"

Returns a snapshot from `/api/launcher/state` (developer-mode only):
which tools are warm, their ports, uptime, recent activity, total
warm count vs cap. Doesn't enumerate installed tools — for that, use
`list-tools`.

---

## pixie-doctor

<span class="skill-pill">non-destructive (read-only)</span>

**Trigger:** "Pixie won't start", "Dashboard is broken", "Run a health
check".

Comprehensive installation diagnostics:

1. Python 3.12+ available?
2. `uv` available?
3. `pixie` package importable?
4. `pixie.db` exists and is readable?
5. `tools/` exists with at least the example tool?
6. `PIXIE_HOST` and `PIXIE_PORT` set correctly?
7. Pixie's HTTP API reachable at `127.0.0.1:7860/api/healthz`?
8. `git` available (required by `add-tool-from-repo`)?
9. Does `pixie validate example-compound-interest` pass?
10. Free disk space in `tools/`?
11. Write access to `tools/` and `pixie.db`?

Returns a formatted report with a final summary.

---

## list-tools

<span class="skill-pill">read-only</span>

**Trigger:** "List all tools", "Show installed tools", "Enumerate
tools".

One-line-per-tool table with id, name, category, layout, validation
status. Useful as the starting point for skills that take a tool id —
when you don't remember the exact name.

---

## validate-against-reference

<span class="skill-pill">read-only</span>

**Trigger:** "Validate accuracy of foo", "Check foo against its
fixtures", "Confirm reproducibility".

Runs **only check 12** of the validator: the reference fixture
comparison. Skips checks 1–11. Use in CI when you've already confirmed
the contract elsewhere and just want to verify the numerics.

Equivalent to `uv run pixie validate <id> --reference-only`. See
[Fixtures & reference validation](/Pixie/build/fixtures/) for the
fixture format.

---

## Diagnosis playbook

Most "tool is broken" cases resolve in this order:

1. `pixie-status` — is Pixie even running?
2. `list-tools` — is the tool present?
3. `debug-tool <id>` — what does the validator say?
4. If the validator's checks 1–5 fail → it's a setup issue (missing
   file, broken JSON, missing dep, missing `.venv/`).
5. If checks 6–8 fail → it's a startup issue (`main.py` won't import,
   uvicorn won't bind, schema endpoint missing).
6. If checks 9–11 fail → it's a logic issue (wrong output shape,
   exception during `/run`, slow shutdown).
7. If check 12 fails → it's a correctness regression (use
   `validate-against-reference` to narrow down which fixture).

If you've done all that and the tool still doesn't work:

- `view-logs <id>` to see the raw stderr.
- `pixie-doctor` to check the surrounding installation.
- Ask the user. Sometimes the answer is "this whole concept is wrong".
