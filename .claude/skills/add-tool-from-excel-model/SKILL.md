---
name: add-tool-from-excel-model
description: Wraps an Excel .xlsx workbook as a Pixie tool by parsing its formula DAG and generating Python that reproduces every cell. Use when the user gives a .xlsx path and asks to wrap, port, or convert an Excel model. Do NOT use for .xlsm/.xlsb/.xls (refused), .csv (fetch-dataset-from-url), or prose.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Add a Pixie tool from an Excel workbook

You are wrapping a Microsoft Excel `.xlsx` workbook as a Pixie tool. The generated tool reproduces the spreadsheet's formula DAG in Python and validates every output against the workbook within float tolerance via reference fixtures (check #12).

## Routing check (do this first)

- If the file is not `.xlsx`, stop. `.xlsm`/`.xlsb`/`.xls`/`.ods` are refused (see below).
- If the user did NOT supply a workbook path, stop and ask for one. Do not invent.
- If `tools/<inferred_id>/` already exists, ask whether to switch to `update-tool` or pick a new id.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

- `tools/example-compound-interest/tool.json` (form-layout reference)
- `tools/example-compound-interest/src/example_compound_interest/handlers.py`
- `tools/example-compound-interest/pyproject.toml`
- `.build/RESEARCH_excel_to_tool.md` §7 (the algorithmic flow)
- `.build/RESEARCH_tool_internals.md` `form` template (scaffold target)

## Precheck refusals

Refuse cleanly (templates below) if any apply:

- Extension is `.xlsm`, `.xlsb`, `.xls`, or `.ods` (macros or binary — Pixie does not execute VBA).
- Workbook is password-protected / encrypted (ZIP signature shows encryption).
- File size > 50 MB (per RESEARCH §8).
- Workbook contains external links to other workbooks or web data sources.
- Formula DAG contains a circular reference (`formulas.finish()` raises; `find_cycle()` reports the cycle).
- Any formula uses a function in the refused set (RESEARCH §3.11 — RTD, HYPERLINK with side effects, GETPIVOTDATA against external pivots, VBA UDFs).

## Steps

### 1. Install the Excel skill extra

From the Pixie repo root:

```bash
uv sync --extra excel-skill
```

This installs `formulas>=1.3.4` and `openpyxl>=3.1.5` into Pixie's own venv so the inspector helpers can import them. Pixie itself never imports them at runtime — only this skill does.

### 2. Inspect the workbook

Run the inspector helper to build a `WorkbookInventory`:

```bash
uv run python -m pixie.scaffold.excel_inspector "<path>"
```

The inventory lists sheets, named ranges, candidate inputs (cells with raw values referenced by other cells), candidate outputs (formula cells not referenced by any other cell), unsupported functions, and volatile functions (`RAND`, `RANDBETWEEN`, `NOW`, `TODAY`). If volatiles are present, plan to introduce a `seed` input per RESEARCH §4.3.

If the inspector raises a circular-reference error, stop and show the cycle verbatim.

### 3. Propose inputs and outputs to the user

Print the markdown summary the inspector produced. Ask the user to confirm or override:

- Which cells are inputs (with type hint: number, integer, percentage, currency, date, string, boolean, enum-from-data-validation).
- Which cells are outputs (with output_type hint: number, currency, table, chart, kv).
- Tool id and human name (default to the workbook filename, kebab-cased).

Wait for explicit confirmation before scaffolding. Do not proceed silently.

### 4. Scaffold the tool

```bash
uv run pixie scaffold-tool --template=form --id=<tool_id> --name="<name>"
```

This creates `tools/<tool_id>/` with the standard `form` layout from `RESEARCH_tool_internals.md`.

### 5. Generate code (Mode A — call `formulas` at runtime)

Write `src/<pkg>/model.py` that loads `data/model.xlsx` via `formulas.ExcelModel().loads().finish()`, takes the inputs dict, sets the input cells, recalculates, and returns the output cells. Overwrite `tool.json` with the synthesised inputs/outputs (per RESEARCH §6.1, §6.2). Overwrite `src/<pkg>/handlers.py` to delegate to `model.py`. Copy the workbook to `tools/<tool_id>/data/model.xlsx` (the runtime ships the source spreadsheet).

Append `formulas>=1.3.4`, `openpyxl>=3.1.5`, `numpy>=2.0` to `pyproject.toml` runtime deps.

### 6. Write reference fixtures (5–10 samples)

Sample inputs deterministically from `sha256(workbook_bytes)` per RESEARCH §7.2. For each sample, set the cells, recompute via `formulas`, and capture the output cells as `expected_outputs`. Write each pair to `reference/fixture_<NN>.json`. Write `reference/tolerance.yaml` with defaults: `number.rtol = 1.0e-6`, `number.atol = 1.0e-9`; tighter for currency outputs (`rtol = 1.0e-4` matching Excel's display precision).

### 7. Set the `source` field on tool.json

Per `DECISIONS.md` item 43:

```json
"source": {
  "type": "excel",
  "reference": "<original-workbook-name>.xlsx",
  "checksum": "sha256:<hex>",
  "generated_at": "<ISO8601>",
  "skill": "add-tool-from-excel-model"
}
```

### 8. Install dependencies

```bash
cd tools/<tool_id> && uv sync
```

### 9. Validator handoff (mandatory final step)

1. From the repo root:
   ```bash
   uv run pixie validate <tool_id> --json
   ```

2. Parse the JSON. Branch on `overall`:
   - `"pass"` — one-line success including check #12 fixture count, e.g. "Tool `<tool_id>` validated — 8/8 reference fixtures matched within tolerance." Surface any `warn` checks verbatim.
   - `"warn"` — report success and list every `warn` check verbatim, including which fixtures degraded.
   - `"fail"` — DO NOT claim success. Output the entire JSON in a fenced `json` block, explain which checks failed (with special attention to check #12 `reference_fixtures_match` if it fired — the per-cell diff is the user's path to fixing the model). End with: "Would you like me to hand this off to the `debug-tool` skill?" Stop.

3. Never paraphrase a failed report. Hard stop after two consecutive failed validations.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't wrap this workbook as a Pixie tool because <one-sentence reason>.

The Excel skill is constrained to:
- .xlsx workbooks only (no macros, no binary formats, no OpenDocument)
- No password protection or encryption
- No external links to other workbooks or web data
- No circular references
- File size ≤ 50 MB

If you can produce a slimmed-down .xlsx that contains only the formulas you
need, I can wrap that instead.
```

## Do NOT

- Do NOT enable macro execution. `.xlsm` files are refused unconditionally.
- Do NOT follow external links — the workbook must be self-contained.
- Do NOT silently relax tolerance to make fixtures pass; if a fixture fails, surface it.
- Do NOT modify the source workbook. Copy it into `data/model.xlsx` and treat the copy as immutable at runtime.
- Do NOT bind to `0.0.0.0`; do NOT add authentication; do NOT add Docker.
- Do NOT write secret values into `main.py` or `tool.json`.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
