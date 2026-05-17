---
name: open-artefacts-folder
description: Opens Pixie's artefacts/ folder (or one tool's, or one run's) in the OS native file browser - Explorer, Finder, xdg-open. Use when the user asks to open, reveal, or 'show in Finder/Explorer' the artefacts or outputs folder. Do NOT use to list artefacts inline (list-outputs) or copy one out (copy-output-to).
allowed-tools: Bash, Read
---

# Open the Pixie artefacts folder

You are opening the `artefacts/` folder (or a specific tool's subfolder, or one run's subfolder) in the operating system's native file browser — Explorer on Windows, Finder on macOS, the default `xdg-open` target on Linux. You do not list, move, or copy any file in this skill.

## Routing check (do this first)

- If the user wants a markdown listing of saved outputs (not to open the folder), switch to `list-outputs`.
- If the user wants to find a specific output by name, switch to `find-output`.
- If the user wants to copy ONE file to a different path, switch to `copy-output-to`.
- If the user wants to open a TOOL'S source folder (not artefacts), the dashboard's "view source" button on the tool header is the right surface — name it and stop.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Resolve the target folder

| Scope | Path |
|---|---|
| Default | `artefacts/` at the repo root. |
| `--tool <id>` | `artefacts/<id>/`. |
| `--run <run_id>` | `artefacts/<tool_id>/<run_id>/` — look up tool_id via `GET /api/runs/<run_id>` or `pixie.db`. |

If the user said "the folder for the last X run", resolve via `view-runs <tool_id>` first — do NOT guess.

### 2. Confirm the folder exists

```bash
ls "<resolved path>"
```

If the folder does not exist, STOP. Tell the user no artefacts have been produced yet for that scope and suggest running the tool once.

### 3. Open the folder

Prefer Pixie's local endpoint if it is running — it deduplicates "is the path Pixie-controlled" checks and respects the user's chosen file browser if Pixie has one configured.

```bash
curl -s -X POST "http://127.0.0.1:8765/api/open-folder" \
  -H "Content-Type: application/json" \
  -d '{"path": "<resolved path>"}'
```

A `2xx` response means Pixie spawned the file browser. Stop.

### 4. Fallback (Pixie offline)

Launch the OS file browser directly. Cross-platform:

```bash
uv run python -c "
import os, sys, subprocess, pathlib
p = pathlib.Path(sys.argv[1]).resolve()
if sys.platform == 'win32':
    os.startfile(str(p))
elif sys.platform == 'darwin':
    subprocess.Popen(['open', str(p)])
else:
    subprocess.Popen(['xdg-open', str(p)])
print({'opened': str(p)})
" "<resolved path>"
```

`os.startfile` on Windows opens Explorer at the path. `open` on macOS uses Finder. `xdg-open` on Linux honours the user's `mimeapps.list` default — usually Files / Nautilus / Dolphin.

### 5. Confirm to the user

Print one line:

> "Opened `<absolute path>` in your file browser."

If running over SSH or in a headless environment, the OS opener may silently fail. Add a one-line note:

> "If nothing opened, you may be in a headless session — the folder is at `<absolute path>`. Copy that path into your file browser manually."

### 6. Do NOT run the validator

This skill does not modify any tool.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
The folder `<path>` does not exist yet. No artefacts have been produced for that
scope. Run the tool once to produce some outputs, then try again.
```

```
I will not open arbitrary folders — only the artefacts directory or a subfolder
under it. If you want to open a tool's source folder, the dashboard's "view source"
button on the tool header is the right surface.
```

## Do NOT

- Do NOT open any path outside `artefacts/`. If the resolved path is not a subpath of `artefacts/`, refuse.
- Do NOT create the folder if it doesn't exist — refuse instead.
- Do NOT list, copy, move, or delete any file in this skill.
- Do NOT open files (only folders) — `copy-output-to` is for files.
- Do NOT chain into a second opener if the first succeeds — one open per invocation.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically — name them and stop.
