---
name: add-tool-from-repo
description: Clones a Git repository and wraps its entrypoint as a Pixie tool - generates tool.json and FastAPI main.py then validates. Use when the user gives a Git URL and asks to add, clone, or wrap a repo. Do NOT use for .zip (import-tool), .py (wrap-local-script), .ipynb (add-tool-from-notebook), or prose (add-tool-from-description).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Add a Pixie tool from a repository

You are integrating an external repository as a Pixie tool. Pixie tools are small, single-purpose Python wrappers — a FastAPI app exposing `/schema`, `/healthz`, `/run`, optionally `/stream` and `/cancel`, bound to `127.0.0.1` only.

## Routing check (do this first)

- If the user did NOT give a Git URL, stop and tell them you are switching to `add-tool-from-description` instead.
- If a tool with the inferred ID already exists under `tools/`, ask whether to switch to `update-tool` instead.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

Read these canonical references first. Match their structure — do not invent a different layout from training data.

- `tools/example-compound-interest/tool.json`
- `tools/example-compound-interest/main.py`
- `tools/example-compound-interest/pyproject.toml`

## Steps

### 1. Clone the repository to a temp location

Use the `Bash` tool:

```bash
git clone --depth=1 <url> /tmp/pixie-import-<short-hash>
```

On Windows, `$env:TEMP` is the temp root — use `$env:TEMP/pixie-import-<short-hash>` if running PowerShell. Never clone directly into `tools/<id>/` — the repo's own files would collide with Pixie's wrapper.

### 2. Inspect the repo

- `Read` the README (`README.md`, `README.rst`, or `README`).
- `Glob` for `pyproject.toml`, `setup.py`, `setup.cfg`, `requirements.txt` to discover declared dependencies.
- `Grep` for likely entrypoints: `^def main`, `^def run`, `if __name__ == "__main__"`, `app = FastAPI`, `@click.command`.
- `Read` the top-level module the README highlights.

### 3. Decide if Pixie can host this

Refuse cleanly (see refusal templates below) if any of these apply:

- Requires a GPU for inference with no CPU fallback.
- Requires Docker or docker-compose.
- Requires a database server (Postgres, MySQL, Redis-as-server). SQLite is fine.
- Is a full web application (Django site, Rails app, SPA) rather than a function or library.
- Requires system packages outside PyPI (apt / brew / choco / native binaries).
- Requires Python earlier than 3.12.
- Requires multi-user authentication or login flows for Pixie itself.

If only part of the repo is unsuitable, offer to wrap the usable submodule instead.

### 4. Pick an ID and create the tool folder

ID is kebab-case derived from the repo name, sanitised to `[a-z0-9-]`. From the repo root:

```bash
mkdir -p tools/<tool_id>
```

### 5. Write `tool.json`

Infer `inputs` and `outputs` from the entrypoint signature plus README behaviour. If types are ambiguous, STOP and ask the user to confirm before writing. Do not guess silently. Required fields: `id`, `name`, `inputs`, `outputs`. Default `layout` to `"form"` unless the repo is clearly conversational.

If the upstream code reads any API keys from environment variables, declare them under `secrets` so Pixie's settings UI can collect them — never write secret values into the tool.

### 6. Write `pyproject.toml`

Include `fastapi`, `uvicorn`, `python-dotenv`, plus exactly the dependencies the repo declares. Never invent dependencies. Pin `requires-python = ">=3.12"` unless the repo's metadata forbids it.

### 7. Write `main.py`

Wrap the repo's entrypoint as a FastAPI app exposing:

- `GET /schema` — returns the `tool.json` contents
- `GET /healthz` — returns `{"ok": true}`
- `POST /run` — takes the input JSON, returns the output JSON
- `GET /stream?run_id=<id>` — only if a streaming output is declared
- `POST /cancel?run_id=<id>` — only if cancellation is supported

Bind to `127.0.0.1`. Read `--port` from `argv`. Load `.env` via `python-dotenv`. Read API keys from `os.environ`.

Hard rules:

- Never modify the cloned repo's source. Wrap from the outside (import via path, or copy needed files into `tools/<tool_id>/_vendor/` if the licence allows).
- Never write API keys or secret values into `main.py`. Declare in `tool.json` under `secrets`; load via `os.environ`.
- If the entrypoint is ambiguous between two plausible functions, stop and ask.

### 8. Install dependencies

From the repo root:

```bash
cd tools/<tool_id> && uv sync
```

`uv` handles the platform-specific venv layout (`tools/<tool_id>/.venv/Scripts/python.exe` on Windows, `tools/<tool_id>/.venv/bin/python` on POSIX). The skill does not need to care.

### 9. Validator handoff (mandatory final step)

1. From the repo root, run:
   ```bash
   uv run pixie validate <tool_id> --json
   ```
   The `--json` flag prints the full `ValidationReport` JSON to stdout. Capture it.

2. Parse the JSON. Branch on the `overall` field:
   - `"pass"` — report success in one line (e.g., "Tool `<tool_id>` validated successfully — all checks passed."). Surface any `warn` checks verbatim.
   - `"warn"` — report success and list every check where `status == "warn"` verbatim, with the `name`, `message`, and `details`.
   - `"fail"` — DO NOT claim success. Output the entire JSON report verbatim in a fenced `json` block, then explain in plain language which checks failed and what the `message` and `details` mean. End with: "Would you like me to hand this off to the `debug-tool` skill?" Then stop.

3. Never paraphrase a failed report. The user must see the exact `name`, `status`, `message`, and `details` for every failing check.

4. Hard stop after two consecutive failed runs. Surface both reports and stop iterating.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't integrate this as a Pixie tool because <one-sentence reason>.

Pixie tools are constrained to:
- Run as a local Python subprocess on 127.0.0.1
- Depend only on PyPI packages
- Need no GPU, no Docker, no database server, no system packages

The repo you gave me requires <specific blocker>, which is outside the v1 Pixie envelope.

If you can point me at a smaller part of the project that takes simple inputs and returns
simple outputs, I can wrap that instead.
```

## Do NOT

- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT add authentication, sessions, login, or multi-user concepts.
- Do NOT add Docker, container, or cloud-deployment files.
- Do NOT invent dependencies the upstream repo did not declare.
- Do NOT write secret values into `main.py` or `tool.json`.
- Do NOT modify the cloned repo's source files.
- Do NOT add telemetry, analytics, or remote reporting from the tool.
- Do NOT install system packages via apt/brew/choco.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
