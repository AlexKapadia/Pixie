---
name: convert-gradio-app
description: Converts a Gradio app into a Pixie tool, mapping gr.Interface or gr.Blocks components onto tool.json inputs and outputs then validating. Use when the user mentions Gradio, gr.Interface, gr.Blocks, or .py importing gradio and asks to convert, port, or wrap it. Do NOT use for Streamlit (convert-streamlit-app) or plain .py (wrap-local-script).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Convert a Gradio app into a Pixie tool

You are converting a single-file Gradio app into a Pixie tool. Gradio's `gr.Interface(fn=..., inputs=[...], outputs=[...])` shape maps almost one-to-one onto Pixie's tool contract. For `gr.Blocks`, try the simple sub-case; refuse otherwise.

## Routing check (do this first)

- If the user gave a Git URL, switch to `add-tool-from-repo`.
- If the user gave a plain `.py` file with no Gradio imports, switch to `wrap-local-script`.
- If the user gave a Streamlit script, switch to `convert-streamlit-app`.
- If the user gave a notebook, switch to `add-tool-from-notebook`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

Read these canonical references first:

- `tools/example-compound-interest/tool.json`
- `tools/example-compound-interest/main.py`
- `tools/example-compound-interest/pyproject.toml`

## Step 1. Read the Gradio script

`Read` the file at the path the user supplied. Do not modify it.

## Step 2. Decide which Gradio shape this is

`Grep` for the entry point:

```
grep -nE "gr\.Interface\(|gr\.Blocks\(|gr\.ChatInterface\(" <path>
```

Cases:

- **`gr.Interface(fn=..., inputs=..., outputs=...)`** — the easy case. Continue.
- **`gr.ChatInterface(fn=...)`** — wrap as a `layout: "chat"` tool with `text` input and `markdown` output. Continue.
- **`gr.Blocks(...)`** — only continue if the Blocks body is a single straight-line list of components feeding into one event handler (one `.click(fn=..., inputs=[...], outputs=[...])`). If there are multiple event handlers, conditional UI, tabs, or state, refuse (see refusal block).

## Step 3. Map Gradio components

Inputs:

| Gradio | Pixie input |
|---|---|
| `gr.Textbox(lines=1)` | `text` |
| `gr.Textbox(lines>1)` / `gr.TextArea` | `textarea` |
| `gr.Number(minimum=,maximum=,step=)` | `number` |
| `gr.Slider(...)` | `slider` |
| `gr.Dropdown(choices=...)` | `select` (or `multiselect` if `multiselect=True`) |
| `gr.Radio(choices=...)` | `radio` |
| `gr.Checkbox()` | `checkbox` |
| `gr.CheckboxGroup(choices=...)` | `multiselect` |
| `gr.Image(...)` / `gr.Audio()` / `gr.File()` | `image` / `audio` / `file` |
| `gr.ColorPicker()` / `gr.Code(...)` | `colour` / `code` |
| `gr.DataFrame()` / `gr.JSON()` | `table` / `json` |
| `gr.Video()` as input | REFUSE — not currently supported |

Outputs:

| Gradio | Pixie output |
|---|---|
| `gr.Textbox` / `gr.Text` / `gr.Label` | `text` |
| `gr.Markdown` / `gr.HTML` / `gr.JSON` | `markdown` (HTML / JSON pretty-printed) |
| `gr.Number` | `number` |
| `gr.Image` / `gr.Audio` / `gr.Video` / `gr.File` | `image` / `audio` / `video` / `file` |
| `gr.DataFrame` | `table` |
| `gr.LinePlot` / `gr.BarPlot` / `gr.ScatterPlot` | `chart_line` / `chart_bar` / `chart_scatter` |
| `gr.Code` | `code` |

For each component, derive a kebab-case `key` from the `label=` argument (or the assigned variable name). Use the original `label` for the Pixie `label`.

## Step 4. Pick an ID and create the folder

```bash
mkdir -p tools/<tool_id>
```

## Step 5. Write `tool.json`

Use the inferred inputs and outputs. If the script reads any `os.environ.get(...)` for an API key, declare it under `secrets`.

For `gr.ChatInterface`, set `layout: "chat"`, declare one input `prompt: text` and one output `reply: markdown`.

## Step 6. Write `pyproject.toml`

Default deps: `fastapi`, `uvicorn`, `python-dotenv`. Add every non-stdlib import from the original script EXCEPT `gradio`. Pin `requires-python = ">=3.12"`.

## Step 7. Copy the script and write `main.py`

Copy the original script:

```bash
cp "<user's script path>" tools/<tool_id>/_gradio_app.py
```

Write `main.py` that stubs `gradio` in `sys.modules` BEFORE importing the script, imports the `fn` callable, and exposes it via `/run`. Do NOT call `.launch()` — Pixie owns the port.

Pattern:

```python
import sys, json, types, argparse
from pathlib import Path
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
TOOL_JSON = json.loads((Path(__file__).parent / "tool.json").read_text())
app = FastAPI()

_gr = types.ModuleType("gradio")
class _StubComponent:
    def __init__(self, *a, **kw): pass
for name in ("Textbox","Number","Slider","Dropdown","Radio","Checkbox",
             "Image","Audio","Video","File","ColorPicker","Code","DataFrame",
             "JSON","Markdown","Label","HTML","LinePlot","BarPlot",
             "ScatterPlot","CheckboxGroup","ChatInterface","TextArea"):
    setattr(_gr, name, _StubComponent)
class _StubInterface:
    def __init__(self, fn=None, **kw): self.fn = fn
    def launch(self, *a, **kw): pass
_gr.Interface = _StubInterface
_gr.Blocks = _StubInterface
sys.modules["gradio"] = _gr
sys.modules["gr"] = _gr

from _gradio_app import *  # noqa
_iface = next((v for v in dict(globals()).values()
               if isinstance(v, _StubInterface) and v.fn), None)
USER_FN = _iface.fn if _iface else None

class RunInput(BaseModel): pass  # one field per input

@app.get("/schema")
def schema(): return TOOL_JSON
@app.get("/healthz")
def healthz(): return {"ok": True}

@app.post("/run")
def run(payload: RunInput):
    args = [getattr(payload, spec["key"]) for spec in TOOL_JSON["inputs"]]
    result = USER_FN(*args)
    if not isinstance(result, tuple): result = (result,)
    return {spec["key"]: {"value": v} for spec, v in zip(TOOL_JSON["outputs"], result)}

if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--port", type=int, required=True)
    uvicorn.run(app, host="127.0.0.1", port=p.parse_args().port, log_level="warning")
```

Tune output wrapping per output type — see the validator's `_OUTPUT_OBJECT_REQUIREMENTS` for required shapes (e.g., `chart_line` needs `{x, series}`).

## Step 8. Install dependencies

```bash
cd tools/<tool_id> && uv sync
```

## Step 9. Validator handoff (mandatory final step)

1. From the repo root:
   ```bash
   uv run pixie validate <tool_id> --json
   ```

2. Parse the JSON. Branch on `overall`:
   - `"pass"` — one-line success. Surface any `warn` checks verbatim.
   - `"warn"` — report success and list every `warn` check verbatim.
   - `"fail"` — DO NOT claim success. Output the entire JSON verbatim. End with: "Would you like me to hand this off to the `debug-tool` skill?" Stop.

3. Never paraphrase a failed report.

4. Hard stop after two consecutive failed runs.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't convert this Gradio app cleanly because it uses `gr.Blocks` with
<feature — e.g., "multiple event handlers", "gr.State", "conditional component visibility">.
That depends on Gradio's reactive event model, which Pixie tools (stateless
request/response) cannot reproduce.

If you can rewrite the core behaviour as a single `fn(inputs) -> outputs`
callable, I can wrap that with `add-tool-from-description`.
```

## Do NOT

- Do NOT bundle `gradio` as a runtime dependency. The stub replaces it.
- Do NOT call `.launch()` from `main.py` — Pixie owns the port.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT add authentication or multi-user concepts.
- Do NOT write secret values into `main.py` or `tool.json`.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
