---
name: add-tool-from-description
description: Generates a brand-new Pixie tool from a natural-language description - writes tool.json, pyproject.toml, main.py from scratch then validates. Use when the user asks to create, make, build, or generate a tool with NO artefact. Do NOT use given a Git URL, .py, .ipynb, .zip, Streamlit, Gradio, OpenAPI, or CLI binary.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Add a Pixie tool from a description

You are generating a new Pixie tool from scratch. Pixie tools are small FastAPI wrappers exposing `/schema`, `/healthz`, `/run`, and optionally `/stream`, bound to `127.0.0.1` only.

## Routing check (do this first)

- If the user gave a Git URL, stop and tell them you are switching to `add-tool-from-repo` instead.
- If the user wants to modify a tool that already exists under `tools/`, stop and switch to `update-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

Read the canonical example. Match its structure exactly.

- `tools/example-compound-interest/tool.json`
- `tools/example-compound-interest/main.py`
- `tools/example-compound-interest/pyproject.toml`

## Steps

### 1. Clarify the spec

Ask up to three questions, only if any of these are ambiguous:

- What are the inputs and their types? (text, number, slider, select, file, etc.)
- What are the outputs and their types? (number, table, chart_line, image, etc.)
- Is this conversational (`layout: "chat"`) or form-based (`layout: "form"`)?
- Does it need an external API key? If so, which environment variable?

If the spec is concrete, skip this step.

### 2. Pick a kebab-case ID and a human name

E.g. "convert currency" becomes `id: "currency-convert"`, `name: "Currency convert"`. Sanitise the ID to `[a-z0-9-]`.

### 3. Create the folder

From the repo root:

```bash
mkdir -p tools/<tool_id>
```

### 4. Write `tool.json`

Provide full input and output schemas with required fields per type. Declare any required environment variables under `secrets` — Pixie's per-tool settings UI will collect them and write to `tools/<tool_id>/.env`.

### 5. Write `pyproject.toml`

Default dependencies: `fastapi`, `uvicorn`, `python-dotenv`. Add only what the tool genuinely needs (e.g. `httpx` for an HTTP call, `Pillow` for image processing, `anthropic` for LLM wrapping). Pin `requires-python = ">=3.12"`.

### 6. Write `main.py`

Pick one of the three templates below based on the tool's shape. All three bind `127.0.0.1`, read `--port` from `argv`, and load `.env` via `python-dotenv`.

#### Template A — pure-function tool

For deterministic compute (maths, formatting, conversion, parsing).

```python
from pathlib import Path
import argparse
import json

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

load_dotenv()
app = FastAPI()
TOOL_JSON = json.loads((Path(__file__).parent / "tool.json").read_text())


class RunInput(BaseModel):
    pass  # one field per input declared in tool.json


@app.get("/schema")
def schema() -> dict:
    return TOOL_JSON


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/run")
def run(payload: RunInput) -> dict:
    return {"result": {"value": 0}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
```

#### Template B — stateful tool

For tools that persist a small amount of state between runs. State lives under `tools/<tool_id>/data/` — Pixie never touches this folder. Use Template A as the base and add these pieces near the top:

```python
TOOL_DIR = Path(__file__).parent
DATA_DIR = TOOL_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
STATE_PATH = DATA_DIR / "state.json"


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2))
```

Then in `run()`, call `state = load_state()`, mutate, and `save_state(state)` before returning.

#### Template C — LLM-wrapping tool

For tools that call a hosted LLM. The API key is the user's own, loaded from `tools/<tool_id>/.env`. Pixie never injects keys; the user sets the key via the per-tool secrets UI. Start from Template A, add `import os` and `from fastapi import HTTPException`, then replace `run()`:

```python
@app.post("/run")
def run(payload: RunInput) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="ANTHROPIC_API_KEY is not set. Add it under this tool's settings in Pixie.",
        )
    response_text = f"(stub) prompt was: {payload.prompt}"
    return {"reply": {"value": response_text}}
```

The matching `tool.json` must declare the secret:

```json
"secrets": [
  {"key": "ANTHROPIC_API_KEY", "description": "Your Anthropic API key", "required": true}
]
```

Never hardcode keys, never log them, never echo their values back to the user.

### 7. Install dependencies

```bash
cd tools/<tool_id> && uv sync
```

`uv` handles the venv layout per platform (`Scripts/python.exe` on Windows vs `bin/python` on POSIX).

### 8. Validator handoff (mandatory final step)

1. From the repo root:
   ```bash
   uv run pixie validate <tool_id> --json
   ```
   Capture the JSON stdout.

2. Parse and branch on `overall`:
   - `"pass"` — one-line success summary. Surface any `warn` checks verbatim.
   - `"warn"` — success summary plus every warning verbatim (`name`, `message`, `details`).
   - `"fail"` — surface the entire JSON report in a fenced `json` block, explain the failing checks in plain language, end with: "Would you like me to hand this off to the `debug-tool` skill?" Stop.

3. Never paraphrase a failed report.

4. Hard stop after two consecutive failures.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't build that as a Pixie tool because <one-sentence reason>. Pixie tools run as
local Python subprocesses on 127.0.0.1, depend only on PyPI packages, and need no GPU,
Docker, database server, or system packages. If we can reduce the scope to a single
function that takes simple inputs and returns simple outputs, I can build that instead.
```

## Do NOT

- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT add authentication, sessions, login, or multi-user concepts to the tool.
- Do NOT add Docker, container, or cloud-deployment files.
- Do NOT hardcode API keys; always load from `os.environ` after `load_dotenv()`.
- Do NOT log secret values; never echo a saved key back to the user.
- Do NOT add telemetry or analytics from inside the tool.
- Do NOT add a JavaScript framework, Node build step, or SPA.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
