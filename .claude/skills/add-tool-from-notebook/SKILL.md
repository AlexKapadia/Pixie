---
name: add-tool-from-notebook
description: Converts a Jupyter notebook (.ipynb) into a Pixie tool - extracts input/output cells, generates tool.json and FastAPI main.py, then validates. Use when the user gives a path to a .ipynb file and asks to add, wrap, convert, or import a notebook. Do NOT use for .py (wrap-local-script) or Streamlit (convert-streamlit-app).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Convert a Jupyter notebook into a Pixie tool

You are turning a `.ipynb` notebook into a Pixie tool. The notebook becomes a single FastAPI subprocess bound to `127.0.0.1` exposing `/schema`, `/healthz`, `/run`, and optionally `/stream`.

## Routing check (do this first)

- Trigger only when the user points at a path ending in `.ipynb`.
- If the path is a `.py` file, switch to `wrap-local-script`.
- If the user gave a Git URL, switch to `add-tool-from-repo`.
- If no file is mentioned at all, switch to `add-tool-from-description`.
- If a tool with the inferred ID already exists, ask whether to switch to `update-tool` or `fork-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Size guard

Inspect the notebook's cell count first:

```bash
uv run python -c "import json,sys; nb=json.load(open(sys.argv[1], encoding='utf-8')); print(len(nb.get('cells', [])))" "<notebook path>"
```

If the count exceeds 50, STOP and tell the user the notebook is too large to wrap cleanly — ask them to trim it to the cells that contain the function and its imports, then re-invoke this skill.

## Read before you act

Read these canonical references first. Match their structure.

- `tools/example-compound-interest/tool.json`
- `tools/example-compound-interest/main.py`
- `tools/example-compound-interest/pyproject.toml`

## Steps

### 1. Parse the notebook

Use `Read` on the `.ipynb` path. Jupyter notebooks are JSON; the `cells` array holds typed cells (`code`, `markdown`). Each `code` cell's `source` is a list of strings or a single string.

For deeper inspection use a one-liner:

```bash
uv run python -c "import json,sys; nb=json.load(open(sys.argv[1], encoding='utf-8')); [print('---',i,c['cell_type']); print(''.join(c['source']) if isinstance(c['source'],list) else c['source']) for i,c in enumerate(nb['cells'])]" "<notebook path>"
```

### 2. Confirm kernel and runtime

Check the notebook's `metadata.kernelspec.name`. Refuse cleanly if it is anything other than a Python kernel (`python3`, `python`, `ipython`). R, Julia, Bash, and other kernels are out of scope.

Also `Grep` the code cells for references to local artifacts that may not be reproducible — pickled files loaded via `pickle.load`, joblib dumps, cached `.npy` blobs, anything in `/tmp` or a hard-coded local path. If found, STOP and ask the user to provide those artifacts as files under `tools/<tool_id>/data/` explicitly. The skill does NOT silently shuttle them in.

### 3. Identify the entrypoint

Search the code cells for `def ` lines. Pick the entrypoint:

1. A function the user named explicitly.
2. A function called `main`, `run`, `predict`, or matching the notebook filename stem.
3. The single most prominent `def` with a clear signature and docstring.

If two or more functions look equally plausible, STOP and ask the user which is the entrypoint.

### 4. Confirm input and output types

Show the user the entrypoint signature plus any docstring, and ask them to confirm:

- Each parameter's Pixie input type (`text`, `number`, `slider`, `select`, `file`, etc.).
- The return value's Pixie output type (`number`, `text`, `table`, `chart_line`, `image`, etc.).

Skip only if the signature is fully type-annotated AND the docstring is unambiguous.

### 5. Pick an ID and create the tool folder

ID is kebab-case derived from the notebook filename stem, sanitised to `[a-z0-9-]`.

```bash
mkdir -p tools/<tool_id>
```

### 6. Extract imports and the entrypoint into `_notebook.py`

Concatenate, in this order:

1. All `import` and `from ... import ...` statements found across `code` cells (deduplicate, preserve order of first appearance).
2. Any top-level helper `def`s and constants that the entrypoint references.
3. The entrypoint function itself.

Write the result to `tools/<tool_id>/_notebook.py`. Do not include cell magics (`%matplotlib`, `!pip install`, `?help`). Do not include `display()`, `print` debug calls left over from exploration unless the entrypoint depends on them — usually it does not.

### 7. Write `tool.json`

Use the confirmed inputs and outputs. Required fields: `id`, `name`, `inputs`, `outputs`. Default `layout` to `"form"`. Declare any environment-variable API keys under `secrets`.

### 8. Write `pyproject.toml`

Include `fastapi`, `uvicorn`, `python-dotenv` plus exactly the third-party imports the notebook uses. Common notebook dependencies to map: `numpy`, `pandas`, `scikit-learn` (declared as `scikit-learn`, imported as `sklearn`), `matplotlib`, `pillow` (declared, imported as `PIL`), `requests`, `httpx`. Never invent dependencies. Pin `requires-python = ">=3.12"`.

### 9. Write `main.py`

A thin wrapper that imports `_notebook` and calls the entrypoint:

- `from _notebook import <entrypoint>`
- Pydantic `RunInput` model matching the inputs in `tool.json`.
- `GET /schema`, `GET /healthz`, `POST /run` as usual.
- Bind `127.0.0.1`, read `--port` from `argv`, load `.env` via `python-dotenv`.

### 10. Install dependencies

```bash
cd tools/<tool_id> && uv sync
```

### 11. Validator handoff (mandatory final step)

1. From the repo root:
   ```bash
   uv run pixie validate <tool_id> --json
   ```
   Capture the full `ValidationReport` JSON from stdout.

2. Parse the JSON. Branch on `overall`:
   - `"pass"` — report success in one line; surface any `warn` checks verbatim.
   - `"warn"` — report success and list every `warn` check verbatim.
   - `"fail"` — DO NOT claim success. Output the entire JSON report verbatim in a fenced `json` block, then explain the failing checks in plain language. End with: "Would you like me to hand this off to the `debug-tool` skill?" Then stop.

3. Never paraphrase a failed report.

4. Hard stop after two consecutive failed runs.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't convert this notebook to a Pixie tool because <one-sentence reason>.

Pixie tools are constrained to:
- Run as a local Python subprocess on 127.0.0.1
- Depend only on PyPI packages
- Need no GPU, no Docker, no database server, no system packages

The notebook needs <specific blocker — e.g., "the R kernel", "an unpickled
model file that isn't on disk", "a CUDA-only PyTorch build">, which is
outside the v1 Pixie envelope.

If you can isolate the pure-function part into a Python kernel cell, or
provide the missing artifact as a file under data/, I can wrap that.
```

## Do NOT

- Do NOT include cell magics, shell escapes, or `display()` calls in the extracted code.
- Do NOT silently include local pickle/joblib artifacts. Ask the user.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT add authentication, sessions, or multi-user concepts.
- Do NOT add Docker, container, or cloud-deployment files.
- Do NOT invent dependencies the notebook does not import.
- Do NOT write secret values into `main.py` or `tool.json`.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
