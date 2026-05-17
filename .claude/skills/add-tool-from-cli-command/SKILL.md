---
name: add-tool-from-cli-command
description: Wraps a CLI binary or shell command (ffmpeg, curl, pandoc, imagemagick, yt-dlp) as a Pixie tool - generates tool.json from its flags plus a subprocess main.py, then validates. Use when the user names a CLI binary or shell command. Do NOT use for a Python script (wrap-local-script) or repo (add-tool-from-repo).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Wrap a CLI command as a Pixie tool

You are wrapping an existing command-line program (e.g., `ffmpeg`, `pandoc`, `yt-dlp`, `imagemagick`) so it can be invoked from Pixie's dashboard with form inputs. The generated tool runs the command via `subprocess.run` inside `/run` and captures stdout, stderr, and any files written to a temp directory.

## Routing check (do this first)

- If the user wants to wrap a Python function or script, switch to `wrap-local-script`.
- If the user wants to wrap a Streamlit or Gradio app, switch to `convert-streamlit-app` or `convert-gradio-app`.
- If the user wants to wrap a REST API, switch to `add-tool-from-openapi-spec`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Read before you act

Read these canonical references first:

- `tools/example-compound-interest/tool.json`
- `tools/example-compound-interest/main.py`
- `tools/example-compound-interest/pyproject.toml`

## Step 1. Verify the CLI is installed

```bash
uv run python -c "import shutil, sys; sys.exit(0 if shutil.which('<command>') else 1)"
```

If exit code is non-zero, REFUSE — tell the user to install the CLI first and how (link to upstream installer). Do not fall back to `pip install` for non-Python tools.

## Step 2. Refuse if the CLI is interactive

`Grep` the CLI's `--help` output for any of: `prompt`, `interactive`, `tty`. If the CLI requires a TTY to function and has no batch/non-interactive flag, REFUSE — Pixie cannot drive interactive CLIs.

```bash
<command> --help 2>&1 | head -50
```

If the help text shows `--non-interactive`, `--batch`, `--yes`, or `--quiet`, you can use that flag to neutralise interactivity. Otherwise refuse.

## Step 3. Clarify with the user

Ask the user (skip any that are obvious):

- Which CLI arguments are tool inputs? Each becomes a Pixie input.
- Which outputs do they want? Common shapes: captured stdout as `text`/`markdown`, written files as `file` outputs, exit code as `number`.
- What's the input file type, if any? (`file`, `image`, `audio`, `video`)
- Are there any flags that should be hardcoded (not user-controlled)?

## Step 4. Pick an ID and create the folder

```bash
mkdir -p tools/<tool_id>
```

Naming convention: prefix with the CLI name, e.g. `ffmpeg-convert`, `pandoc-md-to-pdf`, `yt-dlp-fetch`.

## Step 5. Write `tool.json`

Inputs map directly to CLI flags. Add a `description` per input pointing at the CLI's own docs entry (e.g., "Passed as `-vf` to ffmpeg"). Outputs typically:

- `stdout: text` or `stdout: log` for captured command output
- `<filename>: file` for each artefact written
- `exit_code: number` (optional, useful for debugging)

## Step 6. Write `pyproject.toml`

Minimal deps: `fastapi`, `uvicorn`, `python-dotenv`. No CLI-specific Python wrappers needed — we shell out directly. Pin `requires-python = ">=3.12"`.

## Step 7. Write `main.py`

Use `subprocess.run` with `shell=False` and a constructed argv list. Never use `shell=True` — flag values from user input would interpolate as shell metacharacters. Run inside a per-invocation temp dir so file outputs are isolated.

Skeleton:

```python
from pathlib import Path
import json, subprocess, tempfile, shutil, argparse, base64
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
TOOL_JSON = json.loads((Path(__file__).parent / "tool.json").read_text())
app = FastAPI()
CLI = "<command>"

if shutil.which(CLI) is None:
    raise RuntimeError(f"{CLI} not found on PATH")


class RunInput(BaseModel):
    pass  # one field per declared input


@app.get("/schema")
def schema(): return TOOL_JSON


@app.get("/healthz")
def healthz(): return {"ok": True}


@app.post("/run")
def run(payload: RunInput):
    with tempfile.TemporaryDirectory(prefix="pixie-<tool_id>-") as work:
        work_path = Path(work)
        # 1. write any file inputs to disk (data URI -> file)
        # 2. build argv list from flag mappings
        argv = [CLI, "--non-interactive", ...]
        # 3. run with strict timeout
        completed = subprocess.run(
            argv, cwd=work, capture_output=True, text=True,
            timeout=TOOL_JSON.get("max_runtime_seconds", 30) - 1,
        )
        if completed.returncode != 0:
            raise HTTPException(status_code=500, detail=completed.stderr.strip()[-2000:])
        # 4. collect outputs: stdout, any new files in work_path
        outputs: dict = {"stdout": {"value": completed.stdout}}
        for produced in work_path.iterdir():
            if produced.is_file():
                data = base64.b64encode(produced.read_bytes()).decode("ascii")
                outputs[produced.name] = {"value": {"filename": produced.name, "data": data}}
        return outputs


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
```

Tune the argv construction for the specific CLI. Always pass user input as separate argv items, never concatenated into a shell string.

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
I can't wrap `<command>` because <one-sentence reason>.

Pixie tools call CLIs via `subprocess.run` with no TTY. That means the CLI
must be:
- Installed on PATH already (Pixie does not install system packages).
- Driveable from argv flags alone — no interactive prompts.
- Capable of running with a strict timeout.

`<command>` fails on <specific point — e.g., "isn't installed on this machine",
"requires `--gui` and has no headless mode", "expects keystrokes from the user mid-run">.
If you can install it (or its `--non-interactive` flag exists in a newer version),
re-run this skill.
```

## Do NOT

- Do NOT use `shell=True` in `subprocess.run`. Always pass argv as a list.
- Do NOT install the CLI yourself (no `apt`, no `brew`, no `choco`, no `winget`).
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT add authentication or multi-user concepts.
- Do NOT add Docker, container, or cloud-deployment files.
- Do NOT write secret values into `main.py` or `tool.json`.
- Do NOT invoke other Pixie skills programmatically. Offer the user a choice and stop.
