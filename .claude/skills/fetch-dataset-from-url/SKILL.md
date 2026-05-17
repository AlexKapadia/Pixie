---
name: fetch-dataset-from-url
description: Downloads a dataset from any HTTPS URL into a Pixie tool's data folder with safe extraction and checksum verification. Use when the user gives a non-Kaggle non-HuggingFace data URL and asks to fetch it. Do NOT use for Kaggle (fetch-dataset-from-kaggle), HuggingFace (fetch-dataset-from-huggingface), local paths (import-dataset-from-local), or Git repos (add-tool-from-repo).
allowed-tools: Bash, WebFetch, Read, Write, Edit, Glob, Grep
---

# Fetch a dataset from a URL into a Pixie tool

You are downloading a dataset from an arbitrary HTTPS URL into a named Pixie tool's `data/datasets/<id>/files/` folder. Handles CSV, Parquet, JSON, JSONL, HDF5, NPZ, NPY, plain files, and archives (`.zip`, `.tar`, `.tar.gz`, `.tar.bz2`, `.tar.xz`, `.7z`). Resume on partial download, sha256 verification, safe extraction, licence detection.

## Routing check (do this first)

- If the host is `kaggle.com`, switch to `fetch-dataset-from-kaggle`.
- If the host is `huggingface.co` (datasets), switch to `fetch-dataset-from-huggingface`.
- If the source is a Git repo URL, switch to `add-tool-from-repo` (it's a code repo, not a dataset).
- If the URL is `file://` or a local path, switch to `import-dataset-from-local`.
- If the user did not name a Pixie tool to receive the dataset, ask which one. Refuse if the named tool does not exist.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

- `.build/RESEARCH_dataset_import.md` §1 (folder layout + manifest), §4 (URL flow), §6 (bundled hooks), §7 (safe extraction)

## Precheck refusals

Refuse cleanly if any apply:

- Tool does not exist at `tools/<tool_id>/`.
- URL is `http://` and `--allow-insecure` is not set.
- `Content-Length` > 5 GB without `--max-size <GB>`.
- Provided `--sha256` does not match the downloaded bytes.
- Archive fails `safe_extract` (path traversal, symlinks, hard links).
- Archive contains executables (`.exe`/`.bat`/`.sh`/`.ps1`) without `--allow-scripts`.
- Uncompressed size > 2× the size limit (zip-bomb red flag).

## Steps

### 1. Confirm tool target

If invoked without a tool argument, ask which tool. Validate the tool exists at `tools/<tool_id>/`.

### 2. Validate URL

Require `https://` by default. `http://` allowed only with `--allow-insecure`. Reject `file://` (use `import-dataset-from-local`).

### 3. Sniff size + content type

```bash
curl -sIL "<url>"
```

Read `Content-Length`, `Content-Type`, `Accept-Ranges`. If HEAD is refused, do a GET-with-cancel to capture headers. Apply the size gate: > 100 MB → confirm; > 5 GB → refuse unless `--max-size <GB>`.

### 4. Check for special URL schemes (bundled hooks)

Per RESEARCH §6, the skill recognises pseudo-URLs that dispatch to bundled fetchers:

- `sklearn://<name>` → `sklearn.datasets.fetch_<name>` (requires `scikit-learn` in tool venv).
- `torchvision://<name>` → `torchvision.datasets.<Cls>` (requires `torchvision`).
- `torchaudio://<name>` → `torchaudio.datasets.<Cls>` (requires `torchaudio`).
- `nltk://<name>` → `nltk.download(<name>)` (requires `nltk`).

If a pseudo-URL is used, add the corresponding library to a `dataset-fetch-<source>` dependency group in `tools/<tool_id>/pyproject.toml`, run `uv sync`, then call the hook.

### 5. Cache lookup

Compute cache key `sha256(canonical_url)`. If `~/.cache/pixie/fetchers/<sha8>/` exists and is complete, hard-link or symlink files into the tool's `data/datasets/<id>/files/` and skip download.

### 6. Stream-download into the Pixie cache work area

```bash
uv run python -m pixie.scaffold.dataset_url_fetch <url> ~/.cache/pixie/fetchers/work/<sha8>.part
```

Helper uses `httpx.AsyncClient(follow_redirects=True, timeout=Timeout(connect=10, read=None))`, streams to `.part`, resumes on `Accept-Ranges: bytes`, computes sha256 incrementally, reports progress every 1 MB or 5%.

### 7. Verify checksum

If the user passed `--sha256 <hex>`, compare to the computed digest. On mismatch, delete the file and abort with both values printed.

### 8. Detect format

Detection order: URL extension → HTTP `Content-Type` → magic-byte sniff on first 512 bytes → `binary` default.

### 9. Safe-extract (if archive)

For `.zip` / `.tar*` / `.7z`:

- Inspect members without extracting. Reject path traversal, symlinks, hard links, executables (unless `--allow-scripts`). Strip `__macosx/`. Refuse if uncompressed > 2× the size limit.
- Extract into a tempdir; move atomically into `tools/<tool_id>/data/datasets/<dataset_id>/files/`.
- Discard the original archive (sha256 is preserved in manifest).

For non-archives: move into `files/<derived-name>` (last path segment of URL, query stripped; default `data.<ext>` if unclear).

### 10. Sniff schema and licence

For each CSV/Parquet/JSONL, peek the header to populate `columns` + `row_count`. For licence: capture `Link: <...>; rel="license"` header if present; map known hosts (data.gov.uk → OGL, figshare → user-supplied); otherwise set `licence: "unknown — supplied by user via --licence"` and prompt.

### 11. Write the manifest and ancillary files

- `manifest.json` per RESEARCH §1.4 with `source: "url"`, `source_url`, `fetched_at`, `checksum`, `licence`, `licence_spdx`, `total_size_bytes`, `files[]`, optional `columns`/`row_count`.
- `README.md`, `LICENSE.txt`, `.pixie-fetched` (atomicity marker). `CITATIONS.bib` only if user supplied `--cite "@article{...}"`.

### 12. Update the tool README

Append a `## Datasets` section listing this dataset id, the URL, the licence, the fetch timestamp, and the sha256.

### 13. Offer to regenerate reference fixtures

If `tools/<tool_id>/reference/` exists, ask whether to capture fresh `(inputs, expected_outputs)` pairs using this dataset. Do not auto-invoke.

### 14. Validator handoff (mandatory final step)

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
I can't fetch this URL because <one-sentence reason>.

The URL fetcher is constrained to:
- Tool must exist under tools/<tool_id>/
- HTTPS by default (--allow-insecure to permit http)
- Compressed size ≤ 5 GB (raise with --max-size)
- Archive must pass safe_extract (no path traversal, no symlinks, no executables)
- If --sha256 is provided, it must match

Resolve the blocker and re-invoke me.
```

## Do NOT

- Do NOT execute downloaded scripts. Refuse `.exe`/`.sh`/`.bat`/`.ps1` members unless `--allow-scripts`.
- Do NOT follow `file://` URLs — use `import-dataset-from-local` instead.
- Do NOT write outside `tools/<tool_id>/data/datasets/<dataset_id>/`.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
- Do NOT bind to `0.0.0.0`; do NOT add authentication; do NOT add Docker.
- Do NOT skip checksum verification when `--sha256` is supplied.
- Do NOT auto-extract archives that exceed 2× the size limit (zip-bomb guard).
