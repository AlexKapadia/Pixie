---
name: convert-streamlit-app
description: Converts a Streamlit app into a Pixie tool - maps st.* widgets to tool.json inputs and st.* outputs to partials. Single-form apps only; refuses multi-page or stateful ones. Use when the user mentions Streamlit, streamlit run, or .py importing streamlit. Do NOT use for Gradio (convert-gradio-app) or plain .py (wrap-local-script).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Convert a Streamlit app into a Pixie tool

You are converting a single-file Streamlit script into a Pixie tool. Streamlit's top-down rerun model does not generally map onto Pixie's request/response shape — but for simple "one form in, one set of outputs out" Streamlit apps, it is possible.

## Routing check (do this first)

- If the user gave a Git URL, switch to `add-tool-from-repo`.
- If the user gave a plain `.py` file with NO Streamlit imports, switch to `wrap-local-script`.
- If the user gave a notebook, switch to `add-tool-from-notebook`.
- If the user is describing a tool without any source file, switch to `add-tool-from-description`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

Read these canonical references first:

- `tools/example-compound-interest/tool.json`
- `tools/example-compound-interest/main.py`
- `tools/example-compound-interest/pyproject.toml`

## Step 1. Read the Streamlit script

`Read` the file at the path the user supplied. Do not modify it — every write here goes to the new `tools/<tool_id>/` folder.

## Step 2. Complexity check (refuse if too complex)

`Grep` the script for these patterns and count matches:

```
grep -cE "st\.session_state" <path>
grep -cE "st\.button\(" <path>
grep -cE "st\.tabs\(|st\.expander\(|st\.sidebar" <path>
grep -cE "pages/|multipage" <path>
```

Refuse cleanly (see refusal block) if ANY of these apply:

- Any `st.session_state` reference.
- More than 5 `st.button(` calls.
- Any `pages/` folder reference or multi-page app indicator.
- Any callback-based pattern (`on_click=`, `on_change=`).

These features depend on Streamlit's rerun loop, which Pixie's stateless `/run` cannot reproduce faithfully.

## Step 3. Extract inputs

`Grep` for Streamlit input widgets and map each to a Pixie input type:

| Streamlit | Pixie input type | Notes |
|---|---|---|
| `st.text_input(label, value=...)` | `text` | `default` ← `value` |
| `st.text_area(...)` | `textarea` | |
| `st.number_input(label, min_value=..., max_value=..., step=...)` | `number` | `min`/`max`/`step` map directly |
| `st.slider(label, min_value, max_value, value, step)` | `slider` | |
| `st.selectbox(label, options)` | `select` | Build `options` array of `{value, label}` |
| `st.multiselect(label, options)` | `multiselect` | |
| `st.checkbox(label)` | `checkbox` | |
| `st.radio(label, options)` | `radio` | |
| `st.date_input(label)` | `date` | |
| `st.time_input(label)` | `time` | |
| `st.file_uploader(label, type=...)` | `file` (or `image` / `audio` if `type` restricts) | |
| `st.color_picker(label)` | `colour` | |

Use the assigned variable name as the input `key` (kebab-case sanitised). Use the first positional `label` argument as the input `label`.

## Step 4. Extract outputs

`Grep` for Streamlit output calls and map each:

| Streamlit | Pixie output type |
|---|---|
| `st.write(...)` / `st.markdown(...)` | `markdown` |
| `st.text(...)` | `text` |
| `st.metric(...)` | `number` |
| `st.dataframe(...)` / `st.table(...)` | `table` |
| `st.line_chart(...)` | `chart_line` |
| `st.bar_chart(...)` | `chart_bar` |
| `st.area_chart(...)` | `chart_area` |
| `st.image(...)` | `image` |
| `st.audio(...)` | `audio` |
| `st.video(...)` | `video` |
| `st.json(...)` | `markdown` (render as fenced JSON) |
| `st.code(...)` | `code` |

If the script renders something that has no clean Pixie mapping (e.g., `st.pyplot`, `st.plotly_chart` with arbitrary figure), warn and ask the user how they want it rendered — most commonly as `image`.

## Step 5. Pick an ID and create the folder

```bash
mkdir -p tools/<tool_id>
```

## Step 6. Write `tool.json`

Use the inferred inputs and outputs. If the script imports `os.environ.get("SOMETHING_API_KEY")` or similar, declare it under `secrets`.

## Step 7. Write `pyproject.toml`

Default deps: `fastapi`, `uvicorn`, `python-dotenv`. Add every non-stdlib import from the original script EXCEPT `streamlit` (we stub it). Pin `requires-python = ">=3.12"`.

## Step 8. Copy the script and write `main.py` with an `st` stub

Copy the original script:

```bash
cp "<user's script path>" tools/<tool_id>/_streamlit_app.py
```

Then write `main.py` that injects a stub `streamlit` module into `sys.modules` BEFORE importing the script. The stub:

- Reads input values from the incoming `RunInput` payload (keyed by assignment name).
- Captures output calls (`st.write`, `st.line_chart`, etc.) into a dict that becomes the `/run` response.
- Does nothing for layout calls (`st.title`, `st.header`, `st.divider`, `st.columns`, `st.sidebar`).

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

def make_st_stub(inputs: dict, outputs: dict) -> types.ModuleType:
    st = types.ModuleType("streamlit")
    # one branch per st.* call used in the original script
    return st

class RunInput(BaseModel): pass  # one field per input

@app.get("/schema")
def schema(): return TOOL_JSON
@app.get("/healthz")
def healthz(): return {"ok": True}

@app.post("/run")
def run(payload: RunInput):
    outputs: dict = {}
    sys.modules["streamlit"] = make_st_stub(payload.model_dump(), outputs)
    from _streamlit_app import *  # noqa
    return outputs

if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--port", type=int, required=True)
    uvicorn.run(app, host="127.0.0.1", port=p.parse_args().port, log_level="warning")
```

Flesh out `make_st_stub` to handle every widget and renderer found in steps 3 and 4.

## Step 9. Install dependencies

```bash
cd tools/<tool_id> && uv sync
```

## Step 10. Validator handoff (mandatory final step)

1. From the repo root:
   ```bash
   uv run pixie validate <tool_id> --json
   ```

2. Parse the JSON. Branch on `overall`:
   - `"pass"` — one-line success. Surface any `warn` checks verbatim.
   - `"warn"` — report success and list every `warn` check verbatim.
   - `"fail"` — DO NOT claim success. Output the entire JSON in a fenced `json` block, explain which checks failed. End with: "Would you like me to hand this off to the `debug-tool` skill?" Stop.

3. Never paraphrase a failed report.

4. Hard stop after two consecutive failed runs.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't convert this Streamlit app cleanly because it uses <feature — e.g.,
"st.session_state", "multi-page layout", "more than 5 buttons">. Streamlit's
rerun loop is what makes those features work, and Pixie tools are stateless
request/response — there's no equivalent.

If you can rewrite the part you actually want as a single function that takes
the form inputs and returns the outputs, I can wrap that with `add-tool-from-description`.
```

## Do NOT

- Do NOT bundle Streamlit itself as a runtime dependency. The stub replaces it.
- Do NOT bind to `0.0.0.0` or any non-loopback interface; do NOT add authentication or multi-user concepts; do NOT add Docker, container, or cloud-deployment files.
- Do NOT write secret values into `main.py` or `tool.json`.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
