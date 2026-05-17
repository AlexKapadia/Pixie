---
name: fetch-dataset-from-kaggle
description: Downloads a Kaggle dataset or competition into a Pixie tool's data folder using the user's Kaggle credentials. Use when the user asks to fetch, download, or import a Kaggle dataset for a named tool. Do NOT use for HuggingFace (fetch-dataset-from-huggingface), URLs (fetch-dataset-from-url), local files (import-dataset-from-local), or Kaggle notebooks.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Fetch a Kaggle dataset into a Pixie tool

You are downloading a Kaggle dataset or competition into a named Pixie tool's `data/datasets/<id>/files/` folder. Provenance, licence, checksums, and a manifest are written. The fetch runs in the tool's own venv (RULES §3); credentials stay user-level.

## Routing check (do this first)

- If the source is not Kaggle, switch to `fetch-dataset-from-huggingface`, `fetch-dataset-from-url`, or `import-dataset-from-local`.
- If the user did not name a Pixie tool to receive the dataset, ask which one. Refuse if the named tool does not exist under `tools/`.
- If the user wants a Kaggle kernel / notebook, refuse — kernels are deferred to v2. Suggest fetching the dataset the kernel uses instead.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

- `.build/RESEARCH_dataset_import.md` §1 (folder layout + manifest schema), §2 (Kaggle flow), §7 (safe extraction)
- `.build/DECISIONS.md` item 41 (the Kaggle credentials exception to RULES §4)

## Precheck refusals

Refuse cleanly if any apply:

- Tool does not exist at `tools/<tool_id>/`.
- Source is a Kaggle kernel / notebook (deferred).
- Estimated compressed size > 5 GB without explicit `--max-size <GB>` raise.
- Archive fails `safe_extract` (path traversal, symlinks, hard links).
- Licence is "competition rules" and the user has not acknowledged them.

## Kaggle credentials exception

Per `DECISIONS.md` item 41: Kaggle's PyPI library hard-codes `~/.kaggle/kaggle.json`. This is the **single** allowed exception to RULES §4 ("secrets live in the tool's own .env"). Pixie itself never reads or writes `~/.kaggle/kaggle.json`; only the subprocess running the fetch does. The skill must document this in any user-facing message and never echo the credential values.

## Steps

### 1. Confirm tool target

If invoked without a tool argument, ask which tool. Validate the tool folder exists at `tools/<tool_id>/`.

### 2. Parse the user's source

Accept three forms:

- `<owner>/<dataset>` (e.g. `zillow/zecon`) → dataset mode.
- `competition:<slug>` (e.g. `competition:titanic`) → competition mode.
- Full Kaggle URL → parse host + path and dispatch.

### 3. Credentials check

```bash
test -f ~/.kaggle/kaggle.json || ([ -n "$KAGGLE_USERNAME" ] && [ -n "$KAGGLE_KEY" ])
```

If both checks fail, stop and print:

> Kaggle credentials are not set. Go to https://www.kaggle.com/settings → "Create New API Token", download `kaggle.json`, and save it to `~/.kaggle/kaggle.json` (chmod 600). Per DECISIONS item 41 this is the one allowed exception to Pixie's per-tool secrets rule — Kaggle's library hard-codes that path.

Stop. Do not proceed.

### 4. Add `kaggle` to the tool's venv

If `kaggle` is not already a dependency, add it under a `dataset-fetch-kaggle` dependency group in `tools/<tool_id>/pyproject.toml`:

```toml
[dependency-groups]
dataset-fetch-kaggle = ["kaggle>=1.6"]
```

Run:

```bash
cd tools/<tool_id> && uv sync --group dataset-fetch-kaggle
```

### 5. Probe size and confirm

```bash
cd tools/<tool_id> && uv run kaggle datasets metadata -d <owner/name>
```

Read `dataset-metadata.json` for `totalBytes`. If > 100 MB, ask the user to confirm. If > 5 GB, refuse unless the user passes `--max-size <GB>`.

### 6. Download into a tempdir under the Pixie cache

```bash
cd tools/<tool_id> && uv run kaggle datasets download -d <owner/name> -p ~/.cache/pixie/fetchers/work/<sha8> --unzip
```

(For competitions: `kaggle competitions download -c <slug> -p ...` and unzip explicitly.) Stream the CLI progress to the user.

### 7. Safe-extract and move into the tool

Inspect every member. Reject path traversal, symlinks, hard links, and executables (`.exe`, `.bat`, `.sh`, `.ps1`) unless `--allow-scripts` is set. Strip `__macosx/`. Move clean members into `tools/<tool_id>/data/datasets/<dataset_id>/files/`.

### 8. Write the manifest

Compute sha256 + size + mime for every file. Sniff schema (column names + row count) for CSV/Parquet/JSONL. Fetch licence from `dataset-metadata.json` (map to SPDX). Fetch citation if present. Write:

- `tools/<tool_id>/data/datasets/<dataset_id>/manifest.json` per RESEARCH §1.4
- `tools/<tool_id>/data/datasets/<dataset_id>/README.md`
- `tools/<tool_id>/data/datasets/<dataset_id>/LICENSE.txt`
- `tools/<tool_id>/data/datasets/<dataset_id>/CITATIONS.bib` (if available)
- `tools/<tool_id>/data/datasets/<dataset_id>/.pixie-fetched` (atomicity marker)

The manifest records: `source: "kaggle"`, `source_url`, `fetched_at` ISO8601, `checksum` (sha256 of the archive), `licence`, `licence_spdx`, `total_size_bytes`, `files[]`, optional `columns`/`row_count`/`splits`.

### 9. Update the tool README

Append a `## Datasets` section listing this dataset id, its source URL, its licence, and the fetch timestamp.

### 10. Offer to regenerate reference fixtures

If `tools/<tool_id>/reference/` exists, ask the user whether to capture fresh `(inputs, expected_outputs)` pairs using this dataset. Do not auto-invoke.

### 11. Validator handoff (mandatory final step)

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
I can't fetch this Kaggle dataset because <one-sentence reason>.

The Kaggle fetcher is constrained to:
- Tool must exist under tools/<tool_id>/
- Credentials must be at ~/.kaggle/kaggle.json or KAGGLE_USERNAME+KAGGLE_KEY env vars
- Compressed size ≤ 5 GB by default (raise with --max-size)
- No kernels / notebooks (deferred to v2)
- Archive must pass safe_extract (no path traversal, no symlinks)

Resolve the blocker and re-invoke me.
```

## Do NOT

- Do NOT copy `~/.kaggle/kaggle.json` into the tool's `.env`. The user-level credential stays user-level.
- Do NOT echo or display the credential values in any message.
- Do NOT auto-execute downloaded scripts. Refuse `.exe`/`.sh`/`.bat`/`.ps1` members unless `--allow-scripts`.
- Do NOT write outside `tools/<tool_id>/data/datasets/<dataset_id>/`.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
- Do NOT bind to `0.0.0.0`; do NOT add authentication; do NOT add Docker.
