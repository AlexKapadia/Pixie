---
title: Tool patterns
description: Three templates that cover most tools — pure function, stateful, LLM-wrapping.
sidebar:
  order: 9
---

import { Tabs, TabItem } from "@astrojs/starlight/components";

Almost every Pixie tool fits into one of three shapes. Start from the
nearest template, then specialise.

## Pure function

The most common shape. `/run` is stateless — same inputs always produce
the same outputs. No model loading, no warm state to maintain.

```python
# tools/compound-interest/main.py
import argparse, json, pathlib
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

class RunInput(BaseModel):
    principal: float
    annual_rate: float
    years: int
    compounding: int = 12
    monthly_contribution: float = 0

app = FastAPI()
HERE = pathlib.Path(__file__).parent
TOOL_JSON = json.loads((HERE / "tool.json").read_text())

@app.get("/schema")
async def schema(): return TOOL_JSON

@app.get("/healthz")
async def healthz(): return {"ok": True}

@app.post("/run")
async def run(body: RunInput) -> dict:
    r = body.annual_rate / 100 / body.compounding
    n = body.years * body.compounding
    fv = body.principal * (1 + r) ** n + body.monthly_contribution * (((1 + r) ** n - 1) / r) * (body.compounding / 12)

    return {
        "final_value": {"value": fv, "format": "currency", "precision": 2},
        "growth_chart": _growth_chart(body),
        "yearly_breakdown": _yearly_table(body),
    }

if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
```

This template covers calculators, transformers, analytic tools, and
anything else that's deterministic and cheap.

## Stateful with a loaded model

For tools that load a heavy model at startup (Whisper, Vision Transformer,
BERTopic) and reuse it across requests. The model lives in module state;
warm-keep amortises load time.

```python
# tools/whisper-transcription/main.py
import argparse, base64, io
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel
import faster_whisper

_model: faster_whisper.WhisperModel | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model
    _model = faster_whisper.WhisperModel("tiny", device="cpu", compute_type="int8")
    yield
    _model = None

app = FastAPI(lifespan=lifespan)

class RunInput(BaseModel):
    audio: str   # data URL
    language: str = "auto"

@app.post("/run")
async def run(body: RunInput) -> dict:
    _, b64 = body.audio.split(",", 1)
    wav = io.BytesIO(base64.b64decode(b64))

    segments, _info = _model.transcribe(wav, language=None if body.language == "auto" else body.language)
    rows = [{"start": s.start, "end": s.end, "text": s.text} for s in segments]
    transcript = " ".join(r["text"] for r in rows)

    return {
        "transcript": {"value": transcript},
        "segments": {"columns": [...], "rows": rows},
    }

# /schema, /healthz, __main__ block omitted
```

Set `concurrent: false` in `tool.json` if the model isn't thread-safe.
Increase `warm_keep_seconds` so the cold-start doesn't repeat between
clicks.

## LLM-wrapping (with offline fallback)

For tools that route through an external LLM when an API key is present
and fall back to a local implementation when it isn't. This pattern keeps
the tool **always validatable** — the validator's sample run uses the
fallback so no key is required.

```python
# tools/llm-tool-use-agent/main.py
import os, json, pathlib
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
HAS_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))

app = FastAPI()

class RunInput(BaseModel):
    messages: list[dict]
    tools: list[str] = ["calc"]

@app.post("/run")
async def run(body: RunInput) -> dict:
    if HAS_KEY:
        reply, tool_log = await _route_through_claude(body)
    else:
        reply, tool_log = _local_agent_loop(body)

    return {
        "reply":    {"value": reply},
        "tool_log": {"lines": tool_log},
    }

async def _route_through_claude(body):
    import anthropic
    client = anthropic.AsyncAnthropic()
    rsp = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=body.messages,
        # ... tool definitions
    )
    return rsp.content[0].text, [...]

def _local_agent_loop(body):
    # deterministic intent matcher with calculator and a stub search
    ...
    return "...", [{"level": "info", "message": "Used local fallback", "t": "..."}]
```

Declare the optional secret in `tool.json`:

```json
{
  "secrets": [
    {"key": "ANTHROPIC_API_KEY", "description": "Optional. Enables Claude routing.", "required": false}
  ]
}
```

The pattern in action: [`rag-with-citations`](/Pixie/cookbook/rag-with-citations/),
[`llm-tool-use-agent`](/Pixie/cookbook/llm-tool-use-agent/), and
[`bertopic-modelling`](/Pixie/cookbook/bertopic-modelling/) all ship
graceful fallbacks for the same reason.

## Honourable mentions

### Heavy native deps with a numpy fallback

`live-mlp-training` ships a pure-numpy backprop loop that runs without
PyTorch so the validator passes on machines without GPUs. When the
optional `runtime` group is installed (`uv sync --extra runtime`), it
swaps in the torch path. The contract is the same; only the speed differs.

### Multipart upload for large files

For tools that need to accept files bigger than a few MB, declare
`input_transport: "multipart"` in `tool.json`. The renderer switches the
form encoding, and your `/run` becomes:

```python
from fastapi import UploadFile, Form

@app.post("/run")
async def run(audio: UploadFile, language: str = Form("auto"), run_id: str = Form(...)):
    data = await audio.read()
    ...
```

### Streaming chart updates

See [Streaming outputs](/Pixie/build/streaming/) — same pattern as
streaming text, but the `value` is a partial `{x, series}` delta.

## Anti-patterns

- **Writing a Flask app instead of FastAPI.** The launcher specifically
  expects FastAPI's lifespan/uvicorn shape. Don't.
- **Importing heavy deps at module level when the validator doesn't need
  them.** Use lazy imports inside `/run` so check 5 (`venv_functional`)
  is cheap.
- **Returning huge base64 blobs inline.** If a value exceeds 64 KiB,
  spill it to `os.environ["PIXIE_RUN_ARTEFACTS_DIR"] + "/<filename>"`
  and return `{"filename": "...", "data": "...", "mime_type": "..."}` —
  Pixie picks it up.
- **Reading config from a hardcoded path.** Use `pathlib.Path(__file__).parent`
  — the launcher sets `cwd` to the tool folder but other libs may not
  respect that.
- **Calling `print()` in `/run`.** Use `logging` so the
  `SecretMaskingFilter` can scrub secrets.
