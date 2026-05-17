---
name: list-tools
description: Enumerates every installed Pixie tool under tools/ as a one-line-per-tool table with id, name, and validator status. Use when the user asks to list, show all, or enumerate installed tools. Do NOT use to inspect ONE (inspect-tool), show what's running (pixie-status), or list saved outputs (list-outputs).
allowed-tools: Bash, Read, Glob
---

# List every Pixie tool with status

You are producing a single markdown table that shows every tool installed under `tools/`, plus its current status and validation summary. Prefer the live Pixie API; fall back to a filesystem scan only when Pixie is not running.

## Routing check (do this first)

- If the user wants to re-run the validator on every tool (not just summarise the cached state), switch to `revalidate-all`.
- If the user is asking about a single broken tool, switch to `debug-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Determine the API port

The default port is `7860`. Check whether the user overrode it via the `PIXIE_PORT` env var:

PowerShell: `$env:PIXIE_PORT`
Bash: `echo "${PIXIE_PORT:-7860}"`

Use whichever value is set.

### 2. Try the live API first

```bash
uv run python -c "
import httpx, os, json
port = os.environ.get('PIXIE_PORT', '7860')
try:
    r = httpx.get(f'http://127.0.0.1:{port}/api/tools', timeout=2.0)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))
except Exception as e:
    print('PIXIE_UNREACHABLE: ' + str(e))
"
```

If the output begins with `PIXIE_UNREACHABLE:`, jump to step 4 (filesystem fallback). Otherwise parse the JSON and continue with step 3.

### 3. Render the live API response as a table

The API returns one entry per discovered tool with at least `id`, `name`, `category`, runtime status, and a cached validation summary. Render a markdown table with these columns:

| ID | Name | Category | Status | Validation |
|---|---|---|---|---|

- **Status** is the runtime state: `running`, `warming`, `idle`, `dormant`, `errored`. Render `errored` in bold.
- **Validation** is `pass` / `warn` / `fail` from the cached report. Render `fail` in bold; mention it explicitly in the summary line.

After the table, add a one-line summary: e.g. "12 tools total — 11 passing, 1 failing (`<tool_id>`)."

If any tool's validation is `fail`, end with: "Run `debug-tool` on a failing tool, or `revalidate-all` to re-check everything."

### 4. Filesystem fallback (only if Pixie is not running)

Tell the user up front: "Pixie is not running, so I'm scanning `tools/` directly. This is slower because I have to run the validator per tool."

List the tools:

```bash
ls tools/
```

For each `<tool_id>`, read its `tool.json` to get `name` and `category`:

```bash
uv run python -c "
import json, pathlib, sys
for d in sorted(pathlib.Path('tools').iterdir()):
    if not d.is_dir() or not (d/'tool.json').exists():
        continue
    j = json.loads((d/'tool.json').read_text(encoding='utf-8'))
    print(j.get('id', d.name), '|', j.get('name', ''), '|', j.get('category', ''))
"
```

Then run the validator on each, capturing only the `overall` field — do not dump full JSON for every tool:

```bash
uv run pixie validate <tool_id> --json
```

Parse `overall` from each report. Warn the user that the filesystem fallback may take a while if there are many tools.

Render the same five-column table. Status column reads `unknown` (the launcher's not running, so there is no live runtime state). Validation column reads `pass` / `warn` / `fail`.

### 5. Output format rules

- Always a markdown table, never bullet points.
- Always include the summary line after the table.
- Always highlight `fail` rows in bold (`**fail**`).
- Never run the validator more than once per tool per invocation.
- Never spawn validation in parallel — sequential keeps the output deterministic and avoids port contention.

### 6. Do not run the global validator handoff

This skill summarises validation state; it does NOT produce a single pass/fail verdict for any one tool. The per-tool report blocks live in `debug-tool` and the creating/modifying skills.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't list tools because <one-sentence reason>. <Suggestion>.
```

Realistic blockers: the `tools/` folder is missing, the user is not in a Pixie repo root, or both the live API and the filesystem fallback failed. Suggest `cd`-ing to the Pixie repo root and re-running.

## Do NOT

- Do NOT spawn parallel validator processes — sequential only.
- Do NOT print full `ValidationReport` JSON for every tool. Summary only.
- Do NOT modify any tool while listing. This is read-only.
- Do NOT bind to `0.0.0.0` or assume Pixie binds anywhere other than `127.0.0.1`.
- Do NOT call the API on any host other than `127.0.0.1`.
- Do NOT invoke other Pixie skills programmatically.
