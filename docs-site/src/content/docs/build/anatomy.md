---
title: Tool anatomy
description: The four files that make a Pixie tool, and what each one does.
sidebar:
  order: 1
---

A Pixie tool is a folder under `tools/`. Four files are required:

```text
tools/my-tool/
├── tool.json        # schema: inputs, outputs, layout, secrets, metadata
├── pyproject.toml   # uv project: name, version, dependencies
├── main.py          # FastAPI app: /schema, /healthz, /run, optional /stream
└── .venv/           # built by `uv sync`, never committed
```

Optional:

```text
├── README.md        # human-readable description
├── data/            # the tool's persistent state (Pixie does not touch)
├── .env             # secrets, written via the masked UI
└── reference/       # opt-in: known inputs + expected outputs for check 12
```

If any required file is missing the validator's check 1 fails.

## `tool.json`

The schema. Read [tool.json reference](/Pixie/build/tool-json/) for every
field. Minimum viable:

```json
{
  "id": "my-tool",
  "name": "My tool",
  "inputs": [
    {"key": "x", "type": "number", "label": "X", "default": 1}
  ],
  "outputs": [
    {"key": "y", "type": "number", "label": "Y"}
  ]
}
```

Required: `id`, `name`, `inputs`, `outputs`. Everything else has sensible
defaults — see the [reference](/Pixie/build/tool-json/).

## `pyproject.toml`

Pixie's validator requires `fastapi`, `uvicorn`, and `python-dotenv` to be
declared. Beyond that, list whatever your tool actually imports:

```toml
[project]
name = "my-tool"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.32",
    "python-dotenv>=1.0",
    "numpy>=1.26",   # whatever your tool needs
]
```

Don't add dependencies your tool doesn't use — bloated venvs spawn slower
and waste disk. The `lint-tool` skill flags this.

You can keep heavy optional dependencies in groups so the validator's
`uv sync` is cheap:

```toml
[project.optional-dependencies]
runtime = ["torch>=2", "torchvision>=0.15"]
```

Then on machines that have the GPU stack: `uv sync --extra runtime`.
Tools that ship with optional groups should provide a CPU fallback so the
basic `uv sync` is enough to pass validation.

## `main.py`

A FastAPI app that exposes four endpoints (one optional):

```python
from contextlib import asynccontextmanager
import argparse
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# 1. Define the request and response shapes (Pydantic mirrors tool.json)
class RunInput(BaseModel):
    x: float

class RunOutput(BaseModel):
    y: dict

# 2. Build the app
app = FastAPI()

@app.get("/schema")
async def schema():
    # Return the on-disk tool.json verbatim so the validator's check 7 passes
    import json, pathlib
    return json.loads((pathlib.Path(__file__).parent / "tool.json").read_text())

@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.post("/run")
async def run(body: RunInput) -> dict:
    return {"y": {"value": body.x * 2}}

# 3. Make it executable
if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
```

That's a complete, valid Pixie tool. Run `uv sync` in the folder, then
`uv run pixie validate my-tool` from the repo root — you should get an
all-green report.

## What you don't write

- No auth, no CORS, no rate limiting — Pixie talks to your tool over
  localhost only.
- No logging configuration — `uvicorn` does the right thing.
- No frontend code — the dashboard renders inputs and outputs from
  `tool.json`.
- No database, no caching layer, no queueing — pick a tool format that
  doesn't need them. (If you do need state, write to `data/` and read it
  back.)
- No `/version`, no `/about`, no `/docs` — `tool.json` is the only contract.

## Lifecycle

- Spawn: `cd tools/my-tool && .venv/bin/python main.py --port <port>`
- Health: `GET /healthz` → `{"ok": true}`
- Schema match: `GET /schema` → parsed `tool.json`
- Run: `POST /run` with body → JSON outputs
- Optional stream: `GET /stream?run_id=<id>` → SSE events
- Optional cancel: `POST /cancel?run_id=<id>`
- Shutdown: SIGTERM, then SIGKILL after 5 s

See [Runtime & subprocesses](/Pixie/concepts/runtime/) for the full
lifecycle and how to debug each phase.

## Next

- [tool.json reference](/Pixie/build/tool-json/) — every field, every
  default.
- [HTTP contract](/Pixie/build/http-contract/) — request/response shapes
  for each endpoint.
- [Input types](/Pixie/build/inputs/) — all 25 types with examples.
- [Output types](/Pixie/build/outputs/) — all 39 types with examples.
- [Tool patterns](/Pixie/build/patterns/) — pure-function, stateful, and
  LLM-wrapping templates.
