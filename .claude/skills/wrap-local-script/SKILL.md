---
name: wrap-local-script
description: Wraps a local .py file (loose on disk) as a Pixie tool - generates tool.json and FastAPI main.py then validates. Use when the user gives a .py path and asks to wrap, turn, or convert it. Do NOT use for .ipynb (add-tool-from-notebook), Git URL (add-tool-from-repo), or a .py importing streamlit/gradio.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Wrap a local Python script as a Pixie tool

You are wrapping a single existing `.py` file (sitting loose on disk, not in a Git repo) as a Pixie tool. Pixie tools are FastAPI subprocesses bound to `127.0.0.1` exposing `/schema`, `/healthz`, `/run`, and optionally `/stream` and `/cancel`.

## Routing check (do this first)

- If the user gave a Git URL, stop and tell them you are switching to `add-tool-from-repo`.
- If the user is only describing intent without pointing at an actual file path, stop and switch to `add-tool-from-description`.
- If a tool with the inferred ID already exists under `tools/`, ask whether to switch to `update-tool` or `fork-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

Read these canonical references first. Match their structure.

- `tools/example-compound-interest/tool.json`
- `tools/example-compound-interest/main.py`
- `tools/example-compound-interest/pyproject.toml`

## Steps

### 1. Read the user's script

`Read` the file at the path the user provided. Do not modify the original — every write in this skill goes into the new `tools/<tool_id>/` folder.

### 2. Identify the entrypoint

Use `Grep` to find functions in the script: `^def ` lines and any `if __name__ == "__main__"` block. Pick the entrypoint by priority:

1. A function the user named explicitly.
2. A function called `main`, `run`, or matching the script's filename stem.
3. The body of `if __name__ == "__main__"` — in that case, wrap the whole module as one function call.

If two or more functions look equally plausible, STOP and ask the user which one is the entrypoint. Do not guess silently.

### 3. Confirm input and output types with the user

Show the user the entrypoint signature plus any docstring, and ask them to confirm:

- Each parameter's Pixie input type (`text`, `number`, `slider`, `select`, `file`, etc.).
- The return value's Pixie output type (`number`, `text`, `table`, `chart_line`, `image`, etc.).

Skip this step only if the signature is fully type-annotated AND the docstring describes the return shape unambiguously.

### 4. Pick an ID and create the tool folder

ID is kebab-case, sanitised to `[a-z0-9-]`, usually derived from the script filename stem. From the repo root:

```bash
mkdir -p tools/<tool_id>
```

### 5. Copy the script into the new tool folder

```bash
cp "<user's script path>" tools/<tool_id>/_script.py
```

On Windows PowerShell: `Copy-Item "<path>" tools/<tool_id>/_script.py`.

Never modify the original file. The copy under `_script.py` is what `main.py` imports.

### 6. Write `tool.json`

Use the confirmed inputs and outputs. Required fields: `id`, `name`, `inputs`, `outputs`. Default `layout` to `"form"`. If the script reads any API keys from environment variables, declare them under `secrets`.

### 7. Write `pyproject.toml`

Include `fastapi`, `uvicorn`, `python-dotenv` plus exactly the third-party imports the script uses. `Grep` the script for `^import ` and `^from ` lines, and add anything that isn't a stdlib module. Never invent dependencies. Pin `requires-python = ">=3.12"`.

### 8. Write `main.py`

A thin wrapper that imports the copied script and calls the entrypoint:

- `from _script import <entrypoint>`
- A Pydantic `RunInput` model matching the inputs in `tool.json`.
- `GET /schema` returns the parsed `tool.json`.
- `GET /healthz` returns `{"ok": true}`.
- `POST /run` calls the entrypoint and wraps the return in the output shape declared in `tool.json`.
- Bind `127.0.0.1`, read `--port` from `argv`, load `.env` via `python-dotenv`.

Hard rules:

- Never modify `_script.py` after copying. If the script needs changes, hand off to `update-tool` after validation passes.
- Never write secret values into `main.py` or `tool.json`.

### 9. Install dependencies

```bash
cd tools/<tool_id> && uv sync
```

`uv` handles the platform-specific venv layout — the skill does not need to care.

### 10. Validator handoff (mandatory final step)

1. From the repo root:
   ```bash
   uv run pixie validate <tool_id> --json
   ```
   Capture the full `ValidationReport` JSON from stdout.

2. Parse the JSON. Branch on the `overall` field:
   - `"pass"` — report success in one line. Surface any `warn` checks verbatim.
   - `"warn"` — report success and list every `warn` check verbatim with `name`, `message`, and `details`.
   - `"fail"` — DO NOT claim success. Output the entire JSON report verbatim in a fenced `json` block, then explain in plain language which checks failed. End with: "Would you like me to hand this off to the `debug-tool` skill?" Then stop.

3. Never paraphrase a failed report. The user must see the exact `name`, `status`, `message`, and `details` for every failing check.

4. Hard stop after two consecutive failed runs. Surface both reports and stop iterating.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't wrap this script as a Pixie tool because <one-sentence reason>.

Pixie tools are constrained to:
- Run as a local Python subprocess on 127.0.0.1
- Depend only on PyPI packages
- Need no GPU, no Docker, no database server, no system packages

The script needs <specific blocker — e.g., "a CUDA-only PyTorch build",
"a running PostgreSQL instance", "the `tkinter` GUI loop">, which is
outside the v1 Pixie envelope.

If you can isolate the pure-function part, I can wrap that instead.
```

## Do NOT

- Do NOT modify the user's original script file. Always copy first.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT add authentication, sessions, login, or multi-user concepts.
- Do NOT add Docker, container, or cloud-deployment files.
- Do NOT invent dependencies the script does not actually import.
- Do NOT write secret values into `main.py` or `tool.json`.
- Do NOT install system packages via apt/brew/choco.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
