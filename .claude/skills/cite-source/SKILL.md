---
name: cite-source
description: Records a citation, attribution, or source provenance (paper, Excel checksum, DOI, repo commit) on an EXISTING Pixie tool. Use when the user asks to cite, attribute, credit, or add a citation to a tool. Do NOT use to implement a paper anew (add-tool-from-paper), change behaviour (update-tool), or tag.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Annotate a Pixie tool's source provenance

You are adding or updating the `source` field on a Pixie tool's `tool.json` and the corresponding `## Source` section in its README. This skill is for tools the user hand-built (or regenerated outside the creator skills) that nonetheless derive from a known source — a paper, an Excel workbook, a dataset, or a Git repo commit.

## Routing check (do this first)

- If the user wants to GENERATE a new tool from a source, switch to `add-tool-from-paper`, `add-tool-from-excel-model`, `add-tool-from-repo`, or `implement-model-from-spec` — those skills set the `source` field themselves.
- If the user wants to MODIFY tool behaviour, inputs, or dependencies, switch to `update-tool`.
- If the user wants to add a tag or workspace, switch to `tag-tool` or `workspace-add-tool`.
- If the tool does not exist under `tools/`, stop and ask the user which tool they mean.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

- `tools/<tool_id>/tool.json` — the existing schema, especially any current `source` field.
- `tools/<tool_id>/README.md` — to insert the `## Source` section in the right place.
- `.build/DECISIONS.md` item 43 (the `source` field schema; this is the authoritative shape).

## Precheck refusals

Refuse cleanly if any apply:

- Tool does not exist at `tools/<tool_id>/`.
- The user supplies neither a paper reference, nor a workbook path, nor a dataset DOI, nor a repo URL/commit — there is nothing to cite.
- The user wants to cite a source whose licence forbids attribution disclosure (rare; ask the user to confirm).

## The `source` field schema (per DECISIONS item 43)

Top-level on `tool.json`:

```json
"source": {
  "type": "excel" | "paper" | "description" | "repo" | "dataset",
  "reference": "<human-readable id>",
  "checksum": "sha256:<hex>" | null,
  "generated_at": "<ISO8601>",
  "skill": "cite-source"
}
```

Validated by Pixie's `ToolSchema` (polish-pass addition). If the field is malformed, the validator's check #2 (`tool_json_valid`) will fail.

## Steps

### 1. Identify the tool

If the user did not name a tool, list candidates with `Glob` on `tools/*/tool.json` and ask which one.

### 2. Pick the source type and gather the reference

Ask the user which of the five types applies and capture the canonical reference:

- **`paper`** — `arXiv:<id>` or `DOI:<doi>`. Ask for full BibTeX (multi-line).
- **`excel`** — absolute path to the workbook the user derived the tool from. Compute `sha256` of the file (if accessible).
- **`dataset`** — dataset DOI (Zenodo / Figshare / Dryad), or `kaggle:<owner>/<name>`, or `huggingface:<namespace>/<name>`. If the dataset is already under `tools/<tool_id>/data/datasets/<id>/manifest.json`, read the checksum from there.
- **`repo`** — Git URL plus a commit SHA (full 40-char preferred; refuse a "main" reference because it drifts).
- **`description`** — a path or URL to the spec / description document. Compute `sha256` if it's a file.

### 3. Compute the checksum (where applicable)

```bash
sha256sum "<path>"   # POSIX
Get-FileHash -Algorithm SHA256 "<path>"   # PowerShell
```

For `paper` (arXiv with no local PDF) and `description` (referenced URL), leave `checksum: null` and document the URL in `reference`.

### 4. Write the `source` field on tool.json

Use `Edit` to add or replace the top-level `source` object. Preserve the rest of `tool.json` byte-for-byte. Set `generated_at` to the current ISO8601 timestamp. Set `skill: "cite-source"`.

### 5. Add or update the README `## Source` section

Insert (or replace) a section near the bottom of `tools/<tool_id>/README.md`:

```markdown
## Source

This tool was derived from <type>: <reference>.

- Type: <type>
- Reference: <reference>
- Checksum: <checksum or "n/a">
- Recorded by: cite-source on <ISO8601>

<BibTeX block here for `paper` type, in a fenced ```bibtex code block>
```

For `paper` type, append the full BibTeX in a fenced `bibtex` block exactly as the user supplied. For `dataset` type, append the `CITATIONS.bib` content from the dataset's manifest folder if present.

### 6. Update CHANGELOG.md if present

If the tool has a `CHANGELOG.md`, append one entry under the current version:

```markdown
- Documented source provenance via cite-source: <type>: <reference>.
```

If no `CHANGELOG.md` exists, do not create one — this skill is intentionally narrow.

### 7. Validator handoff (mandatory final step)

1. `uv run pixie validate <tool_id> --json` from repo root.
2. Branch on `overall`:
   - `"pass"` — one-line success: "Tool `<tool_id>` source field set to <type>: <reference> and validated."
   - `"warn"` — report success and surface every `warn` verbatim.
   - `"fail"` — DO NOT claim success. Print the entire JSON in a fenced `json` block, explain which checks failed (most likely check #2 `tool_json_valid` if the `source` field is malformed). End with: "Would you like me to hand this off to the `debug-tool` skill?" Stop.
3. Never paraphrase a failed report. Hard stop after two consecutive failed validations.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't add source provenance to this tool because <one-sentence reason>.

The cite-source skill requires:
- Tool must exist under tools/<tool_id>/
- A canonical reference of one of five types: paper, excel, dataset, repo, description
- For repo type, a commit SHA (not a branch — branches drift)
- For excel/description, the source file must be readable if you want a checksum

Tell me which type applies and supply the reference, and I'll write the field.
```

## Do NOT

- Do NOT modify any field on `tool.json` other than `source`. Use `update-tool` for behaviour or metadata changes.
- Do NOT modify code under `src/` or `main.py`. Use `update-tool` or `debug-tool`.
- Do NOT regenerate the tool from the source — that's `add-tool-from-paper`, `add-tool-from-excel-model`, etc.
- Do NOT invent a BibTeX citation. If the user did not supply one, leave the README section without it.
- Do NOT accept `main` / `master` / `HEAD` as a repo reference — require a commit SHA so the citation is reproducible.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
- Do NOT bind to `0.0.0.0`; do NOT add authentication; do NOT add Docker.
