---
name: tag-tool
description: Adds or removes a kebab-case keyword in one Pixie tool's tool.json tags array - sidebar filter pill. Use when the user asks to tag, mark, or categorise a tool with a keyword. Do NOT use to assign to a sidebar group (workspace-add-tool), label a run (label-run), or change inputs (update-tool).
allowed-tools: Bash, Read, Write, Edit, Glob
---

# Add or remove a tag on a Pixie tool

You are editing the `tags` array in one tool's `tool.json`. Tags are short kebab-case keywords used by the dashboard sidebar's filter pill. They are free-form (no central registry) and a tool can carry as many as the user wants. This skill never touches the tool's inputs, outputs, behaviour, dependencies, secrets, or its workspace membership.

The difference from `workspace-add-tool`: workspaces are top-level sidebar groups defined in `pixie.db`; tags are per-tool keywords stored inside `tool.json` and used for cross-cutting filtering.

The difference from `update-tool`: `update-tool` changes the tool's contract (schema, behaviour, deps); `tag-tool` only edits the `tags` array.

## Routing check (do this first)

- If the user wants to change the tool's inputs, outputs, or behaviour, switch to `update-tool`.
- If the user wants to put the tool in a sidebar group, switch to `workspace-add-tool`.
- If the user wants to rename the tool itself, switch to `rename-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Gather the inputs

You need:

1. The `tool_id`.
2. The `action` — `add` or `remove`.
3. One or more `tag` strings.

If the user said "tag geocoder as geospatial and uk", that maps to `tool_id=geocoder`, `action=add`, `tags=["geospatial", "uk"]`. If they said "untag the LLM tool — drop experimental", that maps to `tool_id=llm`, `action=remove`, `tags=["experimental"]`.

Normalise each tag: lowercase, replace spaces and underscores with hyphens, strip any character outside `[a-z0-9-]`. Reject any tag that becomes empty after normalisation.

### 2. Verify the tool exists

```bash
ls tools/<tool_id>/tool.json
```

If the file does not exist, STOP and tell the user the tool is not installed.

### 3. Read the current tags

`Read` `tools/<tool_id>/tool.json`. Find the `tags` array. If it does not exist, treat it as `[]`.

### 4a. If `action == add`: union the new tags

For each new tag, add it if it is not already present. If every tag was already there, tell the user no change was needed and stop.

### 4b. If `action == remove`: subtract the tags

For each tag to remove, drop it if present. If none of the tags were on the tool, tell the user no change was needed and stop. If removing every tag would leave the array empty, that is fine — write `"tags": []` rather than removing the key, so consumers can rely on the field being present.

### 5. Write the updated `tool.json`

Use `Edit` to replace the `tags` array. Preserve every other field byte-for-byte — same key order, same indentation (two spaces), same trailing newline. Do NOT reformat or reorder unrelated fields. If the file did not previously have a `tags` key, `Edit` it in immediately after the `name` field (the conventional position) with two-space indentation.

Show the user the before/after of the `tags` array as a diff before applying.

### 6. Validator handoff (mandatory final step)

The tags array is part of `tool.json`, so the validator's schema check applies. From the repo root:

```bash
uv run pixie validate <tool_id> --json
```

Parse the JSON. Branch on `overall`:

- `"pass"` — report success in one line. Surface any `warn` checks verbatim.
- `"warn"` — report success and list every check where `status == "warn"` verbatim, with `name`, `message`, and `details`.
- `"fail"` — DO NOT claim success. Output the entire JSON report verbatim in a fenced `json` block, then explain in plain language which checks failed. The most likely cause is a malformed `tool.json` (e.g. a JSON syntax error introduced by the edit). Offer to revert the edit, then end with: "Would you like me to hand this off to the `debug-tool` skill?" Stop.

Hard stop after two consecutive failed runs. Surface both reports and stop iterating.

### 7. Report completion

> "Tool `<tool_id>` now has tags: `<comma_separated_list>`. The sidebar filter will pick these up on next dashboard refresh."

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
The tag `<raw>` is empty after normalisation. Tags must contain at least one
character in [a-z0-9-]. Try again with a non-empty keyword.
```

## Do NOT

- Do NOT change any field in `tool.json` other than `tags`.
- Do NOT touch `main.py`, `pyproject.toml`, `.env`, the `.venv/`, or any other file.
- Do NOT use this skill to add a tool to a workspace — that is `workspace-add-tool`.
- Do NOT use this skill to rename the tool or to alter behaviour — those are `rename-tool` and `update-tool`.
- Do NOT accept tags with characters outside `[a-z0-9-]` after normalisation.
- Do NOT reformat or reorder unrelated fields in `tool.json`.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
