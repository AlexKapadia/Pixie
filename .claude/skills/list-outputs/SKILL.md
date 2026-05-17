---
name: list-outputs
description: Lists saved output ARTEFACTS (files, images, audio, transcripts) from past Pixie tool RUNS, optionally filtered by tool. Use when the user asks to list, show, or browse saved OUTPUTS or ARTEFACTS. Do NOT use to list installed tools (list-tools), search by name (find-output), or show one tool's runs (view-runs).
allowed-tools: Bash, Read
---

# List saved Pixie outputs across tools

You are producing a single read-only report of artefacts saved across one or every Pixie tool. Artefacts are real files on disk under `artefacts/<tool_id>/<run_id>/<filename>` and are also indexed in the `artefacts` SQLite table. You query Pixie's API and print a markdown table — you do not modify or delete anything.

## Routing check (do this first)

- If the user wants to list runs (events, history, what executed and when) rather than the FILES produced, switch to `view-runs`.
- If the user wants one tool's full schema, dependencies, and secrets, switch to `inspect-tool`.
- If the user wants to search saved outputs by a name, label, or tag substring, switch to `find-output`.
- If the user wants the live runtime view (what is warm now), switch to `pixie-status`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Confirm Pixie is reachable

```bash
curl -s http://127.0.0.1:8765/api/healthz
```

If the response is empty or non-2xx, tell the user Pixie is not running and stop. Do not attempt a database-level fallback in this skill — `find-output` and `open-artefacts-folder` are the offline paths.

### 2. Decide scope

If the user named a tool, scope to that tool. Otherwise scope to every tool.

Optional flags inferred from the user's phrasing:

| Flag | Default | Effect |
|---|---|---|
| `tool_id` | unset | Restrict to one tool. |
| `limit` | `20` | Max rows returned. Cap at 200. |
| `starred_only` | `false` | If the user said "starred" / "favourites" / "pinned", set true. |
| `sort` | `date` | Or `size` if the user said "largest" / "biggest". |
| `order` | `desc` | Or `asc` if the user said "oldest" / "smallest". |

### 3. Call the artefacts API

```bash
curl -s "http://127.0.0.1:8765/api/artefacts?tool_id=<id-or-empty>&limit=<n>&starred_only=<bool>"
```

The endpoint returns a JSON list of artefact rows: `id`, `run_id`, `tool_id`, `output_key`, `rel_path`, `filename`, `mime`, `size_bytes`, `sha256`, `created_at`, `starred`, `label`, `tags`.

If the response is `[]`, print a single line — "No saved outputs found." — and stop. If a tool was scoped, suggest running the tool once to produce some.

### 4. Sort client-side

Re-sort the returned list by the chosen field and order. The API defaults to `created_at desc` so a simple list usually needs no resort.

### 5. Format the table

Use sentence-case British English headers. Truncate filenames longer than 32 chars with an ellipsis. Format sizes with `MB` up to 1024 MB then `GB`, one decimal. Format `created_at` as `YYYY-MM-DD HH:MM` (UTC, as returned). Star column shows `★` if starred else blank.

| Created | Tool | Run | File | MIME | Size | Star | Label |
|---|---|---|---|---|---|---|---|

The `Run` column shows the run_id truncated to the first 8 characters.

### 6. Print a summary line

Below the table:

> "`<N>` artefact(s) shown, total `<size>` — across `<M>` run(s) in `<K>` tool(s)."

If `starred_only=true`, append: "(filtered to starred runs)".

If the returned list was capped by `limit`, append: "Increase `limit` to see more — there may be older artefacts."

### 7. Suggest next steps

If the table is non-empty, print one line:

> "Use `find-output` to search by name or label, `copy-output-to` to copy a file to disk, or `open-artefacts-folder` to browse the folder directly."

### 8. Do NOT run the validator

This skill is read-only and does not modify any tool.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
Pixie is not running, so I cannot query the artefacts API. Either start Pixie
(`uv run pixie`) or use `open-artefacts-folder` to browse the artefacts directory
directly on disk.
```

## Do NOT

- Do NOT delete, move, rename, or modify any artefact file or row.
- Do NOT download or copy artefact contents in this skill — use `copy-output-to`.
- Do NOT include artefact SHA-256 hashes in the table — they are noise for a listing.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically — name them and stop.
