---
name: migrate-tool-format
description: Upgrades a Pixie tool whose tool.json uses an older schema_version to the current schema, preserving behaviour and re-validating. Use when the user mentions old format, schema version, deprecation, or asks to migrate or upgrade a tool's format. Do NOT use to fix a broken tool (debug-tool) or change inputs (update-tool).
allowed-tools: Bash, Read, Write, Edit, Glob
---

# Migrate a Pixie tool's `tool.json` format

You are checking and (if needed) upgrading a tool's `tool.json` to the current Pixie schema version. As of Pixie v1, the schema is v1 — this skill mostly confirms tools are at v1 and warns about deprecated patterns. When future schema versions ship, this is the skill that grows migrations.

## Routing check (do this first)

- If the user wants to add a new input or change behaviour, switch to `update-tool` — migration is format-only, not feature work.
- If the user wants to audit metadata completeness (description, icon, category), switch to `lint-tool`.
- If the user wants validation status (does it run?), switch to `revalidate-all`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Identify the tool

If the user didn't name one, ask whether they want to migrate a specific tool or all tools.

For a single tool: verify `tools/<tool_id>/tool.json` exists.
For all tools:

```bash
uv run python -c "
import pathlib
for d in sorted(pathlib.Path('tools').iterdir()):
    if d.is_dir() and (d/'tool.json').exists(): print(d.name)
"
```

Apply the steps below to each in sequence.

### 2. Read the current `tool.json`

`Read` `tools/<tool_id>/tool.json`. Parse it as JSON.

### 3. Detect the format version

Check the top-level `version` field (NOT the tool's own `version`, which is the tool's release version — they may overlap, prefer an explicit `schema_version` field if present in future).

- If `schema_version` is present and == current (v1): print "Tool `<tool_id>` is at the current schema version (v1). No migration needed." Skip to step 6.
- If `schema_version` is missing: treat as v1 (the v1 schema does not require the field). Continue to step 4 for deprecation warnings only.
- If `schema_version` is present and > current: REFUSE. The user is on an older Pixie than the tool was authored for; they need to upgrade Pixie.
- If `schema_version` is present and < current: run the migration ladder (see step 5).

### 4. Scan for deprecated patterns (warn, do not break)

Check the parsed JSON for any of:

- Top-level `inputs` or `outputs` entries with a `type` not in the current type list (see `pixie/discovery.py`). Warn: "Input `<key>` has unknown type `<type>` — likely renamed in a later format."
- Inputs with both `default` and `required: true` but no `default` value set. Warn: "Input `<key>` is required with no default — Pixie will reject submissions missing this key."
- Inputs with `show_if` pointing at a key that doesn't exist. Warn: "Input `<key>` has `show_if` referencing `<missing>` which is not declared."
- Outputs with `format: currency` but `type` not `number`. Warn: "Output `<key>` has currency format on a non-number type."
- Secrets array declared but no `key` in `main.py` reads `os.environ.get(<key>)`. Warn (requires reading `main.py`): "Secret `<key>` is declared but `main.py` never reads it from the environment."
- `layout` not in `{form, chat, split}`. Warn: "Layout `<value>` is not recognised."

Compile warnings into a single block; do not modify the file.

### 5. Apply the migration ladder (no-op in v1)

Pixie v1 is the current schema. There are no past versions to migrate from. This section is a placeholder for future migrations — when v2 ships, this skill grows a sequence of `migrate_v1_to_v2(doc) -> doc` functions and runs them in order.

For v1: skip this step.

When future versions exist, each migration function should:

- Be pure: take a parsed dict, return a new parsed dict.
- Be tested separately under `tests/migrations/`.
- Never delete user content silently — at most rename keys and add defaults.

### 6. Write changes (only if migrations ran)

If step 5 produced changes, `Write` the new `tool.json`. In v1: this step is a no-op.

### 7. Validator handoff (mandatory final step)

Always run the validator, even if no changes were made — confirms the tool still passes after the audit:

1. From the repo root:
   ```bash
   uv run pixie validate <tool_id> --json
   ```

2. Parse the JSON. Branch on `overall`:
   - `"pass"` — report success in one line. Surface any `warn` checks AND any deprecation warnings from step 4 in a single combined list.
   - `"warn"` — report success and list every `warn` check verbatim, plus the step-4 warnings.
   - `"fail"` — DO NOT claim success. Output the entire JSON verbatim. End with: "Would you like me to hand this off to the `debug-tool` skill?" Stop.

3. Never paraphrase a failed report.

4. Hard stop after two consecutive failed runs.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I won't migrate this tool because its `schema_version` is `<version>`, which
is newer than the current Pixie supports (v1). This tool was authored for a
later Pixie release.

Upgrade Pixie itself first (`git pull` in the Pixie repo, then `uv sync` at
the root), then re-run this skill.
```

## Do NOT

- Do NOT rewrite `main.py` or `pyproject.toml` — this skill touches `tool.json` only.
- Do NOT delete fields the user added that aren't in the official schema — Pydantic `extra="forbid"` will catch them; leave them so the user sees the validator error and decides.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT add authentication or multi-user concepts.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
