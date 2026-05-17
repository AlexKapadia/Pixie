---
name: validate-against-reference
description: "Runs Pixie's accuracy validator (check #12 only) against ONE tool's reference fixtures, reporting per-output diffs with tolerance-aware comparison. Use when the user asks to validate accuracy, check correctness, or confirm reproducibility. Do NOT use to run ALL 12 checks (debug-tool), revalidate every tool (revalidate-all), or check Pixie itself (pixie-doctor)."
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Validate a Pixie tool against its reference fixtures

You are running Pixie's check #12 (`reference_fixtures_match`) against one named tool. The check loads every `reference/fixture_*.json`, runs each through the warm tool subprocess, and deep-compares outputs against `expected_outputs` using the tolerance hierarchy in `RESEARCH_reference_validator.md` §3. Failures are surfaced verbatim with per-fixture diffs.

## Routing check (do this first)

- If the user wants to run ALL 12 checks and fix issues, switch to `debug-tool`.
- If the user wants to re-validate EVERY tool, switch to `revalidate-all`.
- If Pixie itself is broken, switch to `pixie-doctor`.
- If the tool does not exist under `tools/`, stop and suggest `add-tool-from-description`, `add-tool-from-paper`, `add-tool-from-excel-model`, or `implement-model-from-spec`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

- `.build/RESEARCH_reference_validator.md` §1 (fixture layout), §3 (tolerance hierarchy), §4 (check #12 algorithm), §9 (skill workflow), §10 (creator-skill integration)

## Precheck refusals

Refuse cleanly if any apply:

- Tool does not exist at `tools/<tool_id>/`.
- Tool has no `reference/` folder AND the user declines to capture fixtures from the source artefact.
- All fixtures resolve to `compare: "skip"` (the check does nothing useful — warn and stop).

## Steps

### 1. Resolve the tool

If the user did not name a tool, list candidates with `Glob` on `tools/*/tool.json` and ask which one.

### 2. Check fixtures exist

```bash
ls tools/<tool_id>/reference/fixture_*.json 2>/dev/null | head -20
```

If empty, tell the user no fixtures exist yet and offer four follow-ups (per RESEARCH §9, the skill never fakes a pass):

- **(a)** If the tool was generated from an Excel workbook, offer to re-invoke `add-tool-from-excel-model` to capture fixtures by sampling the workbook.
- **(b)** If the tool was generated from a paper, offer to re-invoke `add-tool-from-paper` and pick reported numbers as fixtures.
- **(c)** If the tool was built from a spec, offer `implement-model-from-spec`'s fixture-capture path.
- **(d)** If the user has nothing to compare against, capture fixtures from the tool's *current* outputs as a "lock-in" — **requires explicit user confirmation**; do not assume.

Each option is the user's choice. Do not auto-invoke a creator skill.

### 3. Run the reference-only check

```bash
uv run pixie validate <tool_id> --reference-only --json
```

The `--reference-only` flag runs check #12 in isolation; faster than the full 12-check pass. The `--json` flag returns the full `ValidationReport` with the per-fixture diff structure described in `RESEARCH_reference_validator.md` §5.

### 4. Parse and surface verbatim

Branch on `overall`:

- **`"pass"`** — print one line: "Tool `<tool_id>` matched all <N> reference fixtures within tolerance." Surface any `warn` entries verbatim.
- **`"warn"`** — typically means every fixture resolved to `skip`. Tell the user the check is doing nothing useful and suggest tightening `reference/tolerance.yaml` or replacing `compare: "skip"` entries.
- **`"fail"`** — DO NOT claim success. Print the entire JSON in a fenced `json` block. Then surface the formatted per-fixture diff exactly as the report's `details` markdown returned it (the tables in `RESEARCH_reference_validator.md` §5). Do not paraphrase, do not "round" the diffs, do not say "close enough".

### 5. Offer two follow-ups on failure (never auto-execute)

Print verbatim:

> Options:
> 1. Investigate the failing fixtures → I can hand this off to the `debug-tool` skill with the diff as context.
> 2. Update the expected values → I can re-capture fixtures from the tool's current outputs with `--update-fixtures` (this locks in present behaviour as the new truth — explicit confirmation required, never silent).

Then stop. The user picks.

### 6. Token efficiency

If more than five fixtures failed, re-invoke with a summary mode:

```bash
uv run pixie validate <tool_id> --reference-only --summary --json
```

Surface only the per-fixture pass/fail roster. Expand into full diffs only when the user asks for a specific fixture.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't run a reference check on this tool because <one-sentence reason>.

The reference validator requires:
- Tool must exist under tools/<tool_id>/
- At least one reference/fixture_*.json file
- At least one fixture with compare != "skip"

If the tool has no fixtures, I can offer to capture them from the source
artefact (Excel workbook, paper, spec) — but the creator skill does that
work, not me. Tell me which source the tool was generated from and I'll
suggest the right hand-off.
```

## Anti-patterns the skill must avoid (from RESEARCH §9)

- Do NOT quote a "looks close enough" judgement. If the validator says fail, the answer is fail.
- Do NOT propose tightening tolerance to make a failing fixture pass — that's the user's call, never the agent's.
- Do NOT run `--update-fixtures` without explicit confirmation.
- Do NOT modify `reference/tolerance.yaml` on the user's behalf.

## Do NOT

- Do NOT run the full 12-check validator; use `--reference-only` (this is the routing distinction from `debug-tool`).
- Do NOT auto-invoke `debug-tool` or any creator skill. Offer the user a choice and stop.
- Do NOT write to `tools/<tool_id>/reference/*` without an explicit user instruction (the `--update-fixtures` flow).
- Do NOT bind to `0.0.0.0`; do NOT add authentication; do NOT add Docker.
- Do NOT paraphrase a failed report. The user must see the exact `expected`, `actual`, `metric`, and `tolerance` values for every failing fixture.
