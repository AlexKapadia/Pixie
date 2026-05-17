---
name: add-tool-from-openapi-spec
description: Wraps a REST endpoint from an OpenAPI or Swagger spec as a Pixie tool - generates tool.json from spec parameters and a httpx main.py, then validates. Use when the user mentions OpenAPI, Swagger, openapi.yaml, or openapi.json. Do NOT use for a Python SDK repo (add-tool-from-repo) or vague API prose (add-tool-from-description).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Wrap a REST API endpoint as a Pixie tool

You are wrapping a single OpenAPI/Swagger endpoint so it can be called from Pixie's dashboard with form inputs. The generated tool calls the endpoint via `httpx` inside `/run` and renders the response per the spec's response schema.

## Routing check (do this first)

- If the user wants to wrap a CLI command, switch to `add-tool-from-cli-command`.
- If the user wants to wrap a local Python script, switch to `wrap-local-script`.
- If the user wants to import a packaged Pixie tool, switch to `import-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

Read these canonical references first:

- `tools/example-compound-interest/tool.json`
- `tools/example-compound-interest/main.py`
- `tools/example-compound-interest/pyproject.toml`

## Step 1. Load the spec

If the user gave a URL:

```bash
uv run python -c "
import httpx, json, sys
url = '<url>'
r = httpx.get(url, timeout=10.0, follow_redirects=True)
r.raise_for_status()
ct = r.headers.get('content-type', '')
if 'yaml' in ct or url.endswith('.yaml') or url.endswith('.yml'):
    import yaml; print(json.dumps(yaml.safe_load(r.text)))
else:
    print(r.text)
" > /tmp/pixie-openapi.json
```

If the user gave a local path, `Read` it directly. For YAML specs, the snippet above needs `pyyaml` — install transiently with `uv run --with pyyaml python -c "..."`.

## Step 2. Validate it's an OpenAPI document

`Read` the loaded JSON. Check for either `openapi: 3.x` or `swagger: 2.0` at the root. If neither, REFUSE — tell the user the document does not look like OpenAPI / Swagger.

## Step 3. Pick the endpoint to wrap

Parse the `paths` object. List every (method, path) pair. If there is exactly one, use it. Otherwise, ask the user which endpoint to wrap — show the table:

| # | Method | Path | Summary |
|---|---|---|---|

After the user picks one, capture: the method (`GET` / `POST` / etc.), the path, any path parameters, query parameters, the request body schema (if any), the response schema, and any `securitySchemes` the endpoint references.

## Step 4. Map parameters to Pixie inputs

Parameters with `in: path` or `in: query` become inputs. For `application/json` request bodies, expand each top-level property as a separate input using the same mapping:

| OpenAPI type | Pixie input |
|---|---|
| `string` (no `enum`/`format`) | `text` |
| `string` (`enum`) | `select` (options from `enum`) |
| `string` (`format: date` / `date-time`) | `date` / `datetime` |
| `string` (`format: binary` / `byte`) | `file` |
| `integer` / `number` | `number` (with `min`/`max` from `minimum`/`maximum`) |
| `boolean` | `toggle` |
| `array` of `enum` strings | `multiselect` |

## Step 5. Map the response schema to Pixie outputs

For `application/json`: top-level object with one obvious scalar field → `text`/`number`; top-level array → `table`; nested object → `markdown` (fenced JSON). For `image/*`, `audio/*`, `application/octet-stream` → `image`/`audio`/`file`. When unsure, default to one `markdown` output that pretty-prints the body and refine after the first run.

## Step 6. Detect auth requirements

Read the endpoint's `security:` block (or doc-level). For each scheme:

- `apiKey` in header → declare `API_KEY` secret; description names the header.
- `http` `bearer` → declare `BEARER_TOKEN`.
- `http` `basic` → declare `USERNAME` and `PASSWORD`.
- `oauth2` → REFUSE. Tell the user to obtain a token manually and treat it as `BEARER_TOKEN`.

## Step 7. Pick an ID and create the folder

```bash
mkdir -p tools/<tool_id>
```

Naming convention: kebab-case based on API name + endpoint, e.g. `github-create-issue`.

## Step 8. Write `tool.json` and `pyproject.toml`

`tool.json`: mapped inputs/outputs, declared secrets, base URL in the tool description. `pyproject.toml`: `fastapi`, `uvicorn`, `python-dotenv`, `httpx`. Pin `requires-python = ">=3.12"`.

## Step 9. Write `main.py`

`httpx.Client` call inside `/run`. Path parameters interpolated, query parameters as `params=`, body parameters as `json=`. Auth headers built from `os.environ`.

Pattern:

```python
import json, os, argparse
from pathlib import Path
import uvicorn, httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
TOOL_JSON = json.loads((Path(__file__).parent / "tool.json").read_text())
app = FastAPI()
BASE_URL = "<base_url_from_spec>"
PATH_TEMPLATE = "<path with {placeholders}>"
METHOD = "<GET|POST|PUT|PATCH|DELETE>"

class RunInput(BaseModel): pass  # one field per input

@app.get("/schema")
def schema(): return TOOL_JSON
@app.get("/healthz")
def healthz(): return {"ok": True}

@app.post("/run")
def run(payload: RunInput):
    data = payload.model_dump()
    path = PATH_TEMPLATE.format(**{k: data[k] for k in [<path param keys>]})
    headers: dict = {}
    if os.environ.get("API_KEY"):
        headers["<HEADER FROM SPEC>"] = os.environ["API_KEY"]
    if os.environ.get("BEARER_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['BEARER_TOKEN']}"
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        try:
            r = client.request(METHOD, path,
                params={k: data[k] for k in [<query keys>]},
                json={k: data[k] for k in [<body keys>]} if METHOD in ("POST","PUT","PATCH") else None,
                headers=headers)
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=502,
                detail=f"{exc.response.status_code}: {exc.response.text[:1000]}")
    body = r.json() if "application/json" in r.headers.get("content-type","") else r.text
    return {"response": {"value": json.dumps(body, indent=2) if isinstance(body,(dict,list)) else body}}

if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--port", type=int, required=True)
    uvicorn.run(app, host="127.0.0.1", port=p.parse_args().port, log_level="warning")
```

Tune the output shape per the actual response schema.

## Step 10. Install dependencies

```bash
cd tools/<tool_id> && uv sync
```

## Step 11. Validator handoff (mandatory final step)

1. From the repo root:
   ```bash
   uv run pixie validate <tool_id> --json
   ```

2. Parse the JSON. Branch on `overall`:
   - `"pass"` — one-line success. Surface any `warn` checks verbatim.
   - `"warn"` — report success and list every `warn` check verbatim.
   - `"fail"` — DO NOT claim success. Output the entire JSON verbatim. End with: "Would you like me to hand this off to the `debug-tool` skill?" Stop.

3. Never paraphrase a failed report. Note: the `sample_run_succeeds` check will hit the upstream API with sample inputs — if the API requires a real key, the user needs to run `set-secret` before validation passes.

4. Hard stop after two consecutive failed runs.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
I can't wrap this endpoint because <one-sentence reason>.

Pixie tools call REST APIs via `httpx` from a local subprocess. That means:
- No OAuth interactive flows — only static API keys or pre-obtained bearer tokens.
- No file streaming uploads larger than the tool's memory budget.
- No long-polling endpoints (use a CLI or a notebook instead).

If you can <suggested workaround — "supply a pre-obtained bearer token instead",
"point me at the smaller paginated endpoint">, re-run this skill.
```

## Do NOT

- Do NOT hardcode API keys into `main.py` or `tool.json`. Always declare under `secrets`.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT add OAuth interactive flows.
- Do NOT add Docker, container, or cloud-deployment files.
- Do NOT add telemetry, analytics, or remote reporting beyond the wrapped API call.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
