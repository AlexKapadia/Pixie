---
name: star-run
description: Stars one Pixie run - sets runs.starred = 1, pinning to favourites AND protecting its artefacts from auto-pruning. Use when the user asks to star, favourite, pin, bookmark, protect, or keep a specific run or its outputs. Do NOT use to give it a name (label-run) or export it (export-run).
allowed-tools: Bash, Read
---

# Star a Pixie run

You are marking one specific run as starred. Starring sets `runs.starred = 1`, which (a) pins the run to the favourites filter in the library UI and (b) exempts every artefact attached to the run from the background auto-prune sweeper. Unstarring is just the inverse.

## Routing check (do this first)

- If the user wants to give the run a memorable NAME (not just protect it), switch to `label-run` — labelling also protects from auto-prune AND gives the run a human-friendly handle.
- If the user wants to package the run for sharing or archival, switch to `export-run`.
- If the user wants to delete old runs (the opposite of protect), switch to `clear-old-outputs`.
- If the user wants to star a TOOL rather than a run, that's `tag-tool` — Pixie does not have a separate "star tool" concept.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Resolve the run_id

If the user gave a full `run_id`, use it. If they gave a short prefix (first 8 chars from a previous listing), resolve it via the API:

```bash
curl -s "http://127.0.0.1:8765/api/artefacts?limit=200" | \
  uv run python -c "import json, sys; rows = json.load(sys.stdin); ids = sorted({r['run_id'] for r in rows if r['run_id'].startswith(sys.argv[1])}); print('\n'.join(ids))" "<prefix>"
```

If zero matches, STOP — tell the user no run found and suggest `list-outputs` to find the id. If multiple matches, list them and ask which one.

If the user described the run by tool + recency ("the last music separator run"), use `view-runs <tool_id>` to find it first — do NOT guess.

### 2. Check the current state

```bash
curl -s "http://127.0.0.1:8765/api/runs/<run_id>"
```

If the run is already starred and the user clearly said "star" (not "toggle"), print a one-liner confirming and stop — no need to call the API again.

If the user asked to unstar, branch to the unstar path in step 3.

### 3. Call the API

Star:

```bash
curl -s -X POST "http://127.0.0.1:8765/api/runs/<run_id>/star"
```

Unstar:

```bash
curl -s -X POST "http://127.0.0.1:8765/api/runs/<run_id>/unstar"
```

Both endpoints are idempotent and return the updated run row.

### 4. Confirm to the user

Print one line:

> "Run `<run_id_short>` (`<tool_id>`, ran `<when>`) starred. Its `<N>` artefact(s) are now protected from auto-prune."

For unstar:

> "Run `<run_id_short>` (`<tool_id>`) unstarred. Its artefacts will be considered by the next sweeper run."

Include the count of artefacts attached to the run if the API response includes it; otherwise compute it via `curl /api/artefacts?run_id=...` and length the array.

### 5. Suggest next steps

If the user just starred something they'll want to find again, suggest:

> "Use `list-outputs --starred-only` to see every starred run's outputs, or `label-run <run_id> <name>` to also give this run a memorable name."

### 6. Do NOT run the validator

This skill changes only the `runs.starred` boolean — no tool code is touched.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
Pixie is not running, so I cannot star this run. Start Pixie first (`uv run pixie`).
Alternatively, runs and artefacts are safe on disk regardless — starring only affects
auto-prune and the favourites filter.
```

```
I need a run_id, not a tool name. A tool has many runs; each is a single execution.
Use `view-runs <tool_id>` to list runs for a tool, then star a specific one by id.
```

## Do NOT

- Do NOT star a TOOL — Pixie does not have that concept. Use `tag-tool` for tool-level grouping.
- Do NOT modify the run's inputs, outputs, or artefacts themselves.
- Do NOT bulk-star multiple runs in one call without explicit user confirmation listing each id.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically — name them and stop.
