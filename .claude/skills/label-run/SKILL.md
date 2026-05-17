---
name: label-run
description: Sets a short human-memorable label on one Pixie run - searchable via find-output, also protects from auto-pruning. Use when the user asks to label, name, rename, annotate, or 'call this' a specific RUN. Do NOT use to rename a tool (rename-tool), tag a tool (tag-tool), or star a run (star-run).
allowed-tools: Bash, Read
---

# Label a Pixie run

You are setting a short human-memorable string on a run. Labelling sets `runs.label` and — like starring — exempts the run and its artefacts from the auto-prune sweeper. The label is searchable via `find-output` and shown in `list-outputs` and the library UI.

## Routing check (do this first)

- If the user just wants to PROTECT a run from auto-prune without naming it, switch to `star-run`.
- If the user wants to add a TAG to a tool (sidebar grouping by topic), switch to `tag-tool`.
- If the user wants to rename a TOOL (its id), switch to `rename-tool`.
- If the user wants to delete a run's outputs, switch to `clear-old-outputs`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Resolve the run_id

Same logic as `star-run`. Accept a full `run_id` or a short prefix. If a prefix matches zero runs, STOP and suggest `list-outputs`. If it matches multiple, list and ask.

If the user described the run by tool + recency, use `view-runs <tool_id>` first — do NOT guess.

### 2. Validate the label string

Apply these rules:

| Rule | Behaviour |
|---|---|
| Length 1–64 chars | Refuse outside this range. |
| Allowed chars | Letters, digits, spaces, `-`, `_`, `.`, `(`, `)`. No newlines, no slashes, no quotes. |
| Trimmed | Leading/trailing whitespace stripped. |
| Not reserved | Refuse the strings `null`, `none`, `""`, single dot. |

If invalid, refuse with the specific reason and ask for a different label.

### 3. Check for an existing label

```bash
curl -s "http://127.0.0.1:8765/api/runs/<run_id>"
```

If the response shows a non-null `label` AND the user did NOT pass `--force`, STOP. Print:

> "Run `<run_id_short>` already has the label `<existing>`. Pass `--force` to overwrite, or use `--clear` to remove it."

If the user passed `--clear`, set the label to null in step 4 instead of the new value.

### 4. Call the API

Set or change:

```bash
curl -s -X PATCH "http://127.0.0.1:8765/api/runs/<run_id>" \
  -H "Content-Type: application/json" \
  -d '{"label": "<new label>"}'
```

Clear:

```bash
curl -s -X PATCH "http://127.0.0.1:8765/api/runs/<run_id>" \
  -H "Content-Type: application/json" \
  -d '{"label": null}'
```

### 5. Confirm to the user

Set:

> "Run `<run_id_short>` (`<tool_id>`, ran `<when>`) labelled `<label>`. Its `<N>` artefact(s) are now protected from auto-prune."

Overwrite:

> "Run `<run_id_short>` relabelled from `<old>` to `<new>`."

Clear:

> "Run `<run_id_short>` label cleared. Auto-prune protection from labelling is removed — if the run is also starred, it remains protected."

### 6. Suggest next steps

> "Use `find-output <label>` to find this run's artefacts by name, or `export-run <run_id>` to package the whole run as a zip."

### 7. Do NOT run the validator

This skill changes only the `runs.label` text — no tool code is touched.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
The label `<input>` is invalid: <specific reason>. Labels must be 1–64 chars and use
only letters, digits, spaces, and `-_.()`. Try a shorter, simpler name.
```

```
Run `<run_id_short>` already has the label `<existing>`. Pass `--force` to overwrite,
or `--clear` to remove the existing label first.
```

```
Pixie is not running, so I cannot set the label. Start Pixie first (`uv run pixie`).
```

## Do NOT

- Do NOT overwrite an existing label without `--force`.
- Do NOT set labels longer than 64 chars or containing slashes/quotes/newlines.
- Do NOT modify the run's inputs, outputs, or artefacts themselves.
- Do NOT also star the run "for safety" — labelling already protects from prune.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically — name them and stop.
