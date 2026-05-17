---
name: import-dataset-from-local
description: Copies, symlinks, or moves a local file or folder into a Pixie tool's data folder as a dataset. Use when the user gives a local path and asks to import it as a dataset. Do NOT use for URLs (fetch-dataset-from-url), Kaggle (fetch-dataset-from-kaggle), HuggingFace (fetch-dataset-from-huggingface), or a .py script (wrap-local-script).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Import a local file or folder as a dataset

You are placing a local file or folder under a Pixie tool's `data/datasets/<id>/files/` with a manifest. No network. Three modes: `--copy` (default, snapshot), `--symlink` (live link, POSIX only), `--move` (snapshot, removes original).

## Routing check (do this first)

- If the source is an HTTPS URL, switch to `fetch-dataset-from-url`.
- If the source is `kaggle.com`, switch to `fetch-dataset-from-kaggle`.
- If the source is `huggingface.co`, switch to `fetch-dataset-from-huggingface`.
- If the source is a `.py` file the user wants wrapped as a tool, switch to `wrap-local-script`.
- If the user did not name a Pixie tool to receive the dataset, ask which one. Refuse if the named tool does not exist.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

- `.build/RESEARCH_dataset_import.md` §1 (folder layout + manifest), §5 (local import flow), §7 (path-traversal safety)

## Precheck refusals

Refuse cleanly if any apply:

- Tool does not exist at `tools/<tool_id>/`.
- Source path does not exist or is not readable.
- Source is a symlink pointing outside the user's home, and `--allow-external` is not set.
- Source size > 5 GB without `--max-size <GB>`.
- `--symlink` requested on Windows (POSIX only).

## Steps

### 1. Confirm tool target

If invoked without a tool argument, ask which tool. Validate the tool exists at `tools/<tool_id>/`.

### 2. Validate the source path

The path must exist and be readable. If it is a symlink, resolve and reject if the target is outside the user's home (unless `--allow-external`). Probe size (`du -sb` on POSIX, `Get-ChildItem -Recurse | Measure-Object -Sum Length` on Windows).

### 3. Pick a dataset id

Default to the kebab-cased basename of the source. If `tools/<tool_id>/data/datasets/<dataset_id>/` already exists, ask the user whether to overwrite or pick a new id.

### 4. Apply the mode

- **`--copy` (default):** `shutil.copytree` for folders, `shutil.copy2` for files. The dataset is independent of the original.
- **`--symlink`:** POSIX only. `os.symlink(source, target)`. Refuses to symlink across filesystems by default. Faster, no disk cost; breaks if the user moves the source.
- **`--move`:** copy first, then remove the original on successful checksum. Used carefully — the user loses the source.

### 5. Optional safe unpack

If the user passed `--unpack` and the source is `.zip` / `.tar*` / `.7z`, run the same `safe_extract` path as `fetch-dataset-from-url` (no path traversal, no symlinks, no hard links, no executables). Otherwise leave the archive as-is.

### 6. Compute checksums

Iterate every file (including symlink targets) and compute sha256, size, mime. Always — even in `--symlink` mode this verifies the target at the time of import.

### 7. Sniff schema

For each CSV/Parquet/JSONL, peek the header for `columns` + `row_count`. Other formats leave both null.

### 8. Write the manifest and ancillary files

- `manifest.json` per RESEARCH §1.4 with:
  - `source: "local"`
  - `source_url: "local:<absolute-source-path>"`
  - `fetched_at: <ISO8601>`
  - `licence: "user-supplied — see notes"` (or whatever `--licence-spdx <SPDX>` set)
  - `notes: "<copy|symlink|move> mode"`
  - `files[]`, `total_size_bytes`, optional `columns`/`row_count`.
- `README.md` summarising what was imported.
- `.pixie-fetched` (atomicity marker).
- No `CITATIONS.bib` by default (local data has no canonical citation). User can supply `--cite "@article{...}"`.

### 9. Update the tool README

Append a `## Datasets` section listing this dataset id, the source path, the mode (copy / symlink / move), and the timestamp.

### 10. Offer to regenerate reference fixtures

If `tools/<tool_id>/reference/` exists, ask whether to capture fresh `(inputs, expected_outputs)` pairs using this dataset. Do not auto-invoke.

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
I can't import this local source because <one-sentence reason>.

The local-import skill is constrained to:
- Tool must exist under tools/<tool_id>/
- Source path must exist and be readable
- Source size ≤ 5 GB by default (raise with --max-size)
- Symlinks pointing outside the user's home require --allow-external
- --symlink mode is POSIX only

Resolve the blocker and re-invoke me.
```

## Do NOT

- Do NOT auto-unpack archives unless `--unpack` is passed.
- Do NOT cross-mount when `--symlink` is requested — refuse instead.
- Do NOT use `--move` without explicit user confirmation, especially across filesystems.
- Do NOT execute any imported scripts (`.exe`/`.sh`/`.bat`/`.ps1`).
- Do NOT write outside `tools/<tool_id>/data/datasets/<dataset_id>/`.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
- Do NOT bind to `0.0.0.0`; do NOT add authentication; do NOT add Docker.
