---
name: add-tool-from-paper
description: Implements an academic paper (PDF or arXiv URL) as a NEW Pixie tool with reference fixtures from reported numbers. Use when the user gives a paper or arXiv link and asks to implement, reproduce, or replicate it. Do NOT use to cite (cite-source), for code (add-tool-from-repo), or specs (implement-model-from-spec).
allowed-tools: Bash, WebFetch, Read, Write, Edit, Glob, Grep
---

# Add a Pixie tool from an academic paper

You are implementing the algorithm, model, or method described in a paper as a Pixie tool. The flow has eight steps; steps 3 and 4 are human-gated. Reference fixtures are captured from the paper's reported numbers and validated by check #12.

## Routing check (do this first)

- If the user gave a Git URL or a repo path, stop and ask whether they prefer `add-tool-from-repo` instead.
- If the user has a working `.py` / `.ipynb` and only wants it wrapped, switch to `wrap-local-script` or `add-tool-from-notebook`.
- If the user only has an informal description (no equations, no algorithm, no metrics), switch to `add-tool-from-description`.
- If the input is a detailed spec (architecture + hyperparams + expected metric) but not a paper, switch to `implement-model-from-spec`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

- `.build/RESEARCH_paper_to_tool.md` §4 (eight-step flow), §5 (critique loop), §9 (fixture layout)
- `.build/RESEARCH_tool_internals.md` (template selection)
- `tools/example-compound-interest/tool.json` (form-layout reference)

## Precheck refusals

Refuse cleanly if any apply:

- Content category: offensive cyber, CBRN uplift, CSAM-adjacent, or targeted disinformation. Stop with the refusal template below.
- Paper requires a GPU and `pixie-doctor` reports no GPU on this machine. Offer to refuse, or to proceed CPU-only with the user accepting that fixtures may not be reproducible.
- Paper is image-only / scanned and `marker-pdf` extracts < 500 chars. Suggest `--extractor=mineru` as opt-in heavy mode.
- Paper is a survey / position paper (no equations, no algorithms, no tables). Tell the user there is nothing to implement.

## Steps

### 1. Install the paper skill extra

From the Pixie repo root:

```bash
uv sync --extra paper-skill
```

This installs `arxiv>=2.1`, `marker-pdf>=0.4`, `pymupdf>=1.24` into Pixie's own venv. Pixie itself never imports them; only this skill does.

### 2. Resolve and extract the source

- If the input is an arXiv URL or id (`arxiv.org/abs/<id>` or `arXiv:<id>`), fetch the LaTeX source via the `arxiv` library.
- If the input is a PDF path or PDF URL, extract via `marker-pdf` (default) or `MinerU` (opt-in `--extractor=mineru`).

Write `paper_extract.json` to `tools/.staging-<timestamp>/` capturing: title, authors, abstract, section structure, equations (LaTeX with context), pseudocode blocks, tables, reported numbers, hyperparameters, dataset references, code/model references, licence.

### 3. Summarise and confirm with the user (human gate)

Print the structured summary per RESEARCH §4.2: paper_shape, core_idea, inputs, hyperparameters, outputs, headline_number, reproducibility_class, tool_shape_recommendation, internal_template, estimated_complexity.

Ask the user four questions:

1. "Does the paper shape look right? (algorithm / ml_training / method / dataset / benchmark)"
2. "Which reported result(s) do you want as reference fixtures? Pick by index or `all`."
3. "If the paper releases code at `<URL>`, would you prefer to wrap that repo via `add-tool-from-repo` instead?"
4. "Tool id and human name? (defaults: `<arxiv-id-slug>`, paper title)"

**Wait for explicit answers.** Do not proceed silently.

### 4. Plan and confirm (human gate)

Produce a numbered implementation plan per RESEARCH §4.4 — one step per module / fixture / dependency / input / output. Constraints: ≤ 30s runtime per `/run` on CPU, ≤ 2 GB memory, no GPU unless flagged. Print the plan. Wait for explicit confirmation. The user may edit `plan.yaml` and re-invoke with `--from-step=plan`.

### 5. Scaffold and implement

```bash
uv run pixie scaffold-tool --template=<chosen> --id=<tool_id> --name="<name>"
```

For each step in the plan, write or edit the relevant file. Equations become functions in `src/<pkg>/equations.py` with the LaTeX preserved verbatim in docstrings. Pseudocode becomes functions in `src/<pkg>/algorithms.py` with the original pseudocode in docstrings. Hyperparameters become defaulted inputs in `tool.json`. Copy `paper_extract.json` to `tools/<tool_id>/docs/paper_extract.json`.

If the paper depends on a released dataset, ask whether to chain into `fetch-dataset-from-kaggle`, `fetch-dataset-from-huggingface`, or `fetch-dataset-from-url` now. The user decides; do not auto-invoke.

### 6. Critique loop (autonomous, max 2 iterations)

Run the critique prompt from RESEARCH §5.2 comparing pseudocode/equations against the generated Python. Apply one fix round per iteration. Record each iteration's discrepancies in `tools/<tool_id>/docs/critique_log.md`. Hard cap at 2 iterations.

### 7. Write reference fixtures from reported numbers

For each table row the user selected in step 3, write `reference/paper_table_<N>.json` containing `inputs.json` + `expected_outputs.json`. Write `reference/tolerance.yaml` inferring precision from sig-figs in the source (typical `rtol = 1.0e-2` for empirically-reported numbers).

### 8. Set the `source` field on tool.json

Per `DECISIONS.md` item 43:

```json
"source": {
  "type": "paper",
  "reference": "<arxiv-id-or-DOI>",
  "checksum": "sha256:<pdf-hash-or-null>",
  "generated_at": "<ISO8601>",
  "skill": "add-tool-from-paper"
}
```

Append BibTeX to README under `## Source paper`. Add a top banner: `> Reproduced from "<title>" by <authors> (arXiv:<id>). Validated to <metric>=<value>±<tolerance> on <fixture_count> reference fixtures.`

### 9. Install and validate

```bash
cd tools/<tool_id> && uv sync
```

Then the validator handoff:

1. `uv run pixie validate <tool_id> --json` from repo root.
2. Branch on `overall`:
   - `"pass"` — one-line success including check #12 fixture count.
   - `"warn"` — report success, list every `warn` verbatim.
   - `"fail"` — DO NOT claim success. Print the entire JSON in a fenced `json` block, explain which checks failed (especially check #12 — the per-output diff localises the discrepancy in the algorithm). Offer three follow-ups: investigate (`debug-tool`), relax tolerance (user decides, never the skill), or re-run from `--from-step=critique`. Stop.
3. Never paraphrase a failed report. Hard stop after two consecutive failed validations.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't implement this paper as a Pixie tool because <one-sentence reason>.

The paper skill is constrained to:
- No content advancing offensive cyber, CBRN, CSAM, or targeted disinformation
- No GPU-only models when this machine has no GPU (per pixie-doctor)
- No scanned / image-only PDFs (without --extractor=mineru opt-in)
- Equations, an algorithm, or tables must be extractable

If you can point me at a smaller, well-defined subset of the paper — one
specific algorithm, one specific equation, one specific metric — I can
implement that.
```

## Do NOT

- Do NOT skip the human gates at steps 3 and 4. Surprise generation is forbidden.
- Do NOT relax tolerance to make a fixture pass; that is the user's call.
- Do NOT silently install GPU-only dependencies.
- Do NOT invoke `add-tool-from-repo` or `fetch-dataset-from-*` programmatically. Offer the user a choice and stop.
- Do NOT modify the source PDF or LaTeX. Copy extracts into `tools/<tool_id>/docs/` and treat them as immutable.
- Do NOT bind to `0.0.0.0`; do NOT add authentication; do NOT add Docker.
- Do NOT write secret values into `main.py` or `tool.json`.
