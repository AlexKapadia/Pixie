---
name: fetch-dataset-from-huggingface
description: Downloads a HuggingFace Hub dataset (public or token-gated) into a Pixie tool's data folder. Use when the user asks to fetch or import an HF dataset for a named tool. Do NOT use for Kaggle (fetch-dataset-from-kaggle), URLs (fetch-dataset-from-url), local files (import-dataset-from-local), or HF MODELS (use transformers).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Fetch a HuggingFace dataset into a Pixie tool

You are downloading a HuggingFace Hub dataset into a named Pixie tool's `data/datasets/<id>/files/` folder. Supports public datasets (no token) and private / gated datasets (HF_TOKEN in the tool's `.env`). The fetch runs in the tool's own venv.

## Routing check (do this first)

- If the source is not HuggingFace Hub, switch to `fetch-dataset-from-kaggle`, `fetch-dataset-from-url`, or `import-dataset-from-local`.
- If the user wants a HuggingFace MODEL (e.g. `bert-base-uncased`), that is not a dataset — refuse and tell them to add `transformers` / `diffusers` to the tool and load via `from_pretrained`.
- If the user did not name a Pixie tool to receive the dataset, ask which one. Refuse if the named tool does not exist.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

- `.build/RESEARCH_dataset_import.md` §1 (folder layout + manifest), §3 (HuggingFace flow), §7 (safe extraction)

## Precheck refusals

Refuse cleanly if any apply:

- Tool does not exist at `tools/<tool_id>/`.
- Dataset is gated and the user has no `HF_TOKEN` and declines to add one.
- Materialised size > 5 GB without `--max-size` raise (offer streaming mode instead).
- Source is a model repo (not a dataset repo).

## Steps

### 1. Confirm tool target

If invoked without a tool argument, ask which tool. Validate the tool exists at `tools/<tool_id>/`.

### 2. Parse the source

Accept `<namespace>/<name>` with optional `:config` and optional `:split` (e.g. `glue:mrpc:train[:10%]`).

### 3. Add `datasets[parquet]` to the tool's venv

If not already a dependency, add under a `dataset-fetch-huggingface` group in `tools/<tool_id>/pyproject.toml`:

```toml
[dependency-groups]
dataset-fetch-huggingface = ["datasets[parquet]>=2.20"]
```

Then:

```bash
cd tools/<tool_id> && uv sync --group dataset-fetch-huggingface
```

### 4. Probe size and pick a mode

```bash
cd tools/<tool_id> && uv run python -c "from datasets import load_dataset_builder; b = load_dataset_builder('<name>', '<config>'); print(b.info.size_in_bytes)"
```

- If size ≤ 2 GB → **materialise mode** (default).
- If size > 2 GB and ≤ 5 GB → ask the user: materialise or stream?
- If size > 5 GB → refuse unless `--max-size <GB>` is set.

### 5. Token handling (only on 401/403)

First attempt: no token. If the HF Hub returns 401 or 403, stop and ask the user:

> This dataset is gated. Add `HF_TOKEN=<your-token>` to `tools/<tool_id>/.env` (get one from https://huggingface.co/settings/tokens). Then re-invoke me.

Do not echo the token. Do not write the token to manifest or README. Do not copy it across tools.

### 6. Download

**Materialise mode:**

```bash
cd tools/<tool_id> && uv run python -m pixie.scaffold.dataset_hf_materialise <name> <config> <split>
```

Helper calls `load_dataset(name, config, cache_dir=<tempdir>/.hf_cache)`, then `ds.save_to_disk(<tempdir>/files)`. For tabular datasets also exports `train.parquet` / `test.parquet` / `validation.parquet`.

**Stream mode:**

Build the manifest with `format: "streaming"` and `files: []`. Store the dataset id + config + split string so the tool calls `load_dataset(..., streaming=True)` at runtime. Optionally cache the first 100 rows as `sample.jsonl` for offline fixture runs.

### 7. Safe-move into the tool

Move clean files into `tools/<tool_id>/data/datasets/<dataset_id>/files/`. Reject path traversal, symlinks, hard links per RESEARCH §7.

### 8. Sniff schema and licence

`ds.info.features` → `columns`. `ds.info.splits` → `splits`. `ds.info.license` → `licence_spdx` (map to SPDX). `ds.info.citation` → `CITATIONS.bib`. `ds.info.description` → `README.md`.

### 9. Write the manifest and ancillary files

- `manifest.json` per RESEARCH §1.4 with `source: "huggingface"`, `source_url`, `fetched_at`, `checksum`, `licence`, `licence_spdx`, `total_size_bytes`, `files[]`, `columns`, `row_count`, `splits`.
- `README.md`, `LICENSE.txt`, `CITATIONS.bib`, `.pixie-fetched` (atomicity marker).

### 10. Update the tool README

Append a `## Datasets` section listing this dataset id, source URL, licence, fetch timestamp, and whether materialised or streaming.

### 11. Offer to regenerate reference fixtures

If `tools/<tool_id>/reference/` exists, ask whether to capture fresh `(inputs, expected_outputs)` pairs using this dataset. Do not auto-invoke.

### 12. Validator handoff (mandatory final step)

1. `uv run pixie validate <tool_id> --json` from repo root.
2. Branch on `overall`:
   - `"pass"` — one-line success.
   - `"warn"` — list every `warn` verbatim.
   - `"fail"` — DO NOT claim success. Print the entire JSON in a fenced block, explain which checks failed. End with: "Would you like me to hand this off to the `debug-tool` skill?" Stop.
3. Never paraphrase a failed report. Hard stop after two consecutive failed validations.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't fetch this HuggingFace dataset because <one-sentence reason>.

The HuggingFace fetcher is constrained to:
- Tool must exist under tools/<tool_id>/
- Gated datasets require HF_TOKEN in the tool's .env
- Materialised size ≤ 5 GB (or use --stream)
- Source must be a DATASET repo, not a MODEL repo

Resolve the blocker and re-invoke me. For HuggingFace MODELS, add transformers
or diffusers to the tool and load via from_pretrained at runtime.
```

## Do NOT

- Do NOT echo or display the HF_TOKEN in any message.
- Do NOT copy the HF_TOKEN across tools — it stays in this tool's `.env`.
- Do NOT auto-execute downloaded archives. Reject `.exe`/`.sh`/`.bat`/`.ps1` members.
- Do NOT write outside `tools/<tool_id>/data/datasets/<dataset_id>/`.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
- Do NOT bind to `0.0.0.0`; do NOT add authentication; do NOT add Docker.
- Do NOT pre-emptively send the token on public datasets.
