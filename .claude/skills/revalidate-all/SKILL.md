---
name: revalidate-all
description: Re-runs the Pixie validator across EVERY tool under tools/ and surfaces a per-tool pass/warn/fail summary. Use when the user asks to re-validate, recheck, or verify all tools, or audit after a Pixie or Python upgrade. Do NOT use for one named tool (debug-tool) or Pixie's own health (pixie-doctor).
allowed-tools: Bash, Read, Glob
---

# Re-validate every Pixie tool

You are running `uv run pixie validate <tool_id> --json` against every tool under `tools/`, collecting the results, and producing a summary the user can act on.

## Routing check (do this first)

- If the user only wants a snapshot of cached state (no re-run), switch to `list-tools`.
- If the user is asking about one specific failing tool, switch to `debug-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Discover the tools

```bash
ls tools/
```

Filter to directories that contain a `tool.json`:

```bash
uv run python -c "
import pathlib
for d in sorted(pathlib.Path('tools').iterdir()):
    if d.is_dir() and (d/'tool.json').exists():
        print(d.name)
"
```

### 2. Warn before running if there are many

If the count exceeds 10, tell the user up front: "About to validate N tools. Each spawns the tool process and waits for healthz — this typically takes a few seconds per tool, so the total may exceed a minute. Proceed? (yes/no)"

Wait for a yes. Anything else, stop.

### 3. Run the validator sequentially

For each `<tool_id>` in the list, run:

```bash
uv run pixie validate <tool_id> --json
```

Capture the JSON output. Parse:

- `overall` — `"pass"`, `"warn"`, or `"fail"`.
- The first check where `status == "fail"` (if any) — its `name` and `message`.

Do NOT run validations in parallel. Each validator spawn binds an ephemeral port and runs a healthz loop; parallel runs would contend on resources and produce flaky reports.

### 4. Produce the summary table

Render a single markdown table:

| ID | Overall | First failing check | Message |
|---|---|---|---|

- `Overall` shows `pass` / `warn` / `**fail**` (bold fails).
- For passing tools, leave the last two columns blank.
- For warning tools, surface the first `warn` check in the last two columns.
- For failing tools, surface the first `fail` check verbatim.

After the table, add a one-line summary: "N tools total — X passing, Y warning, Z failing."

### 5. Offer per-tool debug handoffs

If any tools failed, list them and ask:

> "The following tools failed validation: `<id1>`, `<id2>`, `<id3>`. For each, would you like me to hand off to `debug-tool`? Tell me which (or 'all' or 'none')."

Then stop and wait. Do NOT invoke `debug-tool` directly — that breaks the cross-skill no-call rule. The user has to pick.

### 6. Surface full reports for failures on request

If the user asks "show me the full report for `<id>`", re-run the validator on that one tool and output the full `ValidationReport` JSON verbatim in a fenced `json` block. Do not paraphrase failing checks.

### 7. No global validator handoff block

This skill IS bulk validation. Skipping the standard end-of-skill validator block is correct here — the table above is the report. The per-tool "surface failures verbatim" rule still applies: any time a single tool's report is shown in detail, it goes in a fenced `json` block exactly as the validator produced it.

## Cross-platform note

The Python one-liners above work identically on Windows, macOS, and Linux. Do not use shell loops like `for tool in tools/*; do ...` (broken in cmd.exe and parts of PowerShell). If you need to iterate, do it in a single `uv run python` block or run each command separately.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't validate every tool because <one-sentence reason>. <Suggestion>.
```

Realistic blockers: the `tools/` folder is missing, no tools are installed, or `uv` is not on PATH. Suggest checking the working directory or `uv` install.

## Do NOT

- Do NOT spawn parallel validator processes — sequential only.
- Do NOT skip surfacing failed checks. Failures must always be visible.
- Do NOT invoke `debug-tool` automatically. Always ask the user.
- Do NOT modify any tool while validating. This is read-only — the validator itself is read-only by design.
- Do NOT bind to `0.0.0.0` or assume Pixie binds anywhere other than `127.0.0.1`.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
