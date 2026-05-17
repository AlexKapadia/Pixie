---
name: implement-model-from-spec
description: Builds a Pixie tool from a detailed ML model spec - architecture, training setup, hyperparameters, expected metric. Use when the user wants to BUILD a specific model rigorously and has NO paper, repo, or code. Do NOT use given a paper (add-tool-from-paper), repo (add-tool-from-repo), or an informal idea (add-tool-from-description).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Implement a Pixie tool from a model specification

You are building a machine-learning tool from a detailed prose specification — architecture, training data, hyperparameters, expected metric. The output is a Pixie tool with both training and inference paths, validated against the user's stated reference metric via check #12.

## Routing check (do this first)

- If the user gave a PDF or arXiv URL, switch to `add-tool-from-paper`.
- If the user gave a Git URL, switch to `add-tool-from-repo`.
- If the user gave a `.py` or `.ipynb`, switch to `wrap-local-script` or `add-tool-from-notebook`.
- If the spec is informal ("build me a sentiment classifier") with no architecture, hyperparameters, or expected metric, switch to `add-tool-from-description`.
- If the dataset is not yet on disk, plan to chain into `fetch-dataset-from-kaggle`, `fetch-dataset-from-huggingface`, `fetch-dataset-from-url`, or `import-dataset-from-local` at step 3. The user decides; do not auto-invoke.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

- `.build/RESEARCH_paper_to_tool.md` §4-§5 (the generation flow + critique loop apply identically)
- `.build/RESEARCH_tool_internals.md` `ml-training` and `ml-inference` templates
- `.build/RESEARCH_dataset_import.md` §1 (the `data/datasets/<id>/` convention)

## Precheck refusals

Refuse cleanly if any apply:

- Spec requires a GPU and `pixie-doctor` reports no GPU. Refuse, or ask user to accept CPU-only with the caveat that training time and metric reproducibility will degrade.
- Spec calls for unlawful surveillance, biometric identification at scale, or models trained on copyright-infringing data the user does not have rights to.
- Spec is incomplete: missing architecture, missing dataset, OR missing expected metric. Ask the user to fill the gaps; do not guess.

## Steps

### 1. Capture the spec (human-gated)

Ask the user explicitly for every field. Do not infer silently:

- **Task:** classification, regression, segmentation, generation, embedding, ranking.
- **Architecture:** model family (MLP, CNN, Transformer, RNN, GBT, …), layer sizes, activations, normalisation.
- **Loss function** and **optimiser** (with learning rate, schedule, weight decay).
- **Dataset:** source (Kaggle / HF / URL / local), name, split strategy, preprocessing.
- **Hyperparameters:** batch size, epochs, seed, dropout, regularisation.
- **Expected metric on a known test set:** the value the user expects, the metric name (accuracy / F1 / RMSE / mAP / BLEU / …), and the tolerance.
- **Tool id and human name.**

Write the captured spec to `tools/.staging-<timestamp>/spec.yaml` and print it back to the user for confirmation. Wait for explicit confirmation before proceeding.

### 2. Plan and confirm (human gate)

Produce a numbered plan: dataset fetch step, scaffold step, model module step, training script step, inference handler step, fixture step. Constraints: training ≤ 10 minutes on CPU for the reference fixture (the user can run longer training out of band); inference ≤ 30s per `/run`. Print the plan. Wait for explicit confirmation.

### 3. Chain dataset fetch if needed

If the dataset is not already in a tool's `data/datasets/<id>/`, ask the user which fetcher to invoke and stop. The dataset fetcher writes provenance + manifest; resume this skill once the dataset is present.

### 4. Scaffold the tool

```bash
uv run pixie scaffold-tool --template=ml-training --id=<tool_id> --name="<name>"
```

Use `ml-training` if the user wants the training loop shipped; use `ml-inference` if only inference is needed (model weights ship under `models/`). The template covers `/run`, `/stream` (training loss), and `/cancel` per `RESEARCH_tool_internals.md`.

### 5. Implement model, training, and inference

- `src/<pkg>/model.py` — the architecture exactly as specified.
- `src/<pkg>/train.py` — training loop with the user's loss, optimiser, schedule, seed.
- `src/<pkg>/infer.py` — inference path that loads weights from `models/` and returns predictions.
- `src/<pkg>/handlers.py` — wires `/run` to either `train` or `infer` based on the input.
- Append exact dep pins to `pyproject.toml` runtime group (torch / sklearn / transformers / xgboost / …). Heavy GPU deps are flagged but installed CPU-only by default.

### 6. Run the critique loop (max 2 iterations)

Reuse the critique prompt from `RESEARCH_paper_to_tool.md` §5.2 adapted to "spec vs implementation". Catch off-by-one errors, wrong activation, wrong loss, wrong optimiser. Record each iteration's discrepancies in `tools/<tool_id>/docs/critique_log.md`.

### 7. Train once and capture the reference fixture

Run training to completion (with `--max-time 600` for the reference). Evaluate on the user-specified test set. Compare to the expected metric. Write the result as `reference/spec_metric.json` with `inputs.json` (the test-set descriptor or test ids) and `expected_outputs.json` (the metric value). Write `reference/tolerance.yaml` with the user-supplied tolerance.

If the achieved metric is outside tolerance, **do not relax tolerance silently**. Report the gap verbatim; ask the user whether to (a) re-run a critique round, (b) adjust training hyperparameters, or (c) accept the gap and update the spec.

### 8. Set the `source` field on tool.json

Per `DECISIONS.md` item 43:

```json
"source": {
  "type": "description",
  "reference": "spec.yaml (captured <timestamp>)",
  "checksum": "sha256:<spec-yaml-hash>",
  "generated_at": "<ISO8601>",
  "skill": "implement-model-from-spec"
}
```

Copy `spec.yaml` to `tools/<tool_id>/docs/spec.yaml`.

### 9. Install and validate

```bash
cd tools/<tool_id> && uv sync
uv run pixie validate <tool_id> --json
```

Validator handoff: branch on `overall` (`pass` / `warn` / `fail`) per the standard contract. Surface check #12's per-fixture diff verbatim on failure. End fails with: "Would you like me to hand this off to the `debug-tool` skill?" Hard stop after two consecutive failed validations.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't implement this model because <one-sentence reason>.

The spec skill requires:
- A complete architecture (layer types, sizes, activations)
- A complete training setup (loss, optimiser, dataset, hyperparameters)
- A known expected metric on a known test set, with tolerance
- No GPU-only training when this machine has no GPU
- No unlawful surveillance / biometric / copyright-infringing training data

Add the missing pieces to the spec and re-invoke me.
```

## Do NOT

- Do NOT skip the human gates at steps 1 and 2.
- Do NOT relax tolerance to make the reference fixture pass; that is the user's call.
- Do NOT silently install CUDA / GPU-only dependencies.
- Do NOT auto-invoke `fetch-dataset-from-*`. Offer the user a choice and stop.
- Do NOT bind to `0.0.0.0`; do NOT add authentication; do NOT add Docker.
- Do NOT write secret values into `main.py` or `tool.json`.
- Do NOT modify weights or datasets in place; write outputs under `tools/<tool_id>/models/`.
