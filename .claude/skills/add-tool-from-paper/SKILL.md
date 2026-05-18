---
name: add-tool-from-paper
description: Implements an academic paper (PDF or arXiv URL) as a NEW Pixie tool with reference fixtures from reported numbers. Use when the user gives a paper or arXiv link and asks to implement, reproduce, or replicate it. Do NOT use to cite (cite-source), for code (add-tool-from-repo), or specs (implement-model-from-spec).
allowed-tools: Bash, WebFetch, Read, Write, Edit, Glob, Grep
---

# Add a Pixie tool from an academic paper

You are implementing the algorithm, model, or method described in a paper as a Pixie tool. The flow has nine steps; steps 3 and 4 are human-gated, step 9 is the mandatory validator handoff. Reference fixtures are captured from the paper's reported numbers and validated by check #12.

## Routing check (do this first)

- If the user gave a Git URL or a repo path, stop and ask whether they prefer `add-tool-from-repo` instead.
- If the user has a working `.py` / `.ipynb` and only wants it wrapped, switch to `wrap-local-script` or `add-tool-from-notebook`.
- If the user only has an informal description (no equations, no algorithm, no metrics), switch to `add-tool-from-description`.
- If the input is a detailed spec (architecture + hyperparams + expected metric) but not a paper, switch to `implement-model-from-spec`.

## Pre-flight: read the kill file (if present)

If `.build/KILL_FILE.md` exists in the repo root, scan it before touching existing patterns. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch. If the file does not exist, skip this step — it is a conceptual lookup, not a required artefact.

## Read before you act

These paths are conceptual references; if they are absent in the working tree, skip silently and rely on the inline guidance in this SKILL.md:

- `.build/RESEARCH_paper_to_tool.md` §4 (eight-step flow), §5 (critique loop), §9 (fixture layout)
- `.build/RESEARCH_tool_internals.md` (template selection)
- An existing `tools/<example>/tool.json` of a `layout: form` tool for shape reference (no specific tool is bundled with Pixie on a fresh clone).

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

**main.py contract — verbatim copy of the blank template.** The `main.py` this skill emits MUST start as a byte-for-byte copy of `pixie/templates_scaffold/blank/main.py`. The four endpoints (`/schema`, `/healthz`, `/run`, `/cancel`), the `__main__` runner, and the `RunRequest` pydantic model are byte-identical to that template. The ONLY change the skill makes is replacing the body of the `/run` handler with the tool-specific compute (parse inputs from `payload.inputs`, call the new equations/algorithms modules, return a dict matching the `outputs` keys in `tool.json`). Do not rename endpoints, do not switch to sync, do not remove the `__main__` block, do not change the host (`127.0.0.1`) or the `--port` argument.

**Self-test (mandatory).** After writing `main.py`, grep for each of the following literal strings. If ANY are absent, abort the skill with the message `main.py self-test failed: missing <token> — refusing to continue; the scaffold is broken`:

```
if __name__ == "__main__"
uvicorn.run(
--port
def healthz
"ok": True
def run(
def cancel(
def schema(
```

**pyproject.toml contract.** The generated `pyproject.toml` must list these as separate dependency entries in `[project].dependencies` (one string per entry, no merging):

```toml
dependencies = [
    "fastapi>=0.110",
    "uvicorn>=0.30",
    "pydantic>=2",
    "python-dotenv>=1",
    # ... paper-specific deps appended below
]
```

If the paper requires the reload-capable uvicorn (`uvicorn[standard]`), do NOT add it to `[project].dependencies`. Put it under an optional-dependencies group instead:

```toml
[project.optional-dependencies]
dev = ["uvicorn[standard]>=0.30"]
```

For each step in the plan, write or edit the relevant file. Equations become functions in `src/<pkg>/equations.py` with the LaTeX preserved verbatim in docstrings. Pseudocode becomes functions in `src/<pkg>/algorithms.py` with the original pseudocode in docstrings. Hyperparameters become defaulted inputs in `tool.json`. Copy `paper_extract.json` to `tools/<tool_id>/docs/paper_extract.json`.

If the paper depends on a released dataset, ask whether to chain into `fetch-dataset-from-kaggle`, `fetch-dataset-from-huggingface`, or `fetch-dataset-from-url` now. The user decides; do not auto-invoke.

### 6. Critique loop (autonomous, max 2 iterations)

Run the critique prompt from RESEARCH §5.2 comparing pseudocode/equations against the generated Python. Apply one fix round per iteration. Record each iteration's discrepancies in `tools/<tool_id>/docs/critique_log.md`. Hard cap at 2 iterations.

### 7. Write reference fixtures from reported numbers

For each table row the user selected in step 3, write `reference/paper_table_<N>.json` containing `inputs.json` + `expected_outputs.json`. Write `reference/tolerance.yaml` inferring precision from sig-figs in the source (typical `rtol = 1.0e-2` for empirically-reported numbers).

**tolerance.yaml format — YAML block style only.** Do NOT emit inline `{...}` mappings on the same line as a colon (e.g. `metric: {atol: 0.01, rtol: 0.001}` is forbidden because the validator's YAML reader rejects it). The exact required shape is:

```yaml
outputs:
  metric:
    atol: 0.01
    rtol: 0.001
  another_output:
    atol: 0.0
    rtol: 1.0e-2
```

One key per line, two-space indentation, no flow-style braces.

### 8. Record the source via `pixie cite` (do NOT add a top-level `source` block)

`pixie/discovery.py::ToolSchema` is declared with `model_config = ConfigDict(extra="forbid")`. Any unknown top-level key in `tool.json` (including `source`) causes validate check #1 to fail with a pydantic `extra_forbidden` error. The historic `"source": { ... }` block is therefore forbidden — **do not write it into tool.json**.

Instead, after scaffolding is complete, attribute the paper by invoking the `cite-source` skill (which writes citation metadata to a sibling location the validator accepts, not to `tool.json`'s root). Equivalent CLI form:

```bash
pixie cite <tool_id> \
  --paper "<title>" \
  --doi   "<doi-or-arxiv-id>" \
  --url   "<arxiv-or-publisher-url>"
```

Then append BibTeX to README under `## Source paper`, and add a top banner: `> Reproduced from "<title>" by <authors> (arXiv:<id>). Validated to <metric>=<value>±<tolerance> on <fixture_count> reference fixtures.`

### 9. Install and validate (mandatory, with auto-fix loop)

```bash
cd tools/<tool_id> && uv sync
```

Then run the validator from the repo root and act on the JSON report. **The skill MUST NOT declare success unless every check has status `pass` or `skip`.**

1. Run `uv run pixie validate <tool_id> --json` and parse the JSON.
2. Walk every entry under `checks[]`. Build a table with columns `id | name | status | message`. If any status is anything other than `pass` or `skip`, surface that table verbatim to the user before doing anything else.
3. Attempt up to TWO auto-fix passes for the known-failure modes below. After each pass, re-run `uv run pixie validate <tool_id> --json` and re-evaluate.

   | Symptom in check report | Auto-fix action |
   |---|---|
   | `extra_forbidden` on `tool.json` root, key `source` (or any other unknown root key) | Delete that key from `tool.json`. Move citation metadata via the `pixie cite` flow in step 8. |
   | Missing dependency `fastapi` / `uvicorn` / `pydantic` / `python-dotenv` reported by pyproject check | Insert the missing entry verbatim into `[project].dependencies` and re-run `uv sync`. |
   | `/healthz` check failed or returned non-`{"ok": true}` | Rewrite `main.py` so the `/healthz` handler matches the blank template byte-for-byte (`async def healthz() -> dict[str, bool]: return {"ok": True}`). |
   | `tolerance.yaml` parse error / inline-mapping rejected | Rewrite `tolerance.yaml` in block style (see §7). |

4. Branch on the final `overall` after at most two auto-fix passes:
   - `"pass"` — one-line success including the check #12 fixture count.
   - `"warn"` (with every other check `pass`/`skip`) — report success and list every `warn` verbatim.
   - Anything else — **abort with the literal message: "the scaffold is broken, do not use it yet"**, then print the full JSON in a fenced `json` block and offer three follow-ups: investigate (`debug-tool`), relax tolerance (user decides, never the skill), or re-run from `--from-step=critique`. Stop.
5. Never paraphrase a failed report. Never declare success on a `fail`. Hard stop after the second auto-fix pass still fails.

## On failure: append to the kill file (if it exists)

If `.build/KILL_FILE.md` exists and you encounter an error not already covered, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule. If the file does not exist, skip — do not create it.

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
