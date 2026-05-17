---
name: clear-old-outputs
description: Runs the retention sweeper to delete OLD past RUNS and artefacts exceeding retain_runs, sparing starred and labelled. Use when the user asks to clear, clean, prune, sweep, or delete OLD runs or run history. Do NOT use to delete a tool (remove-tool), archive (archive-tool), or audit disk (audit-disk-usage).
allowed-tools: Bash, Read
---

# Prune old Pixie outputs

You are running the retention sweeper on demand. The sweeper deletes runs (and their artefacts) that exceed the per-tool retention cap (`retain_runs` in `tool.json`, default 100) AND are neither starred nor labelled. You ALWAYS show what will be deleted first, then confirm before executing.

## Routing check (do this first)

- If the user just wants to REPORT disk usage (not delete anything), switch to `audit-disk-usage`.
- If the user wants to remove an ENTIRE tool (folder, .venv, the lot), switch to `remove-tool`.
- If the user wants to archive a tool reversibly (just removes `.venv`, keeps source), switch to `archive-tool`.
- If the user wants to keep specific runs safe, suggest `star-run` or `label-run` first, then come back here.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Confirm Pixie is reachable

```bash
curl -s http://127.0.0.1:8765/api/healthz
```

If Pixie is not running, STOP — the prune endpoint is the single source of truth for retention policy. Refuse and tell the user to start Pixie (`uv run pixie`). Do NOT attempt a direct SQLite-level delete in this skill — that bypasses the per-tool `retain_runs` resolver and the post-delete artefact-file cleanup.

### 2. Parse the user's flags

| Flag | Default | Effect |
|---|---|---|
| `--older-than <duration>` | unset | Adds an age cutoff on top of per-tool retention. Accept `7d`, `30d`, `90d`, `6m`, `1y`. |
| `--tool <id>` | unset | Restrict the sweep to one tool. |
| `--dry-run` | implied step 3 | Always shown in step 3 — but skip step 5 (the actual delete) if true. |
| `--yes` | false | Skip the user confirmation in step 4. Use only when the user explicitly says "yes" / "just do it". |

### 3. Dry-run the prune (always)

```bash
curl -s -X POST "http://127.0.0.1:8765/api/maintenance/prune" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true, "tool_id": "<id-or-null>", "older_than": "<duration-or-null>"}'
```

The endpoint returns the EXACT set of runs and artefacts that would be deleted, with their reason:

```jsonc
{
  "runs": [
    {"run_id": "...", "tool_id": "...", "created_at": "...", "artefact_count": 3, "artefact_bytes": 1234567, "reason": "exceeds retain_runs=100"},
    ...
  ],
  "totals": {"runs": 12, "artefacts": 47, "bytes": 89000000},
  "preserved": {"starred": 8, "labelled": 4}
}
```

If `runs` is empty, print "Nothing to prune — every run is either within the retention cap or starred/labelled." and STOP.

### 4. Show the user, ask for confirmation

Print a markdown table of every run that would be deleted, sorted oldest first:

| Run | Tool | When | Artefacts | Size | Reason |
|---|---|---|---|---|---|

`Run` is the first 8 chars of `run_id`. `Size` is `MB`/`GB` with one decimal.

Below the table:

> "This would delete `<N>` run(s) and `<M>` artefact(s), freeing `<size>`. `<starred>` starred and `<labelled>` labelled run(s) are preserved automatically."

If `--dry-run` was passed, stop here — print "(dry run — nothing deleted)".

If `--yes` was passed, skip the prompt and proceed to step 5.

Otherwise, ask explicitly: "Proceed with delete? (yes / no)". If the user does not unambiguously say yes (with `yes`, `y`, `confirm`, "do it"), abort. Do NOT interpret silence as consent.

### 5. Execute the prune

```bash
curl -s -X POST "http://127.0.0.1:8765/api/maintenance/prune" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": false, "tool_id": "<id-or-null>", "older_than": "<duration-or-null>"}'
```

The response shape matches step 3 plus `executed: true`.

### 6. Confirm to the user

Print one line:

> "Pruned `<N>` run(s), `<M>` artefact(s), freed `<size>`. `<starred>` starred and `<labelled>` labelled run(s) preserved."

If any deletes failed (the endpoint reports per-run errors), surface each failed `run_id` verbatim with the reason.

### 7. Do NOT run the validator

This skill does not modify any tool's code.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
Pixie is not running, so I cannot prune. The prune endpoint resolves per-tool
retention rules from `tool.json` — bypassing it via direct SQL would leave
artefact files orphaned on disk. Start Pixie (`uv run pixie`) and rerun.
```

```
I need explicit confirmation before deleting. You did not say yes. Aborting —
nothing was deleted. Rerun with `--yes` if you want to skip the prompt.
```

```
`<duration>` is not a recognised age — use `7d`, `30d`, `90d`, `6m`, or `1y`.
```

## Do NOT

- Do NOT delete anything without the dry-run preview (step 3 is mandatory).
- Do NOT skip the confirmation prompt unless `--yes` was explicitly passed.
- Do NOT delete starred or labelled runs under any circumstance — the endpoint already excludes them, do not work around it.
- Do NOT touch `pixie.db` directly with SQL — always go through the prune endpoint.
- Do NOT delete tools themselves — that is `remove-tool`.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically — name them and stop.
